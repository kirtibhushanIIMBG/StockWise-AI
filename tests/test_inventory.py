from conftest import A, B, C
from src.explanation_engine import explain_product, n
from src.inventory_engine import analyze_item, coverage_days, analyze_all
from src.procurement_engine import purchase_plan


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


def test_float_noise_does_not_add_a_unit():
    r = analyze_item({**B, "avg_daily_demand": 0.28, "lead_time_days": 25, "safety_stock": 0})
    assert r["reorder_point"] == 7  # 0.28 × 25 is 7.000000000000001 in floating point


def test_explanation_numbers_never_scientific():
    assert (n(2500000.0), n(2.5), n(110.0), n(0.0)) == ("2500000", "2.5", "110", "0")


def test_low_demand_is_never_reordered_or_planned():
    slow = {**B, "sku": "S", "product_name": "Slow", "current_stock": 1, "avg_daily_demand": 0.4, "lead_time_days": 10}
    r = analyze_item(slow)  # 1 unit is below the order point, but it sells only 0.4 a day
    assert r["status"] == "Low Demand" and not r["needs_reorder"] and r["suggested_qty"] == 0
    assert "avoid reordering" in r["action"]
    e = explain_product(r)
    assert e["estimated_cost"] == "No purchase needed." and "low-demand" in e["how_calculated"][4]
    assert [l["sku"] for l in purchase_plan([slow, C], 1e6)["lines"]] == ["C"]


def test_backorders_reduce_available_stock():
    r = analyze_item({**A, "backorders": 15})  # (20 − 15 owed) ÷ 10 a day
    assert r["coverage_days"] == 0.5 and r["status"] == "Critical"
    slow = analyze_item({**B, "current_stock": 2, "backorders": 5, "avg_daily_demand": 0.3})
    assert slow["status"] == "Out of Stock" and slow["suggested_qty"] == 17  # customers owed more than is on hand
    settled = analyze_item({**B, "current_stock": 5, "backorders": 5, "avg_daily_demand": 0})
    assert settled["status"] == "Low Demand" and settled["suggested_qty"] == 0


def test_user_minimum_and_maximum_stock_levels():
    r = analyze_item({**B, "min_stock": 250})
    assert (r["reorder_point"], r["target_stock"], r["suggested_qty"]) == (250, 250, 50)
    assert "minimum stock level" in explain_product(r)["how_calculated"][1]
    r = analyze_item({**A, "max_stock": 100})
    assert (r["target_stock"], r["suggested_qty"]) == (100, 80)
    assert "maximum stock level" in explain_product(r)["how_calculated"][3]
    assert analyze_item({**A, "max_stock": 40})["target_stock"] == 60  # never below the order point


def test_next_order_due_for_healthy_stock():
    r = analyze_item(B)  # (200 − 30) ÷ 5 a day
    assert r["days_until_reorder"] == 34 and "about 34 days" in r["action"]


def test_equal_urgency_goes_to_bigger_daily_sales():
    cheap, pricey = dict(C, sku="A1", selling_price=50), dict(C, sku="Z9", selling_price=900)
    assert [r["sku"] for r in analyze_all([cheap, pricey])] == ["Z9", "A1"]


def test_never_advises_ordering_zero_units():
    covered = analyze_item({**C, "incoming_stock": 100})  # out of stock, but a delivery is on the way
    assert covered["status"] == "Out of Stock" and covered["suggested_qty"] == 0 and "0 units" not in covered["action"]
    at_level = analyze_item({**B, "current_stock": 250, "min_stock": 250, "avg_daily_demand": 1})
    assert at_level["status"] == "Order Soon" and at_level["suggested_qty"] == 0 and "0 units" not in at_level["action"]
    assert not at_level["needs_reorder"] and "reaches the refill level" in explain_product(at_level)["how_calculated"][4]


def test_rounding_due_today_and_free_items():
    e = explain_product(analyze_item({**A, "current_stock": 20.5}))
    assert "= 109.5, rounded up to 110 units" in e["how_calculated"][4]
    assert "due today" in analyze_item({**B, "current_stock": 32})["action"]  # 2 above the order point, 5 sold a day
    assert analyze_item({**C, "selling_price": 0})["daily_sales_value"] == 0  # a stated price of 0 is kept
