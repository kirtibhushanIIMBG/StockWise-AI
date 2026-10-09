"""Pydantic models for validated inventory records and API payloads."""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_VALUE = 1e9     # per number; far above any real stock, sales, cost or lead time, and keeps every total finite
MAX_BUDGET = 1e15   # also the "buy everything" budget of the CSV export


class InventoryItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # strips before min_length, so "   " is rejected

    sku: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    category: str = "General"
    supplier: str = "Unknown"
    current_stock: float = Field(ge=0, le=MAX_VALUE)
    avg_daily_demand: float = Field(ge=0, le=MAX_VALUE)
    lead_time_days: float = Field(ge=0, le=MAX_VALUE)
    unit_cost: float = Field(ge=0, le=MAX_VALUE)
    selling_price: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)
    safety_stock: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)
    demand_std: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)
    incoming_stock: float = Field(default=0, ge=0, le=MAX_VALUE)
    backorders: float = Field(default=0, ge=0, le=MAX_VALUE)
    min_stock: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)  # the user's own reorder level
    max_stock: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)  # the most they want to hold


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class ConfirmRequest(BaseModel):
    items: list[dict]
    apply_default_buffer: bool = True


class PurchasePlanRequest(BaseModel):
    budget: float = Field(ge=0, le=MAX_BUDGET)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ScenarioRequest(BaseModel):
    kind: str = Field(pattern="^(budget|lead_time)$")
    budget_a: Optional[float] = Field(default=None, ge=0, le=MAX_BUDGET)
    budget_b: Optional[float] = Field(default=None, ge=0, le=MAX_BUDGET)
    sku: Optional[str] = None
    new_lead_time: Optional[float] = Field(default=None, ge=0, le=MAX_VALUE)
