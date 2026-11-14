"""Version 1 intraday rule for one USDTTMN session, with USDT as the resting state and the unit of account.

The benchmark is holding USDT, so a session that never trades nets exactly zero. Two directions are separate trial
families: SELL_RICH sells owned USDT above a rolling mean and buys it back; BUY_CHEAP buys USDT on borrowed Toman
below the mean and sells it again (a margin long, charged `financing_bps` on the loan).

Every order is a limit: entries at the signal threshold, exits through the spread by at most `max_slip_bps`. Nothing is a market
order. One pass over the quotes in availability order; a decision at a bar close can only fill on a later quote.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext

from .bars import qualified
from .model import TEHRAN, iso

BAR = timedelta(minutes=5)
LATENCY = timedelta(milliseconds=500)
SESSION_CLOSE = time(23, 30)  # venue rule wallex-usdttmn-closure-2330-1130 (status REPORTED)
DAILY_BUY_QUOTA = Decimal(2000)  # USDT bought per user per Tehran day (status REPORTED)
DIRECTIONS = ("SELL_RICH", "BUY_CHEAP")


@dataclass(frozen=True)
class Params:
    direction: str = "SELL_RICH"
    lookback: int = 12  # bars in the rolling mean
    entry_bps: int = 50  # distance from the mean that opens a trade
    size_usdt: Decimal = Decimal(1000)
    halt_bps: int = 300  # a bar-to-bar move this large stops new trades for the rest of the session
    max_slip_bps: int = 50  # how far through the touch an exit limit may reach
    flat_minutes: int = 15  # exits are forced this long before the session closes
    financing_bps: Decimal = Decimal(0)  # BUY_CHEAP only: margin fees as a share of the loan, per trade

    def __post_init__(self):
        if self.direction not in DIRECTIONS or not 2 <= self.lookback <= 500 or not 1 <= self.flat_minutes <= 240:
            raise ValueError("invalid intraday direction, lookback or flat time")
        if min(self.entry_bps, self.halt_bps, self.max_slip_bps) < 1 or not 0 < self.size_usdt <= DAILY_BUY_QUOTA:
            raise ValueError("intraday thresholds must be positive and the size within the daily buy quota")
        if self.financing_bps < 0 or (self.financing_bps and self.direction != "BUY_CHEAP"):
            raise ValueError("financing applies to BUY_CHEAP only and cannot be negative")


def run_session(quotes, params: Params, *, fee_rate: Decimal, quota_used: Decimal = Decimal(0)) -> dict:
    """Replay one Tehran-day session. `quotes` are that day's BookTop rows in availability order."""
    if not isinstance(fee_rate, Decimal) or not 0 <= fee_rate < 1 or not 0 <= quota_used <= DAILY_BUY_QUOTA:
        raise ValueError("invalid fee rate or used quota")
    if any(b.ts_avail < a.ts_avail for a, b in zip(quotes, quotes[1:], strict=False)):
        raise ValueError("quotes are not availability ordered")
    if len({q.ts_avail.astimezone(TEHRAN).date() for q in quotes}) > 1:
        raise ValueError("a session holds one Tehran day")
    with localcontext() as context:
        context.prec = 40
        return _run(quotes, params, fee_rate, quota_used)


@dataclass
class _Book:
    """Changes from the resting state. BUY_CHEAP carries its loan as negative Toman."""
    sell_rich: bool
    bought: Decimal
    usdt: Decimal = Decimal(0)
    tmn: Decimal = Decimal(0)
    fills: list = field(default_factory=list)

    def exposed(self) -> bool:
        return self.tmn > 0 if self.sell_rich else self.usdt > 0

    def trade(self, top, side, quantity, fee, why, *, loan_cost=Decimal(0), spend_all=False):
        price = top.ask if side == "BUY" else top.bid
        if side == "BUY":
            self.bought += quantity
            self.usdt += quantity * (1 - fee)
            # Spending all of it leaves exactly nothing, not a rounding remainder.
            self.tmn = Decimal(0) if spend_all else self.tmn - quantity * price * (1 + loan_cost)
        else:
            self.usdt -= quantity
            self.tmn += quantity * price * (1 - fee)
        self.fills.append({"at": iso(top.ts_avail), "side": side, "usdt": str(quantity), "price": str(price), "reason": why})


def _enter(book, top, p, fee, edge):
    """A limit at the signal threshold, tried once: no fill if the price has already come back."""
    room = DAILY_BUY_QUOTA - book.bought  # SELL_RICH only sells what the remaining quota can buy back
    if book.sell_rich and top.bid >= edge:
        quantity = min(p.size_usdt, room, top.bid_qty or Decimal(0))
        if quantity > 0:
            book.trade(top, "SELL", quantity, fee, "SIGNAL")
    elif not book.sell_rich and top.ask <= edge:
        quantity = min(p.size_usdt, room, top.ask_qty or Decimal(0))
        if quantity > 0:
            book.trade(top, "BUY", quantity, fee, "SIGNAL", loan_cost=p.financing_bps / 10000)


def _work_exit(book, top, fee, limit, why):
    """Fill what the touch shows if it is inside the exit limit; the rest keeps working on later quotes."""
    if book.sell_rich and top.ask <= limit:
        whole = book.tmn / top.ask
        quantity = min(whole, DAILY_BUY_QUOTA - book.bought, top.ask_qty or Decimal(0))
        if quantity > 0:
            book.trade(top, "BUY", quantity, fee, why, spend_all=quantity == whole)
    elif not book.sell_rich and top.bid >= limit:
        quantity = min(book.usdt, top.bid_qty or Decimal(0))
        if quantity > 0:
            book.trade(top, "SELL", quantity, fee, why)


def _decide(book, p, closes, close, bar_end, force_at, halted, exiting):
    """The order a closed bar asks for, if any: (kind, decision time, exit reason or entry threshold)."""
    mean = sum(closes) / len(closes)
    if book.exposed():
        back = close <= mean if book.sell_rich else close >= mean
        return ("EXIT", bar_end, "HALT" if halted else "MEAN") if (back or halted) and not exiting else None
    if halted or exiting or len(closes) < p.lookback or bar_end >= force_at:
        return None
    edge = mean * (1 + Decimal(p.entry_bps) / 10000 * (1 if book.sell_rich else -1))
    return ("ENTRY", bar_end, edge) if (close > edge if book.sell_rich else close < edge) else None


def _run(quotes, p, fee, quota_used):
    book = _Book(p.direction == "SELL_RICH", quota_used)
    closes = []
    bar_end = last_mid = last = pending = exit_limit = None
    halted = exiting = False
    decisions = trips = 0
    for top in quotes:
        if not qualified(top):
            continue
        local = top.ts_avail.astimezone(TEHRAN)
        force_at = datetime.combine(local.date(), SESSION_CLOSE, TEHRAN) - timedelta(minutes=p.flat_minutes)
        if bar_end is None:
            bar_end = _bar_end(top.ts_avail)
        while top.ts_avail >= bar_end:  # the bar that just closed is decided on its last mid, never on this quote
            if last_mid is not None:
                decisions += 1
                halted = halted or (bool(closes) and abs(last_mid / closes[-1] - 1) * 10000 >= p.halt_bps)
                closes = [*closes, last_mid][-p.lookback:]
                order = _decide(book, p, closes, last_mid, bar_end, force_at, halted, exiting)
                if order:
                    pending, exiting, exit_limit = order, order[0] == "EXIT", None
            bar_end, last_mid = bar_end + BAR, None
        if book.exposed() and not exiting and top.ts_avail >= force_at:
            exiting, exit_limit, pending = True, None, ("EXIT", top.ts_avail - LATENCY, "SESSION_CLOSE")
        if pending and top.ts_avail >= pending[1] + LATENCY:
            if pending[0] == "ENTRY":
                if top.ts_avail < force_at:
                    _enter(book, top, p, fee, pending[2])
                pending = None
            else:
                if exit_limit is None:  # set once from the first quote after the decision; later quotes cannot move it
                    slip = Decimal(p.max_slip_bps) / 10000
                    exit_limit = top.ask * (1 + slip) if book.sell_rich else top.bid * (1 - slip)
                _work_exit(book, top, fee, exit_limit, pending[2])
                if not book.exposed() or (book.sell_rich and book.bought >= DAILY_BUY_QUOTA):
                    pending, exiting = None, book.exposed()
                    trips += not exiting
        last_mid, last = (top.bid + top.ask) / 2, top
    # What is left is valued where it could be traded: Toman owned buys USDT at the ask, Toman owed costs the bid.
    tmn = book.tmn
    residual = Decimal(0) if last is None or tmn == 0 else tmn / last.ask * (1 - fee) if tmn > 0 else tmn / last.bid / (1 - fee)
    return {"net_usdt": str(book.usdt + residual), "state": "STRANDED" if book.exposed() else "FLAT", "halted": halted,
            "decisions": decisions, "round_trips": trips, "bought_usdt": str(book.bought - quota_used),
            "open_usdt": str(book.usdt), "open_tmn": str(tmn), "fills": book.fills}


def _bar_end(at: datetime) -> datetime:
    start = at.replace(second=0, microsecond=0) - timedelta(minutes=at.minute % 5)
    return start + BAR
