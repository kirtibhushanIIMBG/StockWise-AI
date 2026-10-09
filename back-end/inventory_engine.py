"""Deterministic inventory calculations. The AI never does arithmetic — it calls these functions.

Classification priority (first match wins):
  1. Out of Stock  – current stock is 0 and there is expected demand (or backorders)
  2. Low Demand    – avg daily demand <= LOW_DEMAND_THRESHOLD
  3. Critical      – stock runs out before a normal delivery (coverage < lead time)
                     or current stock is below safety stock
  4. Order Soon    – inventory position <= reorder point
  5. Excess Stock  – coverage > EXCESS_COVERAGE_DAYS
  6. Healthy       – everything else
The "needs_reorder" flag is computed independently of the label.
"""
import math
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

import config


def money(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def coverage_days(stock: float, demand: float):
    """Days current stock will last. None means 'no demand' (infinite coverage)."""
    if demand <= 0:
        return None
    return round(stock / demand, 2)


def safety_stock(demand: float, lead_time: float, supplied=None, demand_std=None):
    """Return (safety_stock, method)."""
    if supplied is not None:
        return float(supplied), "supplied"
    if demand_std:
        return float(math.ceil(config.SERVICE_Z * demand_std * math.sqrt(lead_time))), "statistical"
    return float(math.ceil(config.DEFAULT_BUFFER_DAYS * demand)), "default_buffer"


def analyze_item(item: dict, lead_time_override: float | None = None) -> dict:
    d = float(item["avg_daily_demand"])
    lt = float(lead_time_override if lead_time_override is not None else item["lead_time_days"])
    stock = float(item["current_stock"])
    inc = float(item.get("incoming_stock") or 0)
    bo = float(item.get("backorders") or 0)
    cost = float(item["unit_cost"])

    ss, ss_method = safety_stock(d, lt, item.get("safety_stock"), item.get("demand_std"))
    review = config.REVIEW_PERIOD_DAYS
    pos = stock + inc - bo                       # inventory position
    cov = coverage_days(stock, d)
    rop = math.ceil(d * lt + ss)                 # reorder point
    tgt = math.ceil(d * (lt + review) + ss)      # target stock
    needs = pos <= rop and (d > 0 or bo > 0)
    qty = int(max(0, math.ceil(tgt - pos))) if needs else 0

    if stock <= 0 and (d > 0 or bo > 0):
        status = "Out of Stock"
    elif d <= config.LOW_DEMAND_THRESHOLD:
        status = "Low Demand"
    elif (cov is not None and cov < lt) or stock < ss:
        status = "Critical"
    elif pos <= rop:
        status = "Order Soon"
    elif cov is not None and cov > config.EXCESS_COVERAGE_DAYS:
        status = "Excess Stock"
    else:
        status = "Healthy"

    shortage_days = round(max(0.0, lt - cov), 2) if cov is not None else 0.0
    excess_units = 0
    if status == "Excess Stock":
        excess_units = int(max(0, stock - math.ceil(d * config.EXCESS_COVERAGE_DAYS)))

    return {
        "sku": item["sku"],
        "product_name": item["product_name"],
        "category": item.get("category", "General"),
        "supplier": item.get("supplier", "Unknown"),
        "current_stock": stock,
        "incoming_stock": inc,
        "backorders": bo,
        "avg_daily_demand": d,
        "lead_time_days": lt,
        "unit_cost": money(cost),
        "inventory_position": pos,
        "coverage_days": cov,
        "safety_stock": ss,
        "safety_stock_method": ss_method,
        "reorder_point": rop,
        "target_stock": tgt,
        "review_period_days": review,
        "needs_reorder": needs,
        "suggested_qty": qty,
        "estimated_cost": money(qty * cost),
        "status": status,
        "shortage_days": shortage_days,
        "stock_value": money(stock * cost),
        "excess_units": excess_units,
        "excess_value": money(excess_units * cost),
        "action": recommended_action(status, qty, cov, lt, shortage_days),
    }


def recommended_action(status, qty, cov, lt, shortage_days) -> str:
    if status == "Out of Stock":
        return f"Order {qty} units now — this product is out of stock."
    if status == "Critical":
        if qty == 0:
            return "Stock on hand is low, but stock already on the way should cover it. Watch closely."
        if shortage_days > 0:
            return (f"Order {qty} units now. Stock may run out about {shortage_days:g} days "
                    f"before the next normal delivery.")
        return f"Order {qty} units now — stock is below your safety buffer."
    if status == "Order Soon":
        return f"Time to order more: about {qty} units."
    if status == "Excess Stock":
        return "Pause new orders — you hold much more stock than needed."
    if status == "Low Demand":
        return "Few or no sales — avoid reordering until demand returns."
    return "No order needed right now."


PRIORITY = {"Out of Stock": 0, "Critical": 1}


def priority_key(r: dict):
    """Out of stock > critical > other reorder-required > lower coverage > SKU."""
    tier = PRIORITY.get(r["status"], 2 if r["needs_reorder"] else 3)
    cov = r["coverage_days"] if r["coverage_days"] is not None else float("inf")
    return (tier, cov, r["sku"])


def analyze_all(items: list[dict], lead_time_overrides: dict | None = None) -> list[dict]:
    lead_time_overrides = lead_time_overrides or {}
    rows = [analyze_item(i, lead_time_overrides.get(i["sku"])) for i in items]
    return sorted(rows, key=priority_key)


def summarize(rows: list[dict]) -> dict:
    counts = dict(Counter(r["status"] for r in rows))
    reorder = [r for r in rows if r["needs_reorder"]]
    at_risk = [r for r in rows if r["status"] in ("Out of Stock", "Critical")]
    cat_cost = {}
    for r in reorder:
        cat_cost[r["category"]] = money(cat_cost.get(r["category"], 0) + r["estimated_cost"])
    return {
        "total_products": len(rows),
        "need_reorder": len(reorder),
        "at_risk": len(at_risk),
        "out_of_stock": counts.get("Out of Stock", 0),
        "excess": counts.get("Excess Stock", 0),
        "total_purchase_cost": money(sum(r["estimated_cost"] for r in reorder)),
        "inventory_value": money(sum(r["stock_value"] for r in rows)),
        "excess_value": money(sum(r["excess_value"] for r in rows)),
        "status_counts": counts,
        "cost_by_category": cat_cost,
    }
