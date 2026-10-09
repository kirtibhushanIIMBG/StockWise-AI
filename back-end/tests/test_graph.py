"""LangGraph workflow tests. All model calls are mocked — no live API calls."""
import uuid

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

import graph
from conftest import A, B, C
from language_parser import ExtractedProduct, ExtractionResult


class ToolFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


class FakeExtractor:
    def __init__(self, result): self.result = result
    def with_structured_output(self, schema): return RunnableLambda(lambda _: self.result)


def tid():
    return graph.thread(uuid.uuid4().hex)


def plan_call():
    return AIMessage(content="", tool_calls=[{"name": "create_purchase_plan", "args": {"budget_inr": 12000}, "id": "t1"}])


# ---------------------------------------------------------------- number grounding
def test_grounding_accepts_tool_figures_indian_format_and_rounding():
    evidence = ['{"total_spend": 12000.0, "coverage_days": 3.75, "lines": [{"buy_qty": 45}]}']
    assert graph.ungrounded_numbers("Spend ₹12,000 on 45 units; stock lasts 3.8 days.", evidence) == []
    assert graph.ungrounded_numbers("Total ₹1,20,889", ['{"total": 120889.0}']) == []


def test_grounding_flags_invented_figures_but_allows_policy_and_small_numbers():
    evidence = ['{"suggested_qty": 110}']
    assert graph.ungrounded_numbers("Order 110 units, about 37% more, costing ₹13,500.", evidence) == ["37", "13500"]
    assert graph.ungrounded_numbers("Top 3 items, 7-day review period, 95% service level.", evidence) == []


# ---------------------------------------------------------------- ask graph
def test_ask_graph_runs_tool_and_verifies_answer():
    model = ToolFake(messages=iter([plan_call(), AIMessage(content="Buy Product C first. Total spend ₹12,000.")]))
    out = graph.ASK_GRAPH.invoke({"question": "plan for 12000"}, tid(), context=graph.Ctx(lambda: [A, B, C], model=model))
    assert out["tools_used"] == ["create_purchase_plan"]
    assert out["verified"] and out["unverified"] == [] and out["revisions"] == 0
    assert out["answer"].endswith("₹12,000.")


def test_ask_graph_rewrites_answer_with_invented_number():
    model = ToolFake(messages=iter([plan_call(),
                                    AIMessage(content="Spend ₹12,000 and you will save ₹4,321."),   # invented figure
                                    AIMessage(content="Spend ₹12,000 to cover Product C and part of A.")]))  # revise
    out = graph.ASK_GRAPH.invoke({"question": "plan for 12000"}, tid(), context=graph.Ctx(lambda: [A, B, C], model=model))
    assert out["revisions"] == 1 and out["verified"] and "4,321" not in out["answer"]


def test_ask_graph_flags_answer_that_stays_unverified():
    model = ToolFake(messages=iter([plan_call(), AIMessage(content="You save ₹4,321."), AIMessage(content="You save ₹4,321.")]))
    out = graph.ASK_GRAPH.invoke({"question": "plan"}, tid(), context=graph.Ctx(lambda: [A, B, C], model=model))
    assert not out["verified"] and out["unverified"] == ["4321"] and "could not be matched" in out["answer"]


def test_ask_graph_handles_multi_tool_questions_with_production_limits():
    calls = [AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": str(i)}]) for i, (n, a) in enumerate(
        [("get_inventory_summary", {}), ("analyze_product", {"product": "Product A"}), ("create_purchase_plan", {"budget_inr": 12000})])]
    model = ToolFake(messages=iter(calls + [AIMessage(content="Order 110 units of Product A for ₹11,000.")]))
    out = graph.ASK_GRAPH.invoke({"question": "q"}, tid(), context=graph.Ctx(lambda: [A, B, C], model=model))
    assert len(out["tools_used"]) == 3 and out["verified"]


def test_ask_graph_empty_inventory_needs_no_model():
    out = graph.ASK_GRAPH.invoke({"question": "What should I order?"}, tid(), context=graph.Ctx(lambda: [], model=None))
    assert out["answer"] == graph.NO_DATA and out["tools_used"] == []


def test_ask_graph_remembers_conversation_per_thread():
    cfg = tid()
    m1 = ToolFake(messages=iter([AIMessage(content="Product C is out of stock.")]))
    graph.ASK_GRAPH.invoke({"question": "What is out of stock?"}, cfg, context=graph.Ctx(lambda: [A, B, C], model=m1))
    m2 = ToolFake(messages=iter([AIMessage(content="Order it now.")]))
    out = graph.ASK_GRAPH.invoke({"question": "What should I do about it?"}, cfg, context=graph.Ctx(lambda: [A, B, C], model=m2))
    assert [m.type for m in out["messages"]] == ["human", "ai", "human", "ai"]
    fresh = graph.ASK_GRAPH.invoke({"question": "Hi"}, tid(), context=graph.Ctx(lambda: [], model=None))
    assert len(fresh["messages"]) == 2  # another thread (session) does not see this conversation


# ---------------------------------------------------------------- entry graph (human-in-the-loop)
SHAMPOO = ExtractionResult(products=[ExtractedProduct(
    product_name="Shampoo", current_stock=50, avg_daily_demand=8, lead_time_days=6, unit_cost=120)])


def entry_ctx(saved, result=SHAMPOO):
    return graph.Ctx(get_items=lambda: [A], save_items=saved.extend, model=FakeExtractor(result))


def test_entry_graph_pauses_for_review_and_saves_only_after_confirmation():
    saved, cfg = [], tid()
    ctx = entry_ctx(saved)
    out = graph.ENTRY_GRAPH.invoke({"text": "We have 50 units of Shampoo..."}, cfg, context=ctx)
    review = graph.pending_review(out)
    assert review and review["rows"][0]["product_name"] == "Shampoo" and saved == []  # paused, nothing saved
    rows = review["rows"]
    out = graph.ENTRY_GRAPH.invoke(Command(resume={"action": "save", "items": rows, "apply_default_buffer": True}), cfg, context=ctx)
    assert out["status"] == "saved" and len(saved) == 1 and saved[0]["current_stock"] == 50


def test_entry_graph_cancel_saves_nothing():
    saved, cfg = [], tid()
    ctx = entry_ctx(saved)
    graph.ENTRY_GRAPH.invoke({"text": "..."}, cfg, context=ctx)
    out = graph.ENTRY_GRAPH.invoke(Command(resume={"action": "cancel"}), cfg, context=ctx)
    assert out["status"] == "cancelled" and saved == []


def test_entry_graph_invalid_edit_returns_to_review():
    saved, cfg = [], tid()
    ctx = entry_ctx(saved)
    rows = graph.pending_review(graph.ENTRY_GRAPH.invoke({"text": "..."}, cfg, context=ctx))["rows"]
    bad = [{**rows[0], "unit_cost": None}]
    out = graph.ENTRY_GRAPH.invoke(Command(resume={"action": "save", "items": bad}), cfg, context=ctx)
    assert graph.pending_review(out)["errors"] and saved == []  # back at review, still unsaved
    out = graph.ENTRY_GRAPH.invoke(Command(resume={"action": "save", "items": rows}), cfg, context=ctx)
    assert out["status"] == "saved" and len(saved) == 1


def test_entry_graph_vague_text_asks_for_details():
    out = graph.ENTRY_GRAPH.invoke({"text": "We have very little stock of Product A."}, tid(),
                                   context=entry_ctx([], ExtractionResult(products=[])))
    assert graph.pending_review(out) is None and out["status"] == "empty"
    assert "units in stock" in out["message"] and "Product A" in out["message"]
