"""M-2 step 2: the feed-anomaly classifier learns injected faults, beats chance, registers as a trial, abstains safely."""
import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.services import feed_anomaly as fa

START = datetime(2026, 11, 1, tzinfo=UTC)


def series(markets=6, n=1500, seed=1):
    rng = random.Random(seed)
    out = {}
    for m in range(markets):
        px, rows = 100.0 * (m + 1), []
        for i in range(n):
            px *= 1 + rng.gauss(0, 0.0008)
            half = px * rng.uniform(0.0002, 0.0015)
            rows.append({"t": START + timedelta(seconds=10 * i + rng.uniform(0, 3)),
                         "bid": str(round(px - half, 6)), "ask": str(round(px + half, 6)),
                         "bid_qty": str(round(rng.uniform(0.1, 5), 4)), "flags": ""})
        out[f"M{m}USDT"] = rows
    return out


def test_features_use_only_this_and_the_previous_quote():
    rows = series(markets=1, n=3)["M0USDT"]
    first = fa.features(None, rows[0])
    assert first[1:] == [0.0, 0.0, 0.0, 0.0]
    x = fa.features(rows[0], rows[1])
    assert len(x) == len(fa.FEATURES) and all(math.isfinite(v) for v in x)
    shifted = dict(rows[1], bid=str(Decimal(rows[1]["bid"]) * 10), ask=str(Decimal(rows[1]["ask"]) * 10))
    assert fa.features(rows[0], shifted)[4] == 1.0  # an order-of-magnitude jump is visible


def test_model_learns_injected_faults_out_of_sample():
    rows = fa.build_dataset(series(), seed=3)
    cut = int(len(rows) * 0.7)
    artifact = fa.fit(rows[:cut], epochs=150)
    report = fa.evaluate(artifact, rows[cut:])
    assert report["anomalies"] > 100
    assert report["model"]["auroc"] > 0.95, report
    assert report["model"]["auroc"] >= report["baseline"]["auroc"] - 0.02, report


def test_train_registers_a_trial_and_scan_abstains_on_a_bad_artifact(tmp_path):
    from gym.adapters.store import MarketDB
    from gym.domain.model import BookTop
    db = MarketDB(tmp_path / "market.db")
    for symbol, rows in series(markets=3, n=600).items():
        for r in rows:
            db.add_book_top(BookTop(symbol, r["t"], Decimal(r["bid"]), Decimal(r["ask"]), Decimal(r["bid_qty"]),
                                    Decimal(1), frozenset()), None)
    now = START + timedelta(days=2)
    out = fa.train(tmp_path, db, ["M0USDT", "M1USDT", "M2USDT"], START, START + timedelta(days=1), now=now)
    assert out["advisory_only"] and out["trials_for_question"] == 1 and out["test"]["model"]["auroc"] > 0.9
    scanned = fa.scan(tmp_path, db, "M0USDT", START, START + timedelta(days=1), out["artifact"], now=now)
    assert scanned["status"] == "SCORED" and scanned["quotes"] == 600
    path = tmp_path / "models" / f"{out['artifact']}.json"
    path.write_bytes(path.read_bytes().replace(b'"bias"', b'"bias "'))
    assert fa.scan(tmp_path, db, "M0USDT", START, START + timedelta(days=1), out["artifact"], now=now) == \
        {"status": "ABSTAIN", "reason": "corrupt", "flagged": []}
    assert fa.scan(tmp_path, db, "M0USDT", START, START + timedelta(days=1), out["artifact"],
                   now=now + timedelta(days=40))["status"] == "ABSTAIN"
    db.c.close()


def test_no_order_sizing_or_strategy_module_imports_the_classifier():
    src = Path(__file__).resolve().parents[1] / "src/gym"
    for path in [*src.glob("domain/*.py"), src / "services/session.py", src / "services/portfolio.py",
                 src / "services/paper.py"]:
        assert "feed_anomaly" not in path.read_text(encoding="utf-8"), path
