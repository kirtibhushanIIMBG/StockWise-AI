"""CSV loading and validation. Structured tables are filtered with pandas — no embeddings."""
import io
import re
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from schemas import InventoryItem

# Required fields and how we describe them to the user (also used by the "Describe your stock" preview).
REQUIRED = {
    "product_name": "product name", "current_stock": "units in stock",
    "avg_daily_demand": "average daily sales", "lead_time_days": "supplier delivery time (days)",
    "unit_cost": "cost per unit (₹)",
}
ALIASES = {
    "product": "product_name", "name": "product_name", "item": "product_name",
    "stock": "current_stock", "on_hand": "current_stock", "quantity": "current_stock",
    "daily_demand": "avg_daily_demand", "demand": "avg_daily_demand", "daily_sales": "avg_daily_demand",
    "average_daily_demand": "avg_daily_demand", "average_daily_sales": "avg_daily_demand",
    "avg_daily_sales": "avg_daily_demand",
    "daily_demand_stddev": "demand_std", "demand_stddev": "demand_std", "demand_std_dev": "demand_std",
    "lead_time": "lead_time_days", "cost": "unit_cost", "purchase_cost": "unit_cost",
    "price": "selling_price", "unit_price": "selling_price", "sale_price": "selling_price",
    "incoming": "incoming_stock", "sku_id": "sku", "product_id": "sku",
}


class DataError(ValueError):
    """Raised with a message that is safe to show to the user."""


def make_sku(name: str, taken: set) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:12] or "ITEM"
    sku, n = f"SKU-{base}", 2
    while sku in taken:
        sku, n = f"SKU-{base}-{n}", n + 1
    return sku


def validate_records(records: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate rows; returns (clean_items, errors). Duplicate SKUs are rejected."""
    items, errors, seen = [], [], set()
    for idx, raw in enumerate(records, start=1):
        rec = {k: v for k, v in raw.items() if v not in (None, "")}
        if not rec.get("sku"):
            rec["sku"] = make_sku(str(rec.get("product_name", "ITEM")), seen)
        try:
            item = InventoryItem(**rec).model_dump()
        except ValidationError as e:
            fields = ", ".join(str(err["loc"][0]) for err in e.errors())
            errors.append(f"Row {idx}: missing or invalid value for {fields}.")
            continue
        if item["sku"] in seen:
            errors.append(f"Row {idx}: duplicate product code {item['sku']} was skipped.")
            continue
        seen.add(item["sku"])
        items.append(item)
    return items, errors


def parse_csv(content: bytes) -> tuple[list[dict], list[str]]:
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise DataError("We couldn't read this file. Please save it as a CSV or use our sample file.") from e
    df.columns = [re.sub(r"\W+", "_", str(c).strip().lower()).strip("_") for c in df.columns]
    df = df.rename(columns={c: ALIASES.get(c, c) for c in df.columns})
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise DataError("Your file is missing a column for: "
                        + ", ".join(f"{REQUIRED[c]} (name it “{c}”)" for c in missing)
                        + ". Download our sample file to see the expected columns.")
    if df.empty:
        raise DataError("This file has column headings but no products.")
    df = df.astype(object).where(pd.notna(df), None)
    items, errors = validate_records(df.to_dict(orient="records"))
    if not items:
        raise DataError("None of the rows could be used. " + " ".join(errors[:3]))
    return items, errors


def load_csv_path(path) -> list[dict]:
    return parse_csv(Path(path).read_bytes())[0]
