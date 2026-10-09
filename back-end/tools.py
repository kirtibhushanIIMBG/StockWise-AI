"""LangChain tools. Each tool is bound to ONE session's inventory via closure, so the agent
cannot read another session's records. Tools call deterministic Python only and return
compact results (not the whole dataset)."""
from typing import Optional

from langchain_core.tools import tool

from explanation_engine import explain_product
from inventory_engine import analyze_all, money, summarize
from procurement_engine import compare_budgets, compare_lead_time, purchase_plan

SLIM = ("sku", "product_name", "status", "current_stock", "avg_daily_demand", "coverage_days",
        "lead_time_days", "needs_reorder", "suggested_qty", "estimated_cost")


TOP = 10  # products listed per group; counts and totals always cover every product


def _slim(r):
    return {k: r[k] for k in SLIM}


def _group(rows, fmt=_slim):
    """Total count plus the first TOP rows (callers pass rows most-urgent first)."""
    return {"count": len(rows), "products": [fmt(r) for r in rows[:TOP]]}


def _find(items, query: str):
    q = query.strip().lower()
    for i in items:
        if i["sku"].lower() == q or i["product_name"].lower() == q:
            return i
    matches = [i for i in items if q in i["product_name"].lower() or i["product_name"].lower() in q]
    return matches[0] if len(matches) == 1 else None


def build_tools(get_items):
    """get_items: zero-arg callable returning this session's items."""

    @tool
    def get_inventory_summary() -> dict:
        """Overall inventory health: counts by status, how many products need reordering,
        stock value, total recommended purchase cost, and the 8 most urgent products."""
        rows = analyze_all(get_items())
        return {**summarize(rows), "most_urgent": [_slim(r) for r in rows[:8]]}

    @tool
    def analyze_product(product: str) -> dict:
        """Detailed analysis and plain-language explanation for one product (name or SKU)."""
        items = get_items()
        item = _find(items, product)
        if not item:
            return {"error": f"'{product}' was not found in the inventory.",
                    "available_products": [i["product_name"] for i in items][:40]}
        r = analyze_all([item])[0]
        return {"analysis": r, "explanation": explain_product(r)}

    @tool
    def identify_inventory_risks(within_days: Optional[float] = None) -> dict:
        """Products at risk: out of stock, critical, order soon, excess stock and low demand.
        If within_days is given, also list products whose stock may run out within that many days.
        Each group gives the total count and its 10 most urgent products."""
        rows = analyze_all(get_items())
        out = {s: _group([r for r in rows if r["status"] == s])
               for s in ("Out of Stock", "Critical", "Order Soon", "Low Demand")}
        excess = sorted((r for r in rows if r["status"] == "Excess Stock"), key=lambda r: -r["excess_value"])
        out["Excess Stock"] = {**_group(excess, lambda r: {**_slim(r), "excess_units": r["excess_units"],
                                                           "excess_value": r["excess_value"]}),
                               "total_excess_value": money(sum(r["excess_value"] for r in excess))}
        if within_days is not None:
            out[f"run_out_within_{within_days:g}_days"] = _group(
                [r for r in rows if r["coverage_days"] is not None and r["coverage_days"] <= within_days])
        return out

    @tool
    def calculate_replenishment(products: Optional[list[str]] = None) -> dict:
        """Reorder quantities and costs. Pass product names/SKUs, or omit for all products needing reorder
        (total count and cost of all, details of the 10 most urgent)."""
        items = get_items()
        if products:
            found = {p: _find(items, p) for p in products}
            rows = analyze_all([f for f in found.values() if f])
            missing = [p for p, f in found.items() if not f]
        else:
            rows, missing = [r for r in analyze_all(items) if r["needs_reorder"]], []
        return {"items": _group(rows, lambda r: {**_slim(r), "reorder_point": r["reorder_point"],
                                                  "target_stock": r["target_stock"]}),
                "total_cost": money(sum(r["estimated_cost"] for r in rows)), "not_found": missing}

    @tool
    def create_purchase_plan(budget_inr: float) -> dict:
        """Allocate a purchasing budget (in rupees) across products by priority without exceeding it."""
        if budget_inr < 0:
            return {"error": "Budget must be zero or more."}
        p = purchase_plan(get_items(), budget_inr)
        p["lines"] = p["lines"][:15]
        return p

    @tool
    def compare_scenarios(kind: str, budget_a: Optional[float] = None, budget_b: Optional[float] = None,
                          product: Optional[str] = None, new_lead_time_days: Optional[float] = None) -> dict:
        """What-if comparison. kind='budget' needs budget_a and budget_b (rupees).
        kind='lead_time' needs product and new_lead_time_days. Never changes saved data."""
        items = get_items()
        if kind == "budget" and budget_a is not None and budget_b is not None and min(budget_a, budget_b) >= 0:
            return compare_budgets(items, budget_a, budget_b)
        if kind == "lead_time" and product and new_lead_time_days is not None and new_lead_time_days >= 0:
            item = _find(items, product)
            return compare_lead_time(items, item["sku"] if item else product, new_lead_time_days)
        return {"error": "Unsupported scenario or missing values."}

    return [get_inventory_summary, analyze_product, identify_inventory_risks,
            calculate_replenishment, create_purchase_plan, compare_scenarios]
