"""StockWise AI — FastAPI app. Serves the API and the front-end from one server.

Run:  uvicorn main:app --reload   (from the back-end folder)
"""
import csv
import io
import logging
import uuid

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

import config
import graph
from data_processing import DataError, load_csv_path, parse_csv
from explanation_engine import explain_plan, explain_product
from inventory_engine import analyze_all, summarize
from procurement_engine import compare_budgets, compare_lead_time, purchase_plan
from schemas import AskRequest, ConfirmRequest, ParseRequest, PurchasePlanRequest, ScenarioRequest
from session_store import store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stockwise")

app = FastAPI(title="StockWise AI")
COOKIE = "sw_sid"
AI_OFF = "AI questions are unavailable until the assistant is connected."
AI_DOWN = ("The AI assistant is temporarily unavailable. Your inventory dashboard and "
           "purchasing calculations are still available.")


@app.middleware("http")
async def session_cookie(request: Request, call_next):
    sid = request.cookies.get(COOKIE)
    new = not sid or len(sid) != 32
    if new:
        sid = uuid.uuid4().hex
    request.state.sid = sid
    resp = await call_next(request)
    if new:
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return resp


def err(msg: str, code: int = 400):
    return JSONResponse({"ok": False, "message": msg}, status_code=code)


def inventory_payload(sid: str) -> dict:
    rows = analyze_all(store.get_items(sid))
    for r in rows:
        r["explanation"] = explain_product(r)
    return {"ok": True, "source": store.source(sid), "summary": summarize(rows), "products": rows}


@app.get("/api/health")
def health():
    return {"ok": True, "ai_available": config.ai_available()}


@app.get("/api/inventory")
def inventory(request: Request):
    return inventory_payload(request.state.sid)


@app.post("/api/sample")
@app.get("/api/sample")
def load_sample(request: Request):
    store.set_items(request.state.sid, load_csv_path(config.SAMPLE_CSV), "sample")
    return inventory_payload(request.state.sid)


@app.get("/api/sample.csv")
def sample_csv():
    return FileResponse(config.SAMPLE_CSV, filename="stockwise_sample_inventory.csv", media_type="text/csv")


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 2_000_000:
        return err("This file is too large. Please upload a file under 2 MB.")
    try:
        items, warnings = parse_csv(content)
    except DataError as e:
        log.warning("upload failed: %s", e)
        return err("We couldn't read this file. Please check the format or use our sample file.")
    store.set_items(request.state.sid, items, "upload")
    return {**inventory_payload(request.state.sid), "warnings": warnings, "loaded": len(items)}


def session_ctx(sid: str) -> graph.Ctx:
    """Runtime context for the LangGraph workflows, bound to one browser session."""
    return graph.Ctx(get_items=lambda: store.get_items(sid), save_items=lambda items: store.upsert(sid, items))


@app.post("/api/parse-inventory")
def parse_inventory(request: Request, body: ParseRequest):
    """Start the entry graph: extract → pause at the human review step (nothing is saved yet)."""
    if not config.ai_available():
        return err(AI_OFF, 503)
    sid = request.state.sid
    thread_id = f"{sid}:entry:{uuid.uuid4().hex[:8]}"  # a fresh draft replaces any earlier unsaved one
    try:
        result = graph.ENTRY_GRAPH.invoke({"text": body.text}, graph.thread(thread_id), context=session_ctx(sid))
    except Exception:  # noqa: BLE001
        log.exception("parse failed")
        return err(AI_DOWN, 503)
    review = graph.pending_review(result)
    if review is None:  # vague text: nothing to confirm (Scenario 6)
        store.set_pending(sid, None)
        return {"ok": True, "rows": [], "message": result["message"]}
    store.set_pending(sid, thread_id)
    return {"ok": True, "rows": review["rows"]}


@app.post("/api/confirm-inventory")
def confirm_inventory(request: Request, body: ConfirmRequest):
    """Resume the paused entry graph with the user's (possibly edited) rows."""
    sid = request.state.sid
    thread_id = store.get_pending(sid)
    if not thread_id:
        return err("There is nothing waiting to be saved. Describe your stock first.", 409)
    decision = {"action": "save", "items": body.items, "apply_default_buffer": body.apply_default_buffer}
    result = graph.ENTRY_GRAPH.invoke(Command(resume=decision), graph.thread(thread_id), context=session_ctx(sid))
    review = graph.pending_review(result)
    if review is not None:  # validation failed: the graph is back at the review step, still unsaved
        return err("Some details are missing or invalid. " + " ".join(review["errors"]))
    store.set_pending(sid, None)
    out = inventory_payload(sid)
    out["added"] = [r for r in out["products"] if r["sku"] in set(result.get("saved", []))]
    return out


@app.post("/api/cancel-inventory")
def cancel_inventory(request: Request):
    sid = request.state.sid
    thread_id = store.get_pending(sid)
    if thread_id:
        graph.ENTRY_GRAPH.invoke(Command(resume={"action": "cancel"}), graph.thread(thread_id), context=session_ctx(sid))
        store.set_pending(sid, None)
    return {"ok": True, "message": "Nothing was changed."}


@app.post("/api/purchase-plan")
def plan(request: Request, body: PurchasePlanRequest):
    p = purchase_plan(store.get_items(request.state.sid), body.budget)
    return {"ok": True, **p, "explanation": explain_plan(p)}


@app.post("/api/scenario")
def scenario(request: Request, body: ScenarioRequest):
    items = store.get_items(request.state.sid)
    if body.kind == "budget":
        if body.budget_a is None or body.budget_b is None:
            return err("Please enter both budgets to compare.")
        return {"ok": True, **compare_budgets(items, body.budget_a, body.budget_b)}
    if not body.sku or body.new_lead_time is None:
        return err("Please choose a product and a new delivery time.")
    res = compare_lead_time(items, body.sku, body.new_lead_time)
    if "error" in res:
        return err("We couldn't find this product in your inventory.", 404)
    return {"ok": True, **res}


@app.post("/api/ask")
def ask(request: Request, body: AskRequest):
    """Run the ask graph: guard → LangChain agent → number check → (rewrite) → answer.
    The chat thread is keyed by session, so follow-up questions keep their context."""
    if not config.ai_available():
        return err(AI_OFF, 503)
    sid = request.state.sid
    try:
        res = graph.ASK_GRAPH.invoke({"question": body.question}, graph.thread(f"{sid}:chat"), context=session_ctx(sid))
    except Exception:  # noqa: BLE001
        log.exception("agent failed")
        return err(AI_DOWN, 503)
    return {"ok": True, "answer": res["answer"], "tools_used": res["tools_used"], "verified": res["verified"]}


@app.get("/api/export")
def export(request: Request, budget: float | None = None):
    # No (or invalid) budget = export everything recommended.
    p = purchase_plan(store.get_items(request.state.sid), budget if budget is not None and budget >= 0 else 1e15)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Priority", "SKU", "Product", "Category", "Stock Status", "Recommended Units",
                "Units to Buy", "Unit Cost (INR)", "Cost (INR)", "Units Still Needed", "Funding"])
    for l in p["lines"]:
        w.writerow([l["priority"], l["sku"], l["product_name"], l["category"], l["status"],
                    l["recommended_qty"], l["buy_qty"], l["unit_cost"], l["cost"], l["unfunded_qty"], l["funding"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=stockwise_purchase_plan.csv"})


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="front-end")
