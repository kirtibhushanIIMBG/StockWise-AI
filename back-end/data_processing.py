"""CSV loading: turns almost any inventory or sales-history CSV into validated product records.

Reading: any delimiter (, ; tab |), UTF-8 / BOM / Windows encodings, title lines above the header,
ragged rows, and numbers written as "₹1,200", "1.200,50" (;-separated files), "2 weeks" or "N/A".
Columns: exact names first, then keyword rules ("Qty on Hand" → stock, "Weekly Sales" → daily sales ÷ 7,
"Lead Time (weeks)" → days × 7). Every renamed or converted column is reported back as a note.
Shapes: one row per product; one row per product per location (added up); or a dated sales history
(average daily sales and variability are calculated from it, and the latest stock is used).
If a required column still can't be found, NeedsInput asks the user to pick a column or enter one
value for every product — values are never guessed. Structured data only: no embeddings.
"""
import csv
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError

from schemas import InventoryItem

# Required fields and how we describe them to the user (also used by the "Describe your stock" preview).
REQUIRED = {
    "product_name": "product name", "current_stock": "units in stock",
    "avg_daily_demand": "average daily sales", "lead_time_days": "supplier delivery time (days)",
    "unit_cost": "cost per unit (₹)",
}
OPTIONAL = {
    "sku": "product code", "category": "category", "supplier": "supplier", "selling_price": "selling price",
    "safety_stock": "safety buffer", "demand_std": "sales variability", "incoming_stock": "stock on the way",
    "backorders": "unfilled orders",
}
NUMERIC = {"current_stock", "avg_daily_demand", "lead_time_days", "unit_cost", "selling_price", "safety_stock",
           "demand_std", "incoming_stock", "backorders"}
SUMMED = {"current_stock", "incoming_stock", "backorders", "safety_stock"}  # added up across locations
EXACT = {**{f: f for f in (*REQUIRED, *OPTIONAL)},
         "product": "product_name", "name": "product_name", "item": "product_name",
         "stock": "current_stock", "on_hand": "current_stock", "quantity": "current_stock",
         "daily_demand": "avg_daily_demand", "demand": "avg_daily_demand", "daily_sales": "avg_daily_demand",
         "lead_time": "lead_time_days", "cost": "unit_cost", "purchase_cost": "unit_cost",
         "price": "selling_price", "incoming": "incoming_stock", "sku_id": "sku", "product_id": "sku"}
MAX_PRODUCTS = 5000
SHOWN_WARNINGS = 5


class DataError(ValueError):
    """Raised with a message that is safe to show to the user."""


class NeedsInput(DataError):
    """Required columns we could not find: the user picks a column or enters one value for all products."""

    def __init__(self, missing: list[str], columns: list[str]):
        self.missing, self.columns = missing, columns
        super().__init__("We couldn't find a column for: " + ", ".join(REQUIRED[f] for f in missing)
                         + ". Choose the matching column from your file, or enter one value to use for every product.")


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


# ---------------------------------------------------------------- reading
def _decode(content: bytes) -> str:
    if content[:4] == b"PK\x03\x04" or content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise DataError("This looks like an Excel file. In Excel choose File → Save As → CSV, then upload that file.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            pass
    return content.decode("latin-1")


def _rows(text: str) -> tuple[list[list[str]], str]:
    """All non-empty rows, split on whichever delimiter gives the most columns in the first lines."""
    sample = [line for line in text.splitlines()[:40] if line.strip()]

    def width(d):
        counts = sorted(len(r) for r in csv.reader(sample, delimiter=d))
        return counts[len(counts) // 2] if counts else 0
    delim = max(",;\t|", key=width)  # ties keep ","
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    return rows, delim


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header).lower()).strip("_")


# ---------------------------------------------------------------- column matching
def _per_day(col: str, t: set) -> float:
    """Scale that turns a sales column into units per day ("weekly_sales" → 1/7)."""
    if t & {"daily", "day", "avg", "average", "mean"}:
        return 1
    for words, days in (({"weekly", "week", "wk"}, 7), ({"monthly", "month"}, 30), ({"yearly", "annual", "year"}, 365)):
        if t & words:
            return 1 / days
    m = re.search(r"(\d+)_?d(?:ays?)?(?:_|$)", col)  # sales_last_30_days, units_sold_30d
    return 1 / int(m.group(1)) if m and int(m.group(1)) > 0 else 1


def _rule(col: str) -> tuple[str | None, float]:
    """Keyword match for a normalised header → (field, scale). Order matters: specific before general."""
    t = set(col.split("_"))

    def has(*words):
        return bool(t.intersection(words))
    if has("date", "datetime", "timestamp") or col == "day":
        return "date", 1
    if has("store", "warehouse", "location", "branch", "outlet", "shop", "site"):
        return "location", 1
    if has("std", "stdev", "stddev", "sd", "deviation", "variability"):
        return "demand_std", 1
    if has("safety", "buffer"):
        return "safety_stock", 1
    if has("incoming", "inbound", "transit", "pipeline") or "on_order" in col or "open_po" in col \
            or (has("ordered") and has("units", "qty", "quantity")):
        return "incoming_stock", 1
    if "backorder" in col or "back_order" in col or has("unfilled"):
        return "backorders", 1
    if has("lead", "leadtime") or (has("delivery", "replenishment") and has("time", "days", "weeks", "period")):
        return "lead_time_days", 7 if has("week", "weeks", "wk", "wks") else 1
    if has("cost", "cogs", "landed") or (has("purchase", "buy", "buying") and has("price", "rate")):
        costs_other_than_the_unit = has("holding", "reorder", "order", "ordering", "total", "shipping", "freight",
                                        "carrying", "stockout", "inventory")
        return (None if costs_other_than_the_unit else "unit_cost"), 1
    if has("price", "mrp", "msrp", "retail", "rrp", "selling"):
        return "selling_price", 1
    if has("demand", "sales", "sold", "usage", "consumption", "velocity", "offtake") \
            and not has("revenue", "value", "amount", "forecast", "rank", "growth", "pct", "percent", "trend"):
        return "avg_daily_demand", _per_day(col, t)
    if (has("stock", "inventory", "onhand", "soh", "available", "balance", "closing") or "on_hand" in col
            or col in ("qty", "quantity", "units")) and not has(
            "value", "days", "cover", "coverage", "turn", "turnover", "status", "min", "max", "reorder", "risk", "age",
            "ratio", "cost"):
        return "current_stock", 1
    if has("sku", "barcode", "upc", "ean", "asin") or col in ("id", "code") \
            or (has("product", "item", "article", "material", "part") and has("id", "code", "no", "number", "num")):
        return "sku", 1
    if has("name", "description", "title", "product", "item", "article"):
        return "product_name", 1
    if has("category", "department", "dept", "segment", "family", "class", "subcategory"):
        return "category", 1
    if has("supplier", "vendor", "manufacturer"):
        return "supplier", 1
    return None, 1


def _mostly_numeric(values: pd.Series) -> bool:
    s = values.dropna().astype(str)
    s = s[s != ""]
    return not s.empty and s.str.contains(r"\d").mean() >= 0.5


def _map_columns(headers: list[str], raw: pd.DataFrame, user_map: dict, demand_period: float):
    """field → (column index, scale, how it was matched). User choices win, then exact names, then keywords."""
    fields = {}
    for field, header in user_map.items():
        if field in REQUIRED and header in headers:
            scale = 1 / demand_period if field == "avg_daily_demand" else 1
            fields[field] = (headers.index(header), scale, "your choice")
    used = {i for i, _, _ in fields.values()}
    for exact in (True, False):
        for i, h in enumerate(headers):
            col = _norm(h)
            field, scale = (EXACT.get(col), 1) if exact else _rule(col)
            if i in used or not field or field in fields:
                continue
            if field in NUMERIC and not _mostly_numeric(raw[i]):
                continue  # e.g. "demand_variability" holding words like "Stable"
            fields[field] = (i, scale, "exact" if col == field else "matched")
            used.add(i)
    return fields


# ---------------------------------------------------------------- values
def _numbers(s: pd.Series, decimal_comma: bool) -> pd.Series:
    raw = s.astype("string").str.strip().str.lower()
    if decimal_comma:  # 1.200,50 → 1200.50; plain 1.5 is left alone
        has_comma = raw.str.contains(",", na=False)
        raw = raw.where(~has_comma, raw.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    else:  # ₹1,20,889 / 1,200 → thousands separators
        raw = raw.str.replace(",", "", regex=False)
    return pd.to_numeric(raw.str.extract(r"(-?\d+(?:\.\d+)?)", expand=False), errors="coerce")


def _dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce")
    if d.isna().mean() > 0.2:
        d = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return d


def _scale_note(field: str, scale: float) -> str:
    if field == "lead_time_days" and scale == 7:
        return " (weeks × 7)"
    if field == "avg_daily_demand" and scale != 1:
        days = round(1 / scale)
        return {7: " (weekly ÷ 7)", 30: " (monthly ÷ 30)", 365: " (yearly ÷ 365)"}.get(days, f" (÷ {days} days)")
    return ""


# ---------------------------------------------------------------- shapes
def _from_history(df: pd.DataFrame, key: str, notes: list[str]) -> pd.DataFrame:
    """Dated rows (per product, maybe per location) → one row per product."""
    df = df.dropna(subset=["date"]).sort_values("date")
    first, last = df["date"].min(), df["date"].max()
    days = (last - first).days + 1
    by_loc = [key, "location"] if "location" in df else [key]
    latest = df.groupby(by_loc).last()  # each location's most recent values
    out = df.groupby(key).last()        # most recent text, cost, lead time…
    for f in SUMMED & set(df.columns):
        out[f] = latest.groupby(level=key)[f].sum(min_count=1)
    if "avg_daily_demand" in df:
        daily = df.groupby([key, "date"])["avg_daily_demand"].sum().unstack(fill_value=0)
        daily = daily.reindex(columns=pd.date_range(first, last), fill_value=0)  # no row = no sales that day
        out["avg_daily_demand"] = daily.mean(axis=1).round(2)
        step = pd.Series(df["date"].unique()).sort_values().diff().median()
        if "demand_std" not in df and days > 1 and step <= pd.Timedelta(days=1):
            out["demand_std"] = daily.std(axis=1).round(2)
    stores = df["location"].nunique() if "location" in df else 1
    notes.insert(0, f"Your file is a sales history: {len(df):,} rows over {days} days "
                    f"({first:%d %b %Y} – {last:%d %b %Y}) for {len(out):,} products"
                    + (f" in {stores} locations" if stores > 1 else "") + ". We used total sales ÷ "
                    f"{days} days as average daily sales, day-to-day variation for the safety buffer, and each "
                    "product's latest stock" + (" (all locations added together)." if stores > 1 else "."))
    return out.reset_index()


def _from_locations(df: pd.DataFrame, key: str, notes: list[str]) -> pd.DataFrame:
    """One row per product per location → one row per product (quantities added up)."""
    g = df.groupby(key)
    out = g.last()
    for f in (SUMMED | {"avg_daily_demand"}) & set(df.columns):
        out[f] = g[f].sum(min_count=1)
    if "demand_std" in df:  # independent locations: variances add up
        out["demand_std"] = np.sqrt((df["demand_std"] ** 2).groupby(df[key]).sum(min_count=1)).round(2)
    notes.insert(0, f"Your file lists products per location ({df['location'].nunique()} locations). "
                    "We added stock and sales together for each product.")
    return out.reset_index()


# ---------------------------------------------------------------- main entry
def parse_csv(content: bytes, mapping: dict | None = None, defaults: dict | None = None,
              demand_period: float = 1) -> tuple[list[dict], list[str], list[str]]:
    """Returns (items, warnings, notes). Raises DataError / NeedsInput with user-facing messages."""
    mapping, defaults = mapping or {}, {k: v for k, v in (defaults or {}).items() if k in NUMERIC & set(REQUIRED)}
    rows, delim = _rows(_decode(content))
    if not rows:
        raise DataError("This file is empty.")
    # The header is the row (among the first 15) whose cells look most like column names we know.
    score = [sum(bool(EXACT.get(_norm(c)) or _rule(_norm(c))[0]) for c in r) for r in rows[:15]]
    h = score.index(max(score))
    headers = rows[h]
    keep = [i for i, name in enumerate(headers) if name or any(len(r) > i and r[i] for r in rows[h + 1:h + 50])]
    headers = [headers[i] or f"Column {i + 1}" for i in keep]
    raw = pd.DataFrame([[r[i] if i < len(r) and r[i] else None for i in keep] for r in rows[h + 1:]],
                       columns=range(len(keep)))
    if raw.empty:
        raise DataError("This file has column headings but no products.")

    fields = _map_columns(headers, raw, mapping, demand_period)
    missing = [f for f in REQUIRED if f not in fields and f not in defaults
               and not (f == "product_name" and "sku" in fields)]
    if missing:
        raise NeedsInput(missing, headers)

    notes, decimal_comma = [], delim == ";"
    df = pd.DataFrame(index=raw.index)
    for field, (i, scale, how) in fields.items():
        col = raw[i]
        if field == "date":
            df[field] = _dates(col)
        elif field in NUMERIC:
            num = _numbers(col, decimal_comma)
            if field == "lead_time_days":  # "2 weeks" written in the cells
                num = num.where(~col.astype("string").str.contains("week|wk", case=False, na=False), num * 7)
            df[field] = num * scale
        else:
            df[field] = col
        if how != "exact" and field in {*REQUIRED, *OPTIONAL}:
            label = REQUIRED.get(field) or OPTIONAL[field]
            notes.append(f"“{headers[i]}” → {label}{_scale_note(field, scale)}" + (" (your choice)" if how == "your choice" else ""))
    if "date" in df and df["date"].isna().mean() > 0.2:
        df = df.drop(columns="date")  # not really dates (e.g. weekday names)
    if "product_name" not in df:
        df["product_name"] = df["sku"]
        notes.append("No product name column, so product codes are used as names.")

    key = "sku" if "sku" in df else "product_name"
    repeated = df[key].dropna().duplicated().any()
    if "date" in df and repeated:
        df = _from_history(df, key, notes)
    elif "location" in df and repeated:
        df = _from_locations(df, key, notes)
    elif "avg_daily_demand" in fields:
        i, scale, how = fields["avg_daily_demand"]
        if how == "matched" and scale == 1 and not set(_norm(headers[i]).split("_")) & {"daily", "day", "avg", "average", "mean"}:
            notes.append(f"We assumed “{headers[i]}” is sales per day.")
    for field, value in defaults.items():
        if field not in fields:
            df[field] = value
            notes.append(f"{REQUIRED[field].capitalize()}: {value:g} for every product (entered by you).")

    if len(df) > MAX_PRODUCTS:
        raise DataError(f"This file has {len(df):,} products. StockWise handles up to {MAX_PRODUCTS:,} at a time — "
                        "please split the file.")
    records = df.drop(columns=[c for c in ("date", "location") if c in df]).astype(object)
    items, errors = validate_records(records.where(pd.notna(records), None).to_dict(orient="records"))
    if not items:
        raise DataError("None of the rows could be used. " + " ".join(errors[:3]))
    if len(errors) > SHOWN_WARNINGS:
        errors = errors[:SHOWN_WARNINGS] + [f"…and {len(errors) - SHOWN_WARNINGS:,} more rows were skipped."]
    return items, errors, notes


def load_csv_path(path) -> list[dict]:
    return parse_csv(Path(path).read_bytes())[0]
