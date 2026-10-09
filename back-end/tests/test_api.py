import io

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import agent as agent_mod
import config
import main

GOOD = b"product_name,current_stock,avg_daily_demand,lead_time_days,unit_cost,safety_stock\nWidget,20,10,5,100,10\nGadget,0,4,3,200,5\n"


def client():
    return TestClient(main.app)


def test_health_and_sample_dashboard():
    c = client()
    assert c.get("/api/health").json()["ok"]
    d = c.get("/api/inventory").json()
    assert d["source"] == "sample" and d["summary"]["total_products"] >= 20
    assert c.get("/").status_code == 200


def test_upload_valid_and_session_isolation():
    c1, c2 = client(), client()
    c1.get("/api/inventory"); c2.get("/api/inventory")
    r = c1.post("/api/upload", files={"file": ("inv.csv", io.BytesIO(GOOD), "text/csv")}).json()
    assert r["ok"] and r["loaded"] == 2
    assert c1.get("/api/inventory").json()["summary"]["total_products"] == 2
    assert c2.get("/api/inventory").json()["summary"]["total_products"] >= 20


def test_upload_rejects_missing_columns_and_negatives():
    c = client()
    r = c.post("/api/upload", files={"file": ("x.csv", io.BytesIO(b"name,stock\nA,1\n"), "text/csv")})
    assert r.status_code == 400 and "couldn't read" in r.json()["message"]
    bad = b"product_name,current_stock,avg_daily_demand,lead_time_days,unit_cost\nA,-5,1,1,1\n"
    assert c.post("/api/upload", files={"file": ("x.csv", io.BytesIO(bad), "text/csv")}).status_code == 400


def test_duplicate_sku_skipped():
    csvb = b"sku,product_name,current_stock,avg_daily_demand,lead_time_days,unit_cost\nX,A,1,1,1,1\nX,B,1,1,1,1\n"
    r = client().post("/api/upload", files={"file": ("x.csv", io.BytesIO(csvb), "text/csv")}).json()
    assert r["loaded"] == 1 and "duplicate" in r["warnings"][0]


def test_purchase_plan_budget_and_export():
    c = client()
    p = c.post("/api/purchase-plan", json={"budget": 25000}).json()
    assert p["total_spend"] <= 25000
    e = c.get("/api/export?budget=25000")
    assert e.status_code == 200 and e.text.startswith("Priority,SKU")


def test_confirm_goes_through_review_step(monkeypatch):
    import language_parser
    from language_parser import ExtractedProduct, ExtractionResult
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(language_parser, "extract", lambda text, llm=None: ExtractionResult(
        products=[ExtractedProduct(product_name="Shampoo", current_stock=50,
                                                            avg_daily_demand=8, lead_time_days=6, unit_cost=120)]))
    c = client()
    assert c.post("/api/confirm-inventory", json={"items": []}).status_code == 409  # nothing pending
    rows = c.post("/api/parse-inventory", json={"text": "We have 50 units of Shampoo..."}).json()["rows"]
    assert c.get("/api/inventory").json()["summary"]["total_products"] == 24  # not saved yet
    bad = c.post("/api/confirm-inventory", json={"items": [{**rows[0], "unit_cost": None}]})
    assert bad.status_code == 400
    ok = c.post("/api/confirm-inventory", json={"items": rows}).json()
    assert ok["ok"] and ok["added"][0]["safety_stock"] == 16 and ok["added"][0]["safety_stock_method"] == "default_buffer"
    assert ok["summary"]["total_products"] == 25


def test_ask_endpoint_runs_graph(monkeypatch):
    import agent as agent_mod
    msgs = iter([AIMessage(content="", tool_calls=[{"name": "get_inventory_summary", "args": {}, "id": "1"}]),
                 AIMessage(content="**What we found** 7 products may run out soon.")])
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(agent_mod, "get_model", lambda: ToolFake(messages=msgs))
    r = client().post("/api/ask", json={"question": "What should I order?"}).json()
    assert r["ok"] and r["tools_used"] == ["get_inventory_summary"] and r["verified"]


def test_ask_without_key_is_honest(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    r = client().post("/api/ask", json={"question": "What should I order?"})
    assert r.status_code == 503 and "unavailable" in r.json()["message"]


class ToolFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def tool_turns(n, answer="Here is what I found."):
    """Fake model: n tool-call turns, then a text answer (answer=None never stops)."""
    i = 0
    while answer is None or i < n:
        i += 1
        yield AIMessage(content="", tool_calls=[{"name": "get_inventory_summary", "args": {}, "id": str(i)}])
    yield AIMessage(content=answer)


def test_real_tools_registered_and_invoked():
    from conftest import A, B, C
    msgs = iter([AIMessage(content="", tool_calls=[{"name": "create_purchase_plan", "args": {"budget_inr": 12000}, "id": "1"}]),
                 AIMessage(content="**What we found** Buy Product C first.")])
    res = agent_mod.run_agent([{"role": "user", "content": "plan for 12000"}], lambda: [A, B, C], model=ToolFake(messages=msgs))
    assert res["tools_used"] == ["create_purchase_plan"] and "12000" in res["tool_outputs"][0]
    names = {t.name for t in agent_mod.build_tools(lambda: [])}
    assert names == {"get_inventory_summary", "analyze_product", "identify_inventory_risks",
                     "calculate_replenishment", "create_purchase_plan", "compare_scenarios"}


def test_agent_runs_at_most_five_tools_then_answers():
    from conftest import A
    res = agent_mod.run_agent([{"role": "user", "content": "q"}], lambda: [A], model=ToolFake(messages=tool_turns(6)))  # 6th is blocked
    assert len(res["tools_used"]) == config.AGENT_MAX_TOOL_CALLS and res["answer"] == "Here is what I found."


def test_runaway_model_stops_without_leaking_limit_text():
    from conftest import A
    res = agent_mod.run_agent([{"role": "user", "content": "q"}], lambda: [A], model=ToolFake(messages=tool_turns(0, None)))
    assert res["answer"] == ""  # the ask graph turns this into "I couldn't complete that request"
