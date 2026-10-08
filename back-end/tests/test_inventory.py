from conftest import A, B, C
from inventory_engine import analyze_item, coverage_days, priority_key, analyze_all


def test_scenario1_running_out():
    r = analyze_item(A)
    assert r["coverage_days"] == 2 and r["reorder_point"] == 60 and r["target_stock"] == 130
    assert r["suggested_qty"] == 110 and r["estimated_cost"] == 11000
    assert r["status"] == "Critical" and r["needs_reorder"] and r["shortage_days"] == 3


def test_scenario2_healthy():
    r = analyze_item(B)
    assert r["coverage_days"] == 40 and r["reorder_point"] == 30
    assert not r["needs_reorder"] and r["suggested_qty"] == 0 and r["status"] == "Healthy"


def test_scenario3_stockout():
    r = analyze_item(C)
    assert r["coverage_days"] == 0 and r["reorder_point"] == 17 and r["target_stock"] == 45
    assert r["suggested_qty"] == 45 and r["estimated_cost"] == 9000 and r["status"] == "Out of Stock"


def test_zero_demand():
    assert coverage_days(10, 0) is None
    r = analyze_item({**B, "avg_daily_demand": 0, "safety_stock": 0})
    assert r["status"] == "Low Demand" and not r["needs_reorder"] and r["suggested_qty"] == 0


def test_default_buffer_disclosed():
    r = analyze_item({**A, "safety_stock": None})
    assert r["safety_stock"] == 20 and r["safety_stock_method"] == "default_buffer"


def test_statistical_safety_stock():
    r = analyze_item({**A, "safety_stock": None, "demand_std": 4})
    assert r["safety_stock_method"] == "statistical" and r["safety_stock"] == 15  # ceil(1.65*4*sqrt5)=15


def test_excess_stock():
    r = analyze_item({**B, "current_stock": 1000})
    assert r["status"] == "Excess Stock" and r["excess_units"] == 700


def test_incoming_and_backorders():
    r = analyze_item({**A, "incoming_stock": 50, "backorders": 5})
    assert r["inventory_position"] == 65 and not r["needs_reorder"]


def test_deterministic_priority():
    rows = analyze_all([B, A, C])
    assert [r["sku"] for r in rows] == ["C", "A", "B"]
