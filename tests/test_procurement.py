from conftest import A, B, C
from src.procurement_engine import compare_budgets, compare_lead_time, purchase_plan


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


def test_tool_output_stays_small_for_large_inventories():
    import json
    from src.tools import TOP, build_tools
    big = [dict(sku=f"S{i:04}", product_name=f"P{i}", current_stock=i % 7, avg_daily_demand=5, lead_time_days=6,
                unit_cost=10, safety_stock=5) for i in range(2000)]
    tools = {t.name: t for t in build_tools(lambda: big)}
    risks = tools["identify_inventory_risks"].invoke({"within_days": 5})
    assert risks["Critical"]["count"] > TOP and len(risks["Critical"]["products"]) == TOP  # count covers all
    assert len(json.dumps(risks)) < 20_000
    rep = tools["calculate_replenishment"].invoke({})
    assert rep["items"]["count"] == 2000 and len(rep["items"]["products"]) == TOP and rep["total_cost"] > 0


def test_same_product_by_name_and_sku_is_counted_once():
    from src.tools import build_tools
    rep = {t.name: t for t in build_tools(lambda: [A])}["calculate_replenishment"].invoke({"products": ["Product A", "A"]})
    assert rep["items"]["count"] == 1 and rep["total_cost"] == 11000
