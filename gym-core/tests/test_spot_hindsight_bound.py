from decimal import Decimal
from itertools import product

from scripts.spot_hindsight_bound import solve


def test_hindsight_bound_agrees_with_exhaustive_cash_and_inventory_paths():
    quotes = [(Decimal(bid), Decimal(ask), 1, 1) for bid, ask in [(8, 10), (11, 12), (15, 16), (6, 7)]]
    opening, fee = Decimal(20), Decimal("0.01")
    valid = []
    for moves in product((-1, 0, 1), repeat=len(quotes)):
        cash, inventory = opening, 0
        for delta, (bid, ask, _, _) in zip(moves, quotes):
            cash -= delta * (ask * (1 + fee) if delta > 0 else bid * (1 - fee))
            inventory += delta
            if not (cash >= 0 and 0 <= inventory <= 2):
                break
        else:
            if inventory == 0:
                valid.append(cash)
    result = solve(opening, fee, quotes, max_units=2)
    assert Decimal(result["terminal_flat_cash"]) == max(valid) == Decimal("24.75")
    assert result["inventory_deltas"] == (1, 0, -1, 0)
