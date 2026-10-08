from conftest import A, B, C
from procurement_engine import compare_budgets, compare_lead_time, purchase_plan


def test_scenario4_limited_budget():
    p = purchase_plan([A, B, C], 12000)
    lines = {l["sku"]: l for l in p["lines"]}
    assert lines["C"]["buy_qty"] == 45 and lines["C"]["cost"] == 9000
    assert lines["A"]["buy_qty"] == 30 and lines["A"]["cost"] == 3000 and lines["A"]["unfunded_qty"] == 80
    assert "B" not in lines
    assert p["total_spend"] == 12000 and p["remaining_budget"] == 0


def test_budget_never_exceeded():
    for b in [0, 1, 199, 5555.5, 20000, 10**6]:
        p = purchase_plan([A, B, C], b)
        assert p["total_spend"] <= b
        assert all(l["buy_qty"] >= 0 and isinstance(l["buy_qty"], int) for l in p["lines"])


def test_budget_comparison():
    c = compare_budgets([A, B, C], 12000, 30000)
    assert c["additional_units"] == 80 and c["additional_spend"] == 8000 and c["remaining_unmet_units_b"] == 0


def test_lead_time_scenario_preserves_baseline():
    items = [dict(A)]
    c = compare_lead_time(items, "Product A", 8)
    assert c["before"]["reorder_point"] == 60 and c["after"]["reorder_point"] == 90
    assert c["after"]["suggested_qty"] == 140 and items[0]["lead_time_days"] == 5
