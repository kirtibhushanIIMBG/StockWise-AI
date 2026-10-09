"""StockWise AI — FastAPI app. Serves the API and the front-end from one server.

Run:  ~/.venvs/stockwise/bin/uvicorn app:app --port 8000   (from the repo root)
"""
import csv
import io
import json
import logging
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

from src import config, graph
from src.data import REQUIRED, DataError, NeedsInput, load_csv_path, load_sales_history, parse_csv
from src.explanation_engine import explain_plan, explain_product
from src.inventory_engine import analyze_all, summarize
from src.procurement_engine import compare_budgets, compare_lead_time, purchase_plan
from src.schemas import MAX_BUDGET, AskRequest, ConfirmRequest, ParseRequest, PurchasePlanRequest, ScenarioRequest
from src.model import explain_row, forecast_sku, inventory_comparison, load_forecaster, next_day_features
from src.session_store import store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stockwise")



@asynccontextmanager
async def lifespan(app: FastAPI):
    load_forecaster()  # load (or train) the demand model once, before the first request
    yield


app = FastAPI(title="StockWise AI", lifespan=lifespan)
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


def err(msg: str, code: int = 400, **extra):
    return JSONResponse({"ok": False, "message": msg, **extra}, status_code=code)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    # FastAPI's default reply echoes the input, which crashes on values like a 1e999 budget (infinity).
    return err("Please check what you entered: a value is missing, too long or out of range.", 422)


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


@app.post("/api/sample")  # POST only: opening a link must never wipe the user's inventory
def load_sample(request: Request):
    store.set_items(request.state.sid, load_csv_path(config.SAMPLE_CSV), "sample")
    return inventory_payload(request.state.sid)


@app.get("/api/sample.csv")
def sample_csv():
    return FileResponse(config.SAMPLE_CSV, filename="stockwise_sample_inventory.csv", media_type="text/csv")


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), mapping: str = Form("{}"),
                 defaults: str = Form("{}"), demand_period: float = Form(1)):
    """mapping {field: column header} and defaults {field: number} come from the "help us read
    your file" form, shown when a required column can't be found automatically."""
    content = await file.read(25_000_001)  # never pull a huge upload into memory
    if len(content) > 25_000_000:
        return err("This file is too large. Please upload a file under 25 MB.")
    try:
        mapping, defaults = json.loads(mapping), json.loads(defaults)
        if not (isinstance(mapping, dict) and isinstance(defaults, dict)) or not 0 < demand_period <= 365:  # also NaN/inf
            raise ValueError
        defaults = {k: float(v) for k, v in defaults.items()}
        if any(v < 0 for v in defaults.values()):
            raise ValueError
    except (ValueError, TypeError):
        return err("Please enter numbers of zero or more.")
    try:
        items, warnings, notes = parse_csv(content, mapping, defaults, demand_period)
    except NeedsInput as e:
        return err(str(e), 422, needs_input=True, columns=e.columns,
                   missing=[{"field": f, "label": REQUIRED[f]} for f in e.missing])
    except DataError as e:
        log.warning("upload failed: %s", e)
        return err(str(e))
    store.set_items(request.state.sid, items, "upload")
    return {**inventory_payload(request.state.sid), "warnings": warnings, "notes": notes, "loaded": len(items)}


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
    # No, invalid or out-of-range budget (e.g. "inf") = export everything recommended.
    ok = budget is not None and 0 <= budget <= MAX_BUDGET
    p = purchase_plan(store.get_items(request.state.sid), budget if ok else MAX_BUDGET)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Priority", "SKU", "Product", "Category", "Stock Status", "Recommended Units",
                "Units to Buy", "Unit Cost (INR)", "Cost (INR)", "Units Still Needed", "Funding"])
    for l in p["lines"]:
        w.writerow([l["priority"], l["sku"], l["product_name"], l["category"], l["status"],
                    l["recommended_qty"], l["buy_qty"], l["unit_cost"], l["cost"], l["unfunded_qty"], l["funding"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=stockwise_purchase_plan.csv"})


@lru_cache(maxsize=1)
def sales_history():
    return load_sales_history()


@app.get("/api/forecast/model")  # declared before /api/forecast/{sku}, or "model" would be read as a SKU
def forecast_model():
    m = json.loads(config.METRICS_PATH.read_text())
    c, h, imp = m["chosen_model"]["name"], m["holdout"], m["improvement_pct"]
    summary = (f"The {c.replace('_', ' ')} model's daily forecast is off by {h[c]['mae']:.2f} units on average over "
               f"{m['data']['holdout_days']} days it never saw, against {h['flat_average']['mae']:.2f} for the flat "
               f"average ({imp['vs_flat_average']:.1f}% better) and {h['seasonal_naive']['mae']:.2f} for repeating last "
               f"week ({imp['vs_seasonal_naive']:.1f}% better). Demo data is synthetic.")
    return {"ok": True, "summary": summary, **m}


@app.get("/api/forecast/{sku}")
def forecast(sku: str, horizon: int | None = Query(None, ge=1, le=90)):
    item = next((i for i in load_csv_path(config.SAMPLE_CSV) if i["sku"] == sku), None)
    hist = sales_history()
    if item is None or sku not in set(hist["sku"]):
        return err(f"No sales history for product '{sku[:40]}'.", 404)
    n = horizon or round(item["lead_time_days"]) + config.REVIEW_PERIOD_DAYS
    bundle = load_forecaster()
    fc = forecast_sku(bundle, hist, sku, n)
    base, drivers = explain_row(bundle, next_day_features(hist, sku))
    for d in drivers:
        d["contribution"] = round(d["contribution"], 2)
    inv = inventory_comparison(item, [p["units"] for p in fc], bundle)
    last = hist[hist["sku"] == sku].tail(60)
    top = drivers[0]
    return {"ok": True, "sku": sku, "product_name": item["product_name"], "horizon": n,
            "history": [{"date": d.date().isoformat(), "units": int(u)} for d, u in zip(last["date"], last["units_sold"])],
            "forecast": fc, "base_value": round(base, 2), "drivers": drivers, "inventory": inv,
            "summary": (f"Expected demand tomorrow is {fc[0]['units']:.1f} units (the average product sells {base:.1f}); "
                        f"the biggest factor is '{top['label']}' ({top['contribution']:+.1f}). Ordering on the forecast "
                        f"gives a reorder point of {inv['forecast']['reorder_point']} units instead of "
                        f"{inv['simple_average']['reorder_point']}."),
            "assumptions": ["No promotions are planned in the forecast period.",
                            "Sales history is synthetic demo data.",
                            "Safety stock uses the model's error on the last 56 days, not the flat demand spread."]}


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="front-end")
