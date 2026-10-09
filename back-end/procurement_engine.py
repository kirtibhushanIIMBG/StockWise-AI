"""Budget-constrained purchase planning (transparent greedy, not a global optimum)."""
import math
from decimal import Decimal

from inventory_engine import analyze_all, money


def purchase_plan(items: list[dict], budget: float) -> dict:
    rows = [r for r in analyze_all(items) if r["suggested_qty"] > 0]  # already in priority order
    remaining = Decimal(str(budget))
    lines = []
    for priority, r in enumerate(rows, start=1):
        cost = Decimal(str(r["unit_cost"]))
        need = r["suggested_qty"]
        buy = need if cost == 0 else min(need, math.floor(remaining / cost))
        spend = cost * buy
        remaining -= spend
        lines.append({
            "priority": priority,
            "sku": r["sku"],
            "product_name": r["product_name"],
            "category": r["category"],
            "status": r["status"],
            "recommended_qty": need,
            "buy_qty": int(buy),
            "unit_cost": r["unit_cost"],
            "cost": money(spend),
            "unfunded_qty": int(need - buy),
            "funding": "Full" if buy == need else ("Partial" if buy > 0 else "Not funded"),
        })
    spent = sum(Decimal(str(l["cost"])) for l in lines)
    assert spent <= Decimal(str(budget)), "budget exceeded"  # hard guarantee
    return {
        "budget": money(budget),
        "total_spend": money(spent),
        "remaining_budget": money(remaining),
        "total_required_cost": money(sum(r["estimated_cost"] for r in rows)),
        "fully_funded": sum(1 for l in lines if l["funding"] == "Full"),
        "partially_funded": sum(1 for l in lines if l["funding"] == "Partial"),
        "not_funded": sum(1 for l in lines if l["funding"] == "Not funded"),
        "units_bought": sum(l["buy_qty"] for l in lines),
        "units_unfunded": sum(l["unfunded_qty"] for l in lines),
        "lines": lines,
        "method": "Greedy by priority: stockouts, then critical, then other reorders, "
                  "then lowest days of cover, then SKU. Full quantities first, partial if money runs short.",
    }


def compare_budgets(items: list[dict], budget_a: float, budget_b: float) -> dict:
    a, b = purchase_plan(items, budget_a), purchase_plan(items, budget_b)
    covered = lambda p: {l["sku"] for l in p["lines"] if l["buy_qty"] > 0}
    keys = ("budget", "total_spend", "remaining_budget", "units_bought", "units_unfunded",
            "fully_funded", "partially_funded")
    return {
        "kind": "budget",
        "plan_a": {k: a[k] for k in keys},
        "plan_b": {k: b[k] for k in keys},
        "additional_units": b["units_bought"] - a["units_bought"],
        "additional_spend": money(b["total_spend"] - a["total_spend"]),
        "newly_covered_products": sorted(covered(b) - covered(a)),
        "remaining_unmet_units_b": b["units_unfunded"],
    }


def compare_lead_time(items: list[dict], sku: str, new_lead_time: float) -> dict:
    """What-if on a copy; the saved baseline is never modified."""
    item = next((i for i in items if i["sku"].lower() == sku.lower()
                 or i["product_name"].lower() == sku.lower()), None)
    if item is None:
        return {"error": f"Product '{sku}' not found in your inventory."}
    base = analyze_all([item])[0]
    new = analyze_all([item], {item["sku"]: new_lead_time})[0]
    keys = ("lead_time_days", "reorder_point", "target_stock", "status", "needs_reorder",
            "suggested_qty", "estimated_cost", "shortage_days")
    return {
        "kind": "lead_time",
        "sku": item["sku"],
        "product_name": item["product_name"],
        "before": {k: base[k] for k in keys},
        "after": {k: new[k] for k in keys},
        "extra_units": new["suggested_qty"] - base["suggested_qty"],
        "extra_cost": money(new["estimated_cost"] - base["estimated_cost"]),
    }
