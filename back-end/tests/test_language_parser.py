from langchain_core.runnables import RunnableLambda

from language_parser import ExtractedProduct, ExtractionResult, build_preview, extract


class FakeLLM:
    """Mocked model: returns a fixed structured extraction (no live API call)."""
    def __init__(self, result): self.result = result
    def with_structured_output(self, schema): return RunnableLambda(lambda _: self.result)


def test_scenario5_shampoo_extraction_flags_missing_buffer():
    fake = FakeLLM(ExtractionResult(products=[ExtractedProduct(
        product_name="Shampoo", current_stock=50, avg_daily_demand=8, lead_time_days=6, unit_cost=120)]))
    row = build_preview(extract("We have 50 units of Shampoo...", llm=fake))[0]
    assert row["current_stock"] == 50 and row["unit_cost"] == 120 and row["missing"] == []
    assert row["safety_stock"] is None  # buffer not stated: left empty, never invented
    assert row["sku"].startswith("SKU-SHAMPOO")


def test_multi_product_missing_cost_flagged_not_invented():
    fake = FakeLLM(ExtractionResult(products=[
        ExtractedProduct(product_name="Product A", current_stock=20, avg_daily_demand=10, lead_time_days=5),
        ExtractedProduct(product_name="Product C", current_stock=0, avg_daily_demand=4, lead_time_days=3),
        ExtractedProduct(product_name="Product C", current_stock=0, avg_daily_demand=4, lead_time_days=3)]))
    rows = build_preview(extract("...", llm=fake))
    assert len(rows) == 2  # duplicate removed
    assert all(r["missing"] == ["unit_cost"] and r["unit_cost"] is None for r in rows)


def test_existing_product_marked_as_update():
    fake = FakeLLM(ExtractionResult(products=[ExtractedProduct(product_name="Product A", current_stock=5)]))
    row = build_preview(extract("...", llm=fake), {"SKU-A"}, {"product a": "SKU-A"})[0]
    assert row["sku"] == "SKU-A" and row["is_update"]
