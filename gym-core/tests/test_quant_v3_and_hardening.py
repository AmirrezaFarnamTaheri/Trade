"""Unit tests for Quant v3.1 domain gates and security/integrity hardening (F-03, F-05, F-07)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.api import _origin_allowed, guard
from gym.domain.promoted_strategies import enforce_spot_only_strategy
from gym.domain.quant_v3_gates import (
    assert_irr_tmn_denomination_sane,
    bayesian_fractional_kelly_size,
    compute_deflated_sharpe_ratio,
    compute_leave_k_out_fragility,
    compute_local_fx_basis_stress,
    compute_ofi_toxicity,
    compute_pool_crowding_veto,
    consensus_kalman_fx_rate,
    decompose_dual_factor_fx_return,
    pre_trade_implementation_shortfall_gate,
)
from gym.services.experiments.gru_engine import EnsembleGRU, GRUArtifactError
from gym.services.experiments.io_utils import semantic_engine_digest


def test_quant_v3_ofi_toxicity() -> None:
    assert compute_ofi_toxicity([]) == (0.0, 0.0)
    assert compute_ofi_toxicity([("BUY", -5.0), ("SELL", float("nan"))]) == (0.0, 0.0)
    ofi, tox = compute_ofi_toxicity([("BUY", 75.0), ("SELL", 25.0)])
    assert ofi == pytest.approx(0.5)
    assert tox == pytest.approx(0.5)
    ofi_s, tox_s = compute_ofi_toxicity([("SELL", 100.0)])
    assert ofi_s == pytest.approx(-1.0)
    assert tox_s == pytest.approx(1.0)


def test_quant_v3_implementation_shortfall_gate() -> None:
    admit, net, hurdle = pre_trade_implementation_shortfall_gate(
        50.0, spread_bps=10.0, l2_walk_bps=4.0, fee_bps=16.0, margin_multiple=1.5,
    )
    # total_cost = 30.0 -> hurdle = 45.0 -> 50 >= 45 admitted, net = 20.0
    assert admit is True
    assert net == pytest.approx(20.0)
    assert hurdle == pytest.approx(45.0)

    admit2, net2, _ = pre_trade_implementation_shortfall_gate(
        40.0, spread_bps=10.0, l2_walk_bps=4.0, fee_bps=16.0, margin_multiple=1.5,
    )
    assert admit2 is False
    assert net2 == pytest.approx(10.0)


def test_quant_v3_leave_k_out_fragility() -> None:
    curve = compute_leave_k_out_fragility([300.0, 200.0, -50.0, -50.0], max_k=4)
    assert curve[0]["k_removed"] == 0 and curve[0]["sum_bps"] == 400.0
    assert curve[2]["k_removed"] == 2 and curve[2]["sum_bps"] == -100.0
    assert curve[4]["remaining"] == 0 and curve[4]["sum_bps"] == 0.0


def test_quant_v3_local_fx_basis_and_pool_crowding_veto() -> None:
    assert compute_local_fx_basis_stress(0.0, 60000.0, 100.0) is None
    # Implied USDT = 6_060_000 / 60_000 = 101.0 vs global 100.0 -> +99.5 bps
    basis = compute_local_fx_basis_stress(6_060_000.0, 60_000.0, 100.0)
    assert basis is not None and 99.0 < basis < 100.0

    veto_ok, reasons_ok = compute_pool_crowding_veto(12.0, 0.40)
    assert veto_ok is False and reasons_ok == []

    veto_bad, reasons_bad = compute_pool_crowding_veto(42.5, 0.91)
    assert veto_bad is True and len(reasons_bad) == 2


def test_gru_expiry_enforcement_and_seed_propagation(tmp_path: Path) -> None:
    ens = EnsembleGRU(input_dim=4, hidden_dim=3, task="binary", seeds=(7, 19))
    assert ens._seeds == (7, 19)
    p = tmp_path / "expiring.json"
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    ens.save_json(p, metadata={"expires_at": (now - timedelta(hours=1)).isoformat()})

    with pytest.raises(GRUArtifactError, match="expired"):
        EnsembleGRU.load_json(p, now=now)

    # Disabling expiry check allows offline historical inspection
    loaded, meta = EnsembleGRU.load_json(p, now=now, enforce_expiry=False)
    assert len(loaded.models) == 2 and "expires_at" in meta

    # Future expiry passes cleanly
    ens.save_json(p, metadata={"expires_at": (now + timedelta(days=30)).isoformat()})
    loaded2, _ = EnsembleGRU.load_json(p, now=now)
    assert len(loaded2.models) == 2


def test_semantic_engine_digest_stable() -> None:
    d1 = semantic_engine_digest()
    d2 = semantic_engine_digest()
    assert len(d1) == 64 and d1 == d2


def test_api_origin_and_session_rotate_rate_limit() -> None:
    import asyncio

    assert _origin_allowed("http://127.0.0.1:8787") is True
    assert _origin_allowed("http://localhost:8787") is True
    assert _origin_allowed("https://evil.example") is False

    async def _health(_):
        return web.json_response({"ok": True})

    async def _exercise() -> None:
        app = web.Application(middlewares=[guard("secret-token")])
        app.router.add_get("/api/health", _health)
        async with TestClient(TestServer(app)) as client:
            r_bad_origin = await client.get("/api/health", headers={"Origin": "https://evil.example"})
            assert r_bad_origin.status == 403
            r_bad_site = await client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"})
            assert r_bad_site.status == 403

            tok = "secret-token"
            for _ in range(5):
                r = await client.post("/api/session/rotate", headers={"X-Gym-Token": tok})
                assert r.status == 200
                tok = (await r.json())["token"]
            r_limited = await client.post("/api/session/rotate", headers={"X-Gym-Token": tok})
            assert r_limited.status == 429

    asyncio.run(_exercise())


def test_adr_0009_spot_only_gate_and_quant_fx_dsr_kelly() -> None:
    enforce_spot_only_strategy("slow-s1-trend", leverage=1.0, short_allowed=False)
    with pytest.raises(ValueError, match="ADR 0009"):
        enforce_spot_only_strategy("bear-short", short_allowed=True)
    with pytest.raises(ValueError, match="ADR 0009"):
        enforce_spot_only_strategy("levered-5x", leverage=5.0)

    g, fx, basis = decompose_dual_factor_fx_return(0.05, 0.03, 0.015)
    assert (g, fx, basis) == (0.015, 0.03, 0.005)

    assert consensus_kalman_fx_rate([]) is None
    assert consensus_kalman_fx_rate([(60000.0, 0.0)]) is None
    # Tighter spread (5 bps) dominates wider spread (20 bps) by 16x weight
    fx_rate = consensus_kalman_fx_rate([(60000.0, 5.0), (61000.0, 20.0)])
    assert fx_rate is not None and 60000.0 < fx_rate < 60100.0

    assert_irr_tmn_denomination_sane(60500.0, 60000.0)
    with pytest.raises(ValueError, match="denomination mismatch"):
        assert_irr_tmn_denomination_sane(600000.0, 60000.0)  # 10x IRR/TMN bug
    with pytest.raises(ValueError, match="finite and positive"):
        assert_irr_tmn_denomination_sane(-1.0, 60000.0)

    assert compute_deflated_sharpe_ratio(1.0, 2, 10) == 0.0
    dsr_single = compute_deflated_sharpe_ratio(0.20, 250, 1)
    dsr_many = compute_deflated_sharpe_ratio(0.20, 250, 50)
    assert 0.99 < dsr_single <= 1.0
    assert 0.0 < dsr_many < dsr_single

    assert bayesian_fractional_kelly_size(-0.01, 0.04, 0.01) == 0.0
    sz_full = bayesian_fractional_kelly_size(0.03, 0.04, 0.02, kappa=0.25, max_fraction=0.30, drawdown=0.0)
    sz_dd = bayesian_fractional_kelly_size(0.03, 0.04, 0.02, kappa=0.25, max_fraction=0.30, drawdown=0.075, max_drawdown=0.15)
    assert 0.0 < sz_full < 0.30 and sz_dd == pytest.approx(sz_full * 0.5, rel=1e-3)


def test_nobitex_orderbook_reference_price_denomination_guard() -> None:
    from gym.adapters.nobitex import parse_nobitex_orderbook

    payload = {"bids": [["600000", "1.0"]], "asks": [["601000", "1.0"]], "lastUpdate": 1700000000000}
    ts = datetime(2026, 11, 26, tzinfo=UTC)
    qs = parse_nobitex_orderbook("USDTIRT", payload, ts, convert_rls_to_tmn=True, reference_price=60000.0)
    assert qs is not None and float(qs.bid) == 60000.0
    with pytest.raises(ValueError, match="denomination mismatch"):
        parse_nobitex_orderbook("USDTIRT", payload, ts, convert_rls_to_tmn=False, reference_price=60000.0)


def test_quant_v3_audit_and_fx_attribution_on_synthetic_db(tmp_path: Path) -> None:
    import sqlite3

    from gym.services.promoted_portfolio import compute_dual_factor_fx_attribution
    from gym.services.quant_v3_audit import run_and_publish_quant_v3_audit

    attr = compute_dual_factor_fx_attribution(
        local_tmn_ret=0.05, global_usdt_ret=0.02, usdt_tmn_ret=0.025,
        venue_usdt_quotes=[(60000.0, 5.0), (60500.0, 20.0)],
    )
    assert attr["venue_basis_ret"] == pytest.approx(0.005)
    assert attr["consensus_usdt_tmn"] is not None

    db_path = tmp_path / "audit.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t TEXT, o TEXT, h TEXT, l TEXT, c TEXT, v TEXT)")
    con.execute("CREATE TABLE book_top (instrument_id TEXT, ts_avail TEXT, bid TEXT, ask TEXT)")
    con.executemany("INSERT INTO instruments VALUES (?, ?)", [(1, "BTCUSDT"), (2, "BTCTMN"), (3, "USDTTMN")])
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for d in range(80):
        ts = (t0 + timedelta(days=d)).isoformat().replace("+00:00", "Z")
        btc = 50000.0 * (1.002 ** d)
        fx = 60000.0 * (1.001 ** d)
        con.execute("INSERT INTO venue_candles VALUES (1,'1d',?,?,?,?,?,?)", (ts, str(btc), str(btc * 1.01), str(btc * 0.99), str(btc), "100"))
        con.execute("INSERT INTO venue_candles VALUES (2,'1d',?,?,?,?,?,?)", (ts, str(btc * fx), str(btc * fx), str(btc * fx), str(btc * fx), "100"))
        con.execute("INSERT INTO venue_candles VALUES (3,'1d',?,?,?,?,?,?)", (ts, str(fx), str(fx), str(fx), str(fx), "100"))
        con.execute("INSERT INTO book_top VALUES ('wallex:BTCUSDT', ?, ?, ?)", (ts, str(btc * 0.9995), str(btc * 1.0005)))
        con.execute("INSERT INTO book_top VALUES ('wallex:USDTTMN', ?, ?, ?)", (ts, str(fx * 0.999), str(fx * 1.001)))
    con.commit()
    con.close()

    out_dir = tmp_path / "out"
    rep = run_and_publish_quant_v3_audit(db_path, out_dir)
    assert rep["catalog_dsr_audit"]["strategies_audited"] == 18
    assert rep["fx_dual_factor_attribution"]["status"] == "OK"
    assert rep["empirical_slippage_calibration"]["rows_scanned"] == 80
    assert rep["ml_shadow_readiness"]["permitted_portfolio_weight"] == 0.0
    assert (out_dir / "18-strategy-dsr-fx-slippage-audit.md").is_file()
    assert (out_dir / "18-strategy-dsr-fx-slippage-audit.json").is_file()


def test_quant_v3_audit_no_hardcoded_promotion_and_surfaces_exceptions() -> None:
    from gym.services.quant_v3_audit import _simulate_strategy_on_bars

    # Empty history must never promote slow-s1-trend
    empty_res = _simulate_strategy_on_bars("slow-s1-trend", {}, [])
    assert empty_res["tier"] != "PROMOTE_REFERENCE"
    assert empty_res["errors"] == 0

    # Strategy exceptions must be surfaced, never silently treated as abstentions
    class _BoomBar:
        pass

    boom_res = _simulate_strategy_on_bars("slow-s1-trend", {}, [(_BoomBar(), 100.0, 0.0)])  # type: ignore[list-item]
    assert boom_res["errors"] == 1
    assert boom_res["last_error"] is not None
    assert boom_res["tier"] == "ERROR_STRATEGY_EXCEPTION"
