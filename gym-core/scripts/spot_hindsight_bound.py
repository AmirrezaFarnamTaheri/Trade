"""Solve a small exact best-bid/ask spot fixture with known future receipts."""
import argparse
import json
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path


def solve(opening_cash, fee, quotes, *, max_units):
    """Use whole inventory units and charge fees in quote currency on each side."""
    if (not fee.is_finite() or not opening_cash.is_finite() or not 0 <= fee < 1 or opening_cash < 0
            or type(max_units) is not int or not 1 <= max_units <= 64 or not 1 <= len(quotes) <= 128):
        raise ValueError("invalid bounded spot fixture")
    rate = Fraction(fee)
    states = {0: (Fraction(opening_cash), ())}
    for bid, ask, bid_units, ask_units in quotes:
        if (not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask
                or type(bid_units) is not int or type(ask_units) is not int
                or not 0 <= bid_units <= 64 or not 0 <= ask_units <= 64):
            raise ValueError("invalid quote or displayed capacity")
        buy, sell = Fraction(ask) * (1 + rate), Fraction(bid) * (1 - rate)
        following = {}
        for units, (cash, path) in states.items():
            for delta in range(-min(units, bid_units), min(max_units - units, ask_units) + 1):
                price = buy if delta > 0 else sell
                next_cash, inventory = cash - delta * price, units + delta
                if next_cash >= 0 and (inventory not in following or next_cash > following[inventory][0]):
                    following[inventory] = (next_cash, (*path, delta))
        states = following
    cash, path = states[0]
    with localcontext() as context:
        # Decimal inputs have denominators with only factors of two and five.
        context.prec = cash.numerator.bit_length() + cash.denominator.bit_length() + 1
        terminal = Decimal(cash.numerator) / Decimal(cash.denominator)
    return {"terminal_flat_cash": str(terminal), "cash_benchmark": str(opening_cash), "inventory_deltas": path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    quotes = [(Decimal(row["bid"]), Decimal(row["ask"]), row["bid_units"], row["ask_units"]) for row in fixture["quotes"]]
    print(json.dumps(solve(Decimal(fixture["opening_cash"]), Decimal(fixture["fee"]), quotes,
                           max_units=fixture["max_units"])))


if __name__ == "__main__":
    main()
