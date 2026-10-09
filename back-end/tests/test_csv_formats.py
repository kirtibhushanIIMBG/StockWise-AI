"""One deliberately different CSV per case: the loader must read each correctly or ask for what's missing."""
import io
import json

import pytest
from fastapi.testclient import TestClient

import main
from data_processing import DataError, NeedsInput, parse_csv


def by_name(items):
    return {i["product_name"]: i for i in items}


def test_semicolon_bom_decimal_comma_currency_and_bad_row():
    f = "﻿Product;Qty on Hand;Daily Sales;Lead Time;Cost Price\nWidget;1200;12,5;5;₹1.250,50\nGadget;N/A;3;4;200\n"
    items, warnings, notes = parse_csv(f.encode("utf-8"))
    w = by_name(items)["Widget"]
    assert (w["current_stock"], w["avg_daily_demand"], w["lead_time_days"], w["unit_cost"]) == (1200, 12.5, 5, 1250.5)
    assert len(items) == 1 and "Row 2" in warnings[0]  # Gadget has no stock figure: skipped, not guessed
    assert any("Qty on Hand" in n for n in notes)


def test_tab_separated_windows_encoding_title_lines_weekly_sales_lead_time_in_weeks():
    f = ("Stock report – Café Central\n(generated 2026-10-01)\n\n"
         "Item Code\tDescription\tSOH\tWeekly Sales\tLead Time (weeks)\tUnit Cost\tVendor\n"
         "C1\tCafé Latte Beans\t40\t70\t1\t300\tBeanCo\n")
    items, _, notes = parse_csv(f.encode("cp1252"))
    i = items[0]
    assert (i["sku"], i["product_name"], i["supplier"]) == ("C1", "Café Latte Beans", "BeanCo")
    assert (i["current_stock"], i["avg_daily_demand"], i["lead_time_days"], i["unit_cost"]) == (40, 10, 7, 300)
    assert any("weekly ÷ 7" in n for n in notes) and any("weeks × 7" in n for n in notes)


def test_daily_sales_history_across_stores():
    f = """date,product_id,product_name,units_sold,current_stock,lead_time_days,unit_cost,store_id
2024-01-01,P1,Water,10,100,3,5,S1
2024-01-01,P1,Water,6,50,3,5,S2
2024-01-02,P1,Water,8,92,3,5,S1
2024-01-02,P1,Water,4,46,3,5,S2
2024-01-03,P1,Water,12,80,3,5,S1
2024-01-03,P1,Water,5,41,3,5,S2
2024-01-01,P2,Juice,3,30,4,8,S1
2024-01-03,P2,Juice,6,24,4,8,S1
"""
    items, _, notes = parse_csv(f.encode())
    water, juice = by_name(items)["Water"], by_name(items)["Juice"]
    assert water["avg_daily_demand"] == 15 and water["demand_std"] == 2.65  # daily totals 16, 12, 17
    assert water["current_stock"] == 121                                    # latest S1 80 + S2 41
    assert juice["avg_daily_demand"] == 3 and juice["current_stock"] == 24   # no row on 2 Jan = 0 sold
    assert "sales history" in notes[0] and "2 locations" in notes[0]


def test_snapshot_per_warehouse_is_added_up():
    f = "sku,product_name,warehouse,on_hand,daily_demand,lead_time_days,unit_cost\nS1,Rice,WH-A,100,5,7,40\nS1,Rice,WH-B,50,3,7,40\n"
    items, _, notes = parse_csv(f.encode())
    assert len(items) == 1 and items[0]["current_stock"] == 150 and items[0]["avg_daily_demand"] == 8
    assert "2 locations" in notes[0]


def test_analytics_export_with_text_columns_and_extra_metrics():
    # Shape of the reference repo's processed file: words in "demand_variability" must not be read as numbers.
    f = ("product_id,product_name,unit_price,unit_cost,lead_time_days,reorder_cost,holding_cost_per_unit,current_stock,"
         "avg_daily_demand,std_daily_demand,demand_variability,forecast_daily_demand,safety_stock_units,reorder_point_units\n"
         "P001,Sparkling Water,1.5,0.6,3,50,0.05,1955,618.33,153.03,Stable,809.7,266,2121\n")
    i = parse_csv(f.encode())[0][0]
    assert (i["unit_cost"], i["selling_price"], i["avg_daily_demand"]) == (0.6, 1.5, 618.33)  # not reorder/holding cost
    assert (i["demand_std"], i["safety_stock"]) == (153.03, 266)


def test_messy_numbers_in_cells():
    f = "name,stock,daily sales,lead time,cost\nOil,\"1,200 units\",₹ 85 per day,2 weeks,Rs. 140\n"
    i = parse_csv(f.encode())[0][0]
    assert (i["current_stock"], i["avg_daily_demand"], i["lead_time_days"], i["unit_cost"]) == (1200, 85, 14, 140)


def test_sku_only_file_uses_codes_as_names():
    items, _, notes = parse_csv(b"sku,stock,demand,lead_time,cost\nX-1,5,1,2,10\n")
    assert items[0]["product_name"] == "X-1" and any("codes are used as names" in n for n in notes)


def test_excel_file_gets_a_clear_message():
    with pytest.raises(DataError, match="Excel"):
        parse_csv(b"PK\x03\x04 rest of a zip")


def test_missing_column_asks_and_never_guesses():
    f = b"Product,Stock,Sales per day,Replenishment Window,Cost\nTea,10,2,9,50\n"
    with pytest.raises(NeedsInput) as e:
        parse_csv(f)
    assert e.value.missing == ["lead_time_days"] and "Replenishment Window" in e.value.columns
    by_column = parse_csv(f, mapping={"lead_time_days": "Replenishment Window"})
    assert by_column[0][0]["lead_time_days"] == 9 and any("your choice" in n for n in by_column[2])
    by_value = parse_csv(f, defaults={"lead_time_days": 6})
    assert by_value[0][0]["lead_time_days"] == 6 and any("entered by you" in n for n in by_value[2])


def test_retail_forecasting_style_file_through_the_api():
    # Popular public dataset shape: dated rows per store, no lead time and no purchase cost.
    f = (b"Date,Store ID,Product ID,Category,Region,Inventory Level,Units Sold,Units Ordered,Demand Forecast,Price,Discount\n"
         b"2022-01-01,S001,P0001,Groceries,North,231,127,55,135.47,33.5,20\n"
         b"2022-01-02,S001,P0001,Groceries,North,204,150,66,144.04,33.5,20\n")
    c = TestClient(main.app)
    first = c.post("/api/upload", files={"file": ("r.csv", io.BytesIO(f), "text/csv")})
    assert first.status_code == 422 and [m["field"] for m in first.json()["missing"]] == ["lead_time_days", "unit_cost"]
    ok = c.post("/api/upload", files={"file": ("r.csv", io.BytesIO(f), "text/csv")},
                data={"defaults": json.dumps({"lead_time_days": 7, "unit_cost": 20})}).json()
    p = ok["products"][0]
    assert ok["loaded"] == 1 and p["sku"] == "P0001" and p["current_stock"] == 204 and p["avg_daily_demand"] == 138.5
    assert any("sales history" in n for n in ok["notes"])
