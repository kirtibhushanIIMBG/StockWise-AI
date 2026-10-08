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


def test_confirm_requires_valid_data():
    c = client()
    assert c.post("/api/confirm-inventory", json={"items": [{"product_name": "Soap"}]}).status_code == 400
    ok = c.post("/api/confirm-inventory", json={"items": [{"sku": "SKU-SH", "product_name": "Shampoo",
              "current_stock": 50, "avg_daily_demand": 8, "lead_time_days": 6, "unit_cost": 120}]}).json()
    assert ok["ok"] and ok["added"][0]["safety_stock"] == 16 and ok["added"][0]["safety_stock_method"] == "default_buffer"


def test_ask_without_key_is_honest(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    r = client().post("/api/ask", json={"question": "What should I order?"})
    assert r.status_code == 503 and "unavailable" in r.json()["message"]


class ToolFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def test_real_tools_registered_and_invoked():
    from conftest import A, B, C
    msgs = iter([AIMessage(content="", tool_calls=[{"name": "create_purchase_plan", "args": {"budget_inr": 12000}, "id": "1"}]),
                 AIMessage(content="**What we found** Buy Product C first.")])
    log = []
    ag = agent_mod.build_agent(lambda: [A, B, C], log, model=ToolFake(messages=msgs))
    out = ag.invoke({"messages": [{"role": "user", "content": "plan for 12000"}]})
    tool_msg = [m for m in out["messages"] if m.type == "tool"][0]
    assert '"total_spend": 12000' in tool_msg.content or "12000" in tool_msg.content
    assert log == [{"tool": "create_purchase_plan", "args": {"budget_inr": 12000}}]
    names = {t.name for t in agent_mod.build_tools(lambda: [], [])}
    assert names == {"get_inventory_summary", "analyze_product", "identify_inventory_risks",
                     "calculate_replenishment", "create_purchase_plan", "compare_scenarios"}


def test_agent_tool_call_limit_bounds_loop():
    from conftest import A
    def endless():
        i = 0
        while True:
            i += 1
            yield AIMessage(content="", tool_calls=[{"name": "get_inventory_summary", "args": {}, "id": str(i)}])
    log = []
    ag = agent_mod.build_agent(lambda: [A], log, model=ToolFake(messages=endless()))
    ag.invoke({"messages": [{"role": "user", "content": "loop"}]}, config={"recursion_limit": 30})
    assert len(log) <= config.AGENT_MAX_TOOL_CALLS
