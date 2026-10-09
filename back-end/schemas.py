"""Pydantic models for validated inventory records and API payloads."""
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InventoryItem(BaseModel):
    sku: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    category: str = "General"
    supplier: str = "Unknown"
    current_stock: float = Field(ge=0)
    avg_daily_demand: float = Field(ge=0)
    lead_time_days: float = Field(ge=0)
    unit_cost: float = Field(ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    safety_stock: Optional[float] = Field(default=None, ge=0)
    demand_std: Optional[float] = Field(default=None, ge=0)
    incoming_stock: float = Field(default=0, ge=0)
    backorders: float = Field(default=0, ge=0)

    @field_validator("sku", "product_name", "category", "supplier")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class ConfirmRequest(BaseModel):
    items: list[dict]
    apply_default_buffer: bool = True


class PurchasePlanRequest(BaseModel):
    budget: float = Field(ge=0)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ScenarioRequest(BaseModel):
    kind: str = Field(pattern="^(budget|lead_time)$")
    budget_a: Optional[float] = Field(default=None, ge=0)
    budget_b: Optional[float] = Field(default=None, ge=0)
    sku: Optional[str] = None
    new_lead_time: Optional[float] = Field(default=None, ge=0)
