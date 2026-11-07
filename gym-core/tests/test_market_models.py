"""Run: .venv/Scripts/python.exe -m unittest tests.test_market_models"""
import copy
import json
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

from gym.domain.market_models import (
    LocalLiquidity,
    decimal,
    evaluate_artifact,
    financing,
    implied_fx,
    liquidity,
    roundtrip_spacing,
)

T = datetime(2026, 1, 1, tzinfo=UTC)


def q(second=0, bid="100", ask="101", status="OPEN"):
    return {"at": (T + timedelta(seconds=second)).isoformat(), "bid": bid, "ask": ask,
            "status": status, "qualified": True}


def liquidity_args(samples):
    return {"samples": samples, "delta_up": "0.01", "delta_down": "0.01", "overshoot_step": "0.01", "alpha": "0.08",
                "overshoot_probability": "0.08", "dc_surprise": "0.0834", "overshoot_surprise": "2.5257",
                "sigma_per_sqrt_second": "0.01"}


def spacing_args():
    return {"spacing": "0.02", "fee_buy": "0.001", "fee_sell": "0.002", "spread": "0.003",
                "slippage_buy": "0.001", "slippage_sell": "0.001", "quote_currency": "USDT"}


def finance_args():
    return {"product": "MARGIN", "side": "LONG", "quote_currency": "USDT", "collateral": "50", "quantity": "1", "borrowed": "50",
                "interest_rate": "0.01", "interest_period_seconds": "86400", "entry_fee": "0", "exit_fee": "0",
                "maintenance_ratio": "0.1", "closure_liquidation": "PAUSE",
                "samples": [q(0, "99", "100"), q(86400, "40", "41", "CLOSED"), q(172800, "39", "40")]}


class MarketModelsTests(unittest.TestCase):
    def test_decimal_boundary(self):
        for value in (1, 0.1, True, None, [], "NaN", "Infinity", "1e-3", " 1", "-1", "1_000", "01", "0." + "1" * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decimal(value)
        self.assertEqual(decimal("0.100000000000000000001"), D("0.100000000000000000001"))
        self.assertEqual(decimal(D("1e-9")), D("0.000000001"))

    def test_spacing_roundtrip_strict(self):
        args = spacing_args()
        result = roundtrip_spacing(**args)
        self.assertEqual(result["additive_roundtrip_cost"], D("0.008"))
        for spacing in ("0.001", "0.008", str(result["required_spacing"])):
            with self.subTest(spacing=spacing), self.assertRaises(ValueError):
                roundtrip_spacing(**(args | {"spacing": spacing}))
        for name in ("fee_buy", "fee_sell", "spread", "slippage_buy", "slippage_sell"):
            changed = roundtrip_spacing(**(args | {name: "0.004"}))
            self.assertGreater(changed["required_spacing"], result["required_spacing"])
        with self.assertRaises(ValueError):
            roundtrip_spacing(**(args | {"quote_currency": "IRT"}))

    def test_liquidity_bid_ask_asymmetry_and_overshoot(self):
        samples = [q(0, "100", "100"), q(1, "100", "103"), q(2, "102", "103"),
                   q(3, "106", "107"), q(4, "102", "106"), q(5, "101", "102")]
        result = liquidity(**liquidity_args(samples))
        events = [(x["at"], x["event"]) for x in result["events"]]
        self.assertEqual([code for _, code in events], [1, 2, 2, -1])
        self.assertEqual(events[0][0], samples[2]["at"])
        self.assertEqual(events[-1][0], samples[5]["at"])
        self.assertEqual(result["observed_sample_count"], 6)
        self.assertEqual(result["expected_dc_count"], D(5))
        self.assertFalse(result["certified"])

    def test_liquidity_closure_and_bad_samples(self):
        samples = [q(0), q(1, "90", "91", "CLOSED"), q(2, "105", "106")]
        result = liquidity(**liquidity_args(samples))
        self.assertEqual(result["open_sample_count"], 2)
        self.assertTrue(result["events"][0]["gap"])
        self.assertEqual(result["observed_open_seconds"], 0)
        for bad in ([], [q(), q()], [q() | {"qualified": False}], [q() | {"status": "UNKNOWN"}], [q(0, "102", "101")]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                liquidity(**liquidity_args(bad))

    def test_local_liquidity_null(self):
        model = LocalLiquidity()
        h1 = D("0.92") * D("0.0834") + D("0.08") * D("2.5257")
        self.assertEqual(model.h1, h1)
        self.assertLess(model.update(1), 0)
        self.assertGreater(model.update(2), 0)
        for event in (0, 3, True, "1"):
            with self.assertRaises(ValueError):
                model.update(event)
        with self.assertRaises(ValueError):
            LocalLiquidity(overshoot_probability="0")

    def test_seeded_gbm_golden_counts(self):
        rng, log_price, samples = random.Random(714), 0.0, []
        for second in range(1001):
            log_price += rng.gauss(0, 0.01)
            price = D(100) * D(str(log_price)).exp()
            samples.append(q(second, format(price, "f"), format(price, "f")))
        result = liquidity(**liquidity_args(samples))
        self.assertEqual((result["dc_count"], result["event_count"]), (206, 489))
        self.assertEqual(result["expected_dc_count"], D(1000))

    def test_fx_dispersion_and_closed_reference(self):
        pairs = [{"base": "BTC", "tmn": q(0, "600", "606"), "usdt": q(0, "2", "3")},
                 {"base": "ETH", "tmn": q(0, "660", "666"), "usdt": q(0, "2", "3")}]
        args = {"pairs": pairs, "reference": None, "as_of": q()["at"], "max_age_seconds": "5", "max_skew_seconds": "1"}
        result = implied_fx(**args)
        self.assertEqual(result["median_tmn_per_usdt"], D(210))
        self.assertEqual(result["range_dispersion"], D(20))
        self.assertFalse(result["executable"])
        self.assertIsNone(result["reference_mid"])
        self.assertEqual(implied_fx(**(args | {"reference": q(0, "199", "201")}))["reference_mid"], D(200))
        for bad in (q(0, status="CLOSED"), q(-6), q(1), q(0, "102", "101"), q() | {"qualified": False}, q() | {"status": "UNKNOWN"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                implied_fx(**(args | {"reference": bad}))
        bad_pairs = copy.deepcopy(pairs)
        bad_pairs[1]["usdt"] = q(-2, "2", "3")
        with self.assertRaises(ValueError):
            implied_fx(**(args | {"pairs": bad_pairs}))
        with self.assertRaises(ValueError):
            implied_fx(**(args | {"pairs": pairs + [pairs[0]]}))

    def test_long_liquidation_closure_debt_and_interest(self):
        args = finance_args()
        report = financing(**args)
        first, closed, reopened = report["history"]
        self.assertEqual(first["equity_quote"], D(49))
        self.assertEqual(closed["debt_units"], D("50.50"))
        self.assertEqual(closed["action"], "LIQUIDATION_PAUSED")
        self.assertFalse(closed["paper_send_allowed"])
        self.assertEqual(reopened["action"], "PAPER_LIQUIDATION")
        self.assertEqual(reopened["debt_units"], D(12))
        self.assertEqual(reopened["equity_quote"], D(-12))
        self.assertEqual(report["interest_accrued_units"], D(1))
        for policy, action in (("UNKNOWN", "LIQUIDATION_UNKNOWN"), ("CONTINUE", "LIQUIDATION_DUE_UNEXECUTABLE")):
            changed = financing(**(args | {"closure_liquidation": policy}))
            self.assertEqual(changed["history"][1]["action"], action)
            self.assertEqual(changed["history"][1]["base_units"], 1)
        later = financing(**(args | {"samples": args["samples"] + [q(259200, "39", "40")]}))
        self.assertGreater(later["history"][-1]["debt_units"], D(12))

    def test_short_mark_at_ask_and_partial_cover(self):
        args = finance_args() | {"side": "SHORT", "product": "TRADE_CREDIT", "borrowed": "1", "collateral": "20",
                                    "samples": [q(0, "100", "101"), q(86400, "149", "150")]}
        report = financing(**args)
        self.assertEqual(report["history"][0]["equity_quote"], D(19))
        end = report["history"][-1]
        self.assertEqual(end["action"], "PAPER_LIQUIDATION")
        self.assertEqual(end["debt_units"], D("0.21"))
        self.assertEqual(end["liability_quote"], D("31.50"))
        self.assertEqual(end["equity_quote"], D("-31.50"))
        self.assertFalse(report["venue_terms_verified"])

    def test_finance_validation(self):
        args = finance_args()
        for change in ({"borrowed": "0"}, {"samples": [q(status="CLOSED")]}, {"samples": [q(), q()]},
                       {"closure_liquidation": "YES"}, {"quote_currency": "USD"}, {"side": "SHORT"},
                       {"maintenance_ratio": "1"}, {"interest_period_seconds": "0"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                financing(**(args | change))

    def test_artifact_schema_and_times(self):
        artifact = {"model": "spacing", "parameters": spacing_args()}
        self.assertEqual(evaluate_artifact(artifact)["mode"], "PAPER_ONLY")
        for bad in (artifact | {"extra": 1}, {"model": "unknown", "parameters": {}},
                    artifact | {"parameters": spacing_args() | {"currency": "USD"}},
                    artifact | {"parameters": []}):
            with self.assertRaises(ValueError):
                evaluate_artifact(bad)
        for at in ("2026-01-01T00:00:00", "nonsense", 1, "2026-01-01"):
            with self.assertRaises(ValueError):
                liquidity(**liquidity_args([q() | {"at": at}]))

    def test_cli_success_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.json", Path(directory) / "report.json"
            artifact = {"model": "spacing", "parameters": spacing_args()}
            source.write_text(json.dumps(artifact), encoding="utf-8")
            command = [sys.executable, "-m", "gym.cli", "paper-research", str(source)]
            success = subprocess.run(command + ["--output", str(output)], capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            report = json.loads(success.stdout)
            self.assertEqual(report, json.loads(output.read_text("utf-8")))
            self.assertEqual(report["result"]["additive_roundtrip_cost"], "0.008")
            self.assertFalse(report["funded_authority"])
            self.assertFalse(report["order_submitted"])
            exists = subprocess.run(command + ["--output", str(output)], capture_output=True, text=True)
            self.assertEqual(exists.returncode, 2)
            for invalid in (artifact | {"extra": True}, artifact | {"parameters": spacing_args() | {"fee_buy": 0.1}},
                            artifact | {"parameters": spacing_args() | {"spacing": "0.001"}}):
                source.write_text(json.dumps(invalid), encoding="utf-8")
                error = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(error.returncode, 2, error.stderr)
                self.assertIn("error:", error.stderr)
                self.assertEqual(error.stdout, "")
            source.write_text('{"model":"spacing","model":"fx","parameters":{}}', encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
            cases = {
                "liquidity": liquidity_args([q(), q(1, "105", "106")]),
                "financing": finance_args(),
                "fx": {"pairs": [{"base": "BTC", "tmn": q(0, "600", "606"), "usdt": q(0, "2", "3")}],
                           "reference": None, "as_of": q()["at"], "max_age_seconds": "1", "max_skew_seconds": "0"},
            }
            for name, parameters in cases.items():
                source.write_text(json.dumps({"model": name, "parameters": parameters}), encoding="utf-8")
                probe = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(probe.returncode, 0, probe.stderr)
                self.assertEqual(json.loads(probe.stdout)["mode"], "PAPER_ONLY")
            protected = Path(directory) / "DATA" / "never.json"
            denied = subprocess.run(command + ["--output", str(protected)], capture_output=True, text=True)
            self.assertEqual(denied.returncode, 2)
            self.assertIn("outside data/", denied.stderr)
            self.assertFalse(protected.exists())
            for existing in ("compare", "paper"):
                help_result = subprocess.run([sys.executable, "-m", "gym.cli", existing, "--help"], capture_output=True, text=True)
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn("--candidate" if existing == "compare" else "--strategy", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
