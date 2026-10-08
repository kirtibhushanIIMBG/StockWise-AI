"""Natural-language inventory descriptions -> structured, validated preview records.

Claude only *extracts* values the user stated. It never fills in missing commercial values;
missing essentials are reported back so the user can supply them.
"""
from typing import Optional

from pydantic import BaseModel, Field

import config
from data_processing import make_sku

ESSENTIAL = ["product_name", "current_stock", "avg_daily_demand", "lead_time_days", "unit_cost"]
LABELS = {
    "product_name": "product name", "current_stock": "units in stock",
    "avg_daily_demand": "average daily sales", "lead_time_days": "supplier delivery time (days)",
    "unit_cost": "cost per unit (₹)", "safety_stock": "extra buffer units",
}


class ExtractedProduct(BaseModel):
    product_name: Optional[str] = Field(None, description="Product name exactly as the user called it")
    current_stock: Optional[float] = Field(None, description="Units on hand now. 'out of stock' = 0. Null if not stated or vague (e.g. 'very little').")
    avg_daily_demand: Optional[float] = Field(None, description="Average units sold per day. Convert per-week to per-day only if stated per week. Null if not stated.")
    lead_time_days: Optional[float] = Field(None, description="Supplier delivery time in days. Null if not stated.")
    unit_cost: Optional[float] = Field(None, description="Purchase cost per unit in rupees. Null if not stated.")
    safety_stock: Optional[float] = Field(None, description="Extra buffer units the user wants to keep. Null if not stated.")
    incoming_stock: Optional[float] = Field(None, description="Units already ordered and on the way. Null if not stated.")
    backorders: Optional[float] = Field(None, description="Unfilled customer orders. Null if not stated.")


class ExtractionResult(BaseModel):
    intent: str = Field(description="'inventory_data' if the text describes stock facts, 'question' if it only asks something")
    products: list[ExtractedProduct] = Field(default_factory=list)


SYSTEM = (
    "You extract inventory facts from a business user's text. Create one entry per distinct product. "
    "Only record numbers the user explicitly stated. NEVER guess, estimate or invent values — use null "
    "for anything not stated or stated vaguely. Words like 'five' are numbers (5). 'Out of stock' means 0 units."
)


def get_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=config.ANTHROPIC_MODEL, api_key=config.ANTHROPIC_API_KEY,
                         temperature=0, timeout=config.AGENT_TIMEOUT_SECONDS,
                         max_retries=config.AGENT_MAX_RETRIES, max_tokens=2000)


def extract(text: str, llm=None) -> ExtractionResult:
    llm = llm or get_llm()
    structured = llm.with_structured_output(ExtractionResult)
    return structured.invoke([("system", SYSTEM), ("human", text)])


def build_preview(result: ExtractionResult, existing_skus: set | None = None,
                  existing_names: dict | None = None) -> dict:
    """Turn extracted products into editable preview rows with missing fields flagged."""
    existing_names = existing_names or {}
    taken = set(existing_skus or set())
    rows, seen_names = [], set()
    for p in result.products:
        d = p.model_dump()
        name = (d.get("product_name") or "").strip()
        if name.lower() in seen_names:  # de-duplicate repeated mentions
            continue
        seen_names.add(name.lower())
        sku = existing_names.get(name.lower())
        is_update = sku is not None
        if not sku:
            sku = make_sku(name or "ITEM", taken)
        taken.add(sku)
        missing = [f for f in ESSENTIAL if d.get(f) is None or (f == "product_name" and not name)]
        rows.append({
            **d, "sku": sku, "is_update": is_update,
            "missing": missing, "missing_labels": [LABELS[f] for f in missing],
            "safety_stock_note": None if d.get("safety_stock") is not None else
            f"No buffer given — we can apply a default of {config.DEFAULT_BUFFER_DAYS} days of sales if you agree.",
        })
    return {"intent": result.intent, "rows": rows,
            "complete": bool(rows) and all(not r["missing"] for r in rows)}
