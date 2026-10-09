"""Deterministic inventory calculations. The AI never does arithmetic — it calls these functions.

"Available" stock is on hand minus units already owed to customers (backorders); coverage uses it.

Classification priority (first match wins):
  1. Out of Stock  – nothing available to sell, and there is demand (or customers are still owed units)
  2. Low Demand    – avg daily demand <= LOW_DEMAND_THRESHOLD
  3. Critical      – available stock runs out before a normal delivery (coverage < lead time)
                     or is below safety stock
  4. Order Soon    – inventory position <= reorder point
  5. Excess Stock  – coverage > EXCESS_COVERAGE_DAYS
  6. Healthy       – everything else
"needs_reorder" is position <= reorder point with at least one unit to buy; Low Demand products are never reordered.
A minimum stock level from the user's file raises the reorder point; a maximum stock level caps the
target (never below the reorder point).
"""
import math
from collections import Counter
from decimal import ROUND_HALF_UP, Context, Decimal

from . import config

MONEY = Context(prec=60)  # the default 28 digits can't hold very large totals to the paisa


def money(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP, context=MONEY))


def ceil(x: float) -> int:
    """Round up whole units, ignoring float noise (0.28 × 25 = 7.000000000000001 must give 7, not 8)."""
    return math.ceil(round(x, 9))


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
        return float(ceil(config.SERVICE_Z * demand_std * math.sqrt(lead_time))), "statistical"
    return float(ceil(config.DEFAULT_BUFFER_DAYS * demand)), "default_buffer"


def analyze_item(item: dict, lead_time_override: float | None = None) -> dict:
    d = float(item["avg_daily_demand"])
    lt = float(lead_time_override if lead_time_override is not None else item["lead_time_days"])
    stock = float(item["current_stock"])
    inc = float(item.get("incoming_stock") or 0)
    bo = float(item.get("backorders") or 0)
    cost = float(item["unit_cost"])
    min_stock, max_stock = item.get("min_stock"), item.get("max_stock")

    ss, ss_method = safety_stock(d, lt, item.get("safety_stock"), item.get("demand_std"))
    review = config.REVIEW_PERIOD_DAYS
    pos = stock + inc - bo                       # inventory position
    avail = stock - bo                           # on hand, after units already owed to customers
    cov = coverage_days(max(0.0, avail), d)
    calc_rop = ceil(d * lt + ss)                 # reorder point
    calc_tgt = ceil(d * (lt + review) + ss)      # target stock
    rop = max(calc_rop, ceil(min_stock)) if min_stock is not None else calc_rop  # never later than the user's minimum
    tgt = max(calc_tgt, rop)
    if max_stock is not None:                    # no more than the user can hold, but at least the reorder point
        tgt = max(min(tgt, math.floor(max_stock)), rop)

    if avail <= 0 and (d > 0 or bo > stock):     # nothing left to sell, and buyers waiting
        status = "Out of Stock"
    elif d <= config.LOW_DEMAND_THRESHOLD:
        status = "Low Demand"
    elif (cov is not None and cov < lt) or avail < ss:
        status = "Critical"
    elif pos <= rop:
        status = "Order Soon"
    elif cov is not None and cov > config.EXCESS_COVERAGE_DAYS:
        status = "Excess Stock"
    else:
        status = "Healthy"
    # Low-demand products are never reordered: sales are too slow to justify buying more.
    qty = max(0, ceil(tgt - pos)) if status != "Low Demand" and pos <= rop and (d > 0 or bo > 0) else 0
    needs = qty > 0  # at a reorder level that is also the refill level there is nothing to buy
    # Days until the reorder point is reached at today's sales rate (None when no order is coming up).
    days_to_order = math.floor((pos - rop) / d) if not needs and status != "Low Demand" and d > 0 else None

    shortage_days = round(max(0.0, lt - cov), 2) if cov is not None else 0.0
    excess_units = 0
    if status == "Excess Stock":
        excess_units = int(max(0, avail - ceil(d * config.EXCESS_COVERAGE_DAYS)))
    price = cost if item.get("selling_price") is None else item["selling_price"]  # sales lost per day if it runs out

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
        "min_stock": min_stock,
        "max_stock": max_stock,
        "calc_reorder_point": calc_rop,
        "calc_target_stock": calc_tgt,
        "reorder_point": rop,
        "target_stock": tgt,
        "review_period_days": review,
        "needs_reorder": needs,
        "suggested_qty": qty,
        "estimated_cost": money(qty * cost),
        "days_until_reorder": days_to_order,
        "status": status,
        "shortage_days": shortage_days,
        "daily_sales_value": money(d * float(price)),
        "stock_value": money(stock * cost),
        "excess_units": excess_units,
        "excess_value": money(excess_units * cost),
        "action": recommended_action(status, qty, cov, lt, shortage_days, days_to_order),
    }


def _next_order(days) -> str:
    if days is None:
        return ""
    return " Next order due " + ("today." if days < 1 else "in about 1 day." if days == 1 else f"in about {days} days.")


def recommended_action(status, qty, cov, lt, shortage_days, days_to_order=None) -> str:
    if status in ("Out of Stock", "Critical") and qty == 0:
        return "Stock on hand is low, but stock already on the way should cover it. Watch closely."
    if status == "Out of Stock":
        return f"Order {qty} units now — this product is out of stock."
    if status == "Critical":
        if shortage_days > 0:
            return (f"Order {qty} units now. Stock may run out about {shortage_days:g} days "
                    f"before the next normal delivery.")
        return f"Order {qty} units now — stock is below your safety buffer."
    if status == "Order Soon":  # qty 0: stock sits exactly at a reorder level that is also the refill level
        return f"Time to order more: about {qty} units." if qty else "Stock is at your reorder level. Watch closely."
    if status == "Excess Stock":
        return "Pause new orders — you hold much more stock than needed." + _next_order(days_to_order)
    if status == "Low Demand":
        return "Few or no sales — avoid reordering until demand returns."
    return "No order needed right now." + _next_order(days_to_order)


PRIORITY = {"Out of Stock": 0, "Critical": 1}


def priority_key(r: dict):
    """Out of stock > critical > other reorder-required > lower coverage > more sales lost per day > SKU."""
    tier = PRIORITY.get(r["status"], 2 if r["needs_reorder"] else 3)
    cov = r["coverage_days"] if r["coverage_days"] is not None else float("inf")
    return (tier, cov, -r["daily_sales_value"], r["sku"])


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
