"""StockWise AI — FastAPI app. Serves the API and the front-end from one server.

Run:  uvicorn main:app --reload   (from the back-end folder)
"""
import csv
import io
import logging
import math

from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from data_processing import DataError, parse_csv, validate_records
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
        sid = store.new_id()
    request.state.sid = sid
    resp = await call_next(request)
    if new:
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    return resp


def err(msg: str, code: int = 400, **extra):
    return JSONResponse({"ok": False, "message": msg, **extra}, status_code=code)


def inventory_payload(sid: str) -> dict:
    rows = analyze_all(store.get_items(sid))
    for r in rows:
        r["explanation"] = explain_product(r)
    return {"ok": True, "source": store.source(sid), "summary": summarize(rows), "products": rows}


@app.get("/api/health")
def health():
    return {"ok": True, "ai_available": config.ai_available(),
            "ai_message": None if config.ai_available() else AI_OFF}


@app.get("/api/inventory")
def inventory(request: Request):
    return inventory_payload(request.state.sid)


@app.post("/api/sample")
@app.get("/api/sample")
def load_sample(request: Request):
    from data_processing import load_csv_path
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
        return err("We couldn't read this file. Please check the format or use our sample file.", detail=str(e))
    store.set_items(request.state.sid, items, "upload")
    return {**inventory_payload(request.state.sid), "warnings": warnings, "loaded": len(items)}


@app.post("/api/parse-inventory")
def parse_inventory(request: Request, body: ParseRequest):
    if not config.ai_available():
        return err(AI_OFF, 503)
    from language_parser import build_preview, extract
    items = store.get_items(request.state.sid)
    try:
        result = extract(body.text)
    except Exception:  # noqa: BLE001
        log.exception("parse failed")
        return err(AI_DOWN, 503)
    preview = build_preview(result, {i["sku"] for i in items},
                            {i["product_name"].lower(): i["sku"] for i in items})
    if not preview["rows"]:
        # Scenario 6: vague text — check whether a mentioned product already exists
        known = [i["product_name"] for i in items if i["product_name"].lower() in body.text.lower()
                 or any(w in body.text.lower() for w in i["product_name"].lower().split() if len(w) > 4)]
        msg = ("We couldn't find specific stock numbers in your description. Please tell us: units in stock, "
               "average daily sales, supplier delivery time (days) and cost per unit.")
        if known:
            msg += f" We already have {', '.join(known[:3])} in your inventory — try asking StockWise about it."
        return {"ok": True, "intent": preview["intent"], "rows": [], "complete": False, "message": msg}
    return {"ok": True, **preview}


@app.post("/api/confirm-inventory")
def confirm_inventory(request: Request, body: ConfirmRequest):
    rows = []
    for r in body.items:
        r = {k: v for k, v in r.items() if k in {
            "sku", "product_name", "category", "supplier", "current_stock", "avg_daily_demand",
            "lead_time_days", "unit_cost", "safety_stock", "incoming_stock", "backorders"}}
        if r.get("safety_stock") in (None, "") and not body.apply_default_buffer:
            return err(f"Please enter extra buffer units for {r.get('product_name') or 'each product'}, "
                       "or accept the default buffer.")
        if r.get("safety_stock") in (None, "") and r.get("avg_daily_demand") not in (None, ""):
            r["safety_stock"] = None  # engine applies disclosed default buffer
        rows.append(r)
    items, errors = validate_records(rows)
    if errors or not items:
        return err("Some details are missing or invalid. " + " ".join(errors))
    store.upsert(request.state.sid, items)
    out = inventory_payload(request.state.sid)
    out["added"] = [r for r in out["products"] if r["sku"] in {i["sku"] for i in items}]
    return out


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
    if not config.ai_available():
        return err(AI_OFF, 503)
    from agent import ask as agent_ask
    sid = request.state.sid
    try:
        res = agent_ask(body.question, lambda: store.get_items(sid))
    except Exception:  # noqa: BLE001
        log.exception("agent failed")
        return err(AI_DOWN, 503)
    return {"ok": True, **res}


@app.get("/api/export")
def export(request: Request, budget: float | None = None):
    items = store.get_items(request.state.sid)
    if budget is None or math.isnan(budget) or budget < 0:
        budget = float("inf")
    p = purchase_plan(items, budget if budget != float("inf") else 1e15)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Priority", "SKU", "Product", "Category", "Stock Status", "Recommended Units",
                "Units to Buy", "Unit Cost (INR)", "Cost (INR)", "Units Still Needed", "Funding"])
    for l in p["lines"]:
        w.writerow([l["priority"], l["sku"], l["product_name"], l["category"], l["status"],
                    l["recommended_qty"], l["buy_qty"], l["unit_cost"], l["cost"], l["unfunded_qty"], l["funding"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=stockwise_purchase_plan.csv"})


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="front-end")
