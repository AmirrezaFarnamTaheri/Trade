"""Unit tests for Quant v3.1 domain gates and security/integrity hardening (F-03, F-05, F-07)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.api import _origin_allowed, guard
from gym.domain.quant_v3_gates import (
    compute_leave_k_out_fragility,
    compute_local_fx_basis_stress,
    compute_ofi_toxicity,
    compute_pool_crowding_veto,
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

    async def _exercise() -> None:
        app = web.Application(middlewares=[guard("secret-token")])
        app.router.add_get("/api/health", lambda _: web.json_response({"ok": True}))
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
