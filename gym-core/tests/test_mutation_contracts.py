"""Observable cash-journal, stop diagnostics and statistics boundary contracts."""
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Context, Decimal, DecimalException, localcontext

import pytest

from gym.contracts.stop_wire import (
    StopCommand,
    StopMode,
    StopResult,
    encode_reply,
    encode_request,
    verify_reply_for,
)
from gym.domain.performance import expected_max_sharpe
from gym.domain.sim import CashBook


def test_cash_posting_preserves_complete_auditable_receipt():
    book = CashBook({"USDT": Decimal("3.5")})
    book.post(datetime(2026, 1, 1, tzinfo=UTC), "USDT", Decimal("-1.25"), "FEE", "order-7")
    assert book.get("USDT") == Decimal("2.25")
    assert book.postings == [{"t": "2026-01-01T00:00:00.000000Z", "ccy": "USDT",
                              "amount": "-1.25", "kind": "FEE", "ref": "order-7"}]


def test_cash_overdraft_diagnostic_identifies_currency_kind_and_reference():
    book = CashBook({"USDT": Decimal(0)})
    with pytest.raises(ArithmeticError) as error:
        book.post(datetime(2026, 1, 1, tzinfo=UTC), "USDT", Decimal(-1), "FEE", "order-7")
    assert str(error.value) == "USDT balance would go negative (FEE order-7)"
    assert not book.postings


@pytest.mark.parametrize(("mode", "reply_epoch", "message"), [
    (StopMode.HALTED, 2, "stop has not been acknowledged for this request"),
    (StopMode.PAUSED, 1, "acknowledgment does not confirm the requested stop level"),
])
def test_stop_failure_distinguishes_uncorrelated_ack_from_insufficient_stop(mode, reply_epoch, message):
    correlation = bytes(range(16))
    request = encode_request(StopCommand.HALT, 1, correlation)
    reply = encode_reply(StopResult.ACK, mode, False, reply_epoch, correlation)
    with pytest.raises(ValueError) as error:
        verify_reply_for(request, reply)
    assert str(error.value) == message


def test_two_candidates_have_a_positive_luck_threshold():
    assert 0 < expected_max_sharpe(2, 0.01) < 0.1


@pytest.mark.parametrize(("trials", "variance"), [(1, 0.01), (0, 0.01), (100, -0.01),
                                                  (10**30, 0.0)])
def test_no_selection_or_no_variance_returns_zero_before_quantile_evaluation(trials, variance):
    assert expected_max_sharpe(trials, variance) == 0.0


def test_floor_quantum_coefficient_mutation_is_equivalent_under_decimal_contexts():
    # Decimal.quantize uses the target exponent, not its coefficient. Check signal behavior too.
    def observed(value, coefficient, places, context):
        with localcontext(context) as active:
            active.clear_flags()
            try:
                result = value.quantize(Decimal(coefficient).scaleb(-places), ROUND_DOWN)
                outcome = ("value", result.as_tuple())
            except DecimalException as error:
                outcome = ("error", type(error).__name__, str(error))
            return outcome, {signal.__name__: raised for signal, raised in active.flags.items()}

    for precision in (1, 2, 6, 28, 60):
        for rounding in ("ROUND_CEILING", "ROUND_DOWN", "ROUND_FLOOR", "ROUND_HALF_DOWN",
                         "ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_UP", "ROUND_05UP"):
            for trap in (False, True):
                context = Context(prec=precision, rounding=rounding, Emin=-9, Emax=9)
                for signal in context.traps:
                    context.traps[signal] = trap
                for raw in ("0", "-0", "1.2345", "-1.2345", "9.99999", "-9.99999",
                            "1E-9", "-1E-9", "1E9", "-1E9", "1E-20", "1E20"):
                    for places in (-100, -20, -10, -9, -1, 0, 1, 9, 10, 20, 100):
                        assert observed(Decimal(raw), 1, places, context) == observed(Decimal(raw), 2, places, context)
