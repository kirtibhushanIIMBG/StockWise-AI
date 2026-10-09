"""LangGraph workflows that orchestrate the AI features.

ASK graph   (questions)       guard → agent → verify ─(ok)──────────────→ finalize
                                                  └─(unverified)→ revise ─┘ (max 1 rewrite)
ENTRY graph (describe stock)  extract → review ⟲ validate → commit
                                          └─ interrupt(): waits for the user to confirm or cancel

`agent` is the LangChain `create_agent` tool-calling agent (see agent.py). Everything around it is
deterministic: the guard needs no model, the verify step checks every figure in the answer against
the tool outputs, and nothing is written to the inventory until the human review step is resumed
with an explicit "save". Both graphs use an in-memory checkpointer, so each browser session keeps
its chat history and its unsaved draft between requests (lost on server restart, like the rest).
"""
import re
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from . import agent as agent_mod
from . import config
from . import language_parser as lp
from .data import validate_records

NO_DATA = "We need your stock information before we can make a recommendation. Upload a file or describe your stock first."
NO_ANSWER = "I couldn't complete that request. Please try rephrasing it."
UNVERIFIED_NOTE = ("\n\n*Note: some figures above could not be matched to your inventory data. "
                   "Please confirm them in the Inventory Health table.*")


@dataclass
class Ctx:
    """Per-request runtime context. Tools only ever see this session's data."""
    get_items: Callable[[], list[dict]]
    save_items: Optional[Callable[[list[dict]], None]] = None
    model: Any = None  # None = the configured Claude model; tests inject a fake


# ---------------------------------------------------------------- number grounding
NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
# Disclosed policy constants the answer may mention: review period, buffer days, service level, Z, excess days.
POLICY_NUMBERS = {7.0, 2.0, 95.0, 1.65, 60.0, 0.5}


def _numbers(text: str) -> list[tuple[str, float]]:
    out = []
    for m in NUM_RE.findall(text or ""):
        s = m.rstrip(",").replace(",", "")
        try:
            out.append((s, float(s)))
        except ValueError:
            pass
    return out


def ungrounded_numbers(answer: str, evidence: list[str], question: str = "") -> list[str]:
    """Figures in the answer that do not appear in the tool outputs or the question.
    Small whole numbers (≤10, e.g. list positions, "top 3") and policy constants are allowed,
    and a figure may be a rounded form of a tool value (e.g. 3.75 shown as 3.8)."""
    known = {v for _, v in _numbers(" ".join(evidence) + " " + question)}
    bad = []
    for s, v in _numbers(answer):
        if v in known or v in POLICY_NUMBERS or (v.is_integer() and v <= 10):
            continue
        places = len(s.split(".")[1]) if "." in s else 0
        if any(round(k, places) == v for k in known):
            continue
        if s not in bad:
            bad.append(s)
    return bad


# ---------------------------------------------------------------- ASK graph
class AskState(TypedDict, total=False):
    messages: Annotated[list, add_messages]  # remembered chat: questions + final answers only
    question: str
    draft: str
    answer: str
    tools_used: list[str]
    evidence: list[str]                       # raw tool outputs for this turn
    unverified: list[str]
    revisions: int
    verified: bool


def guard(state: AskState, runtime: Runtime[Ctx]) -> dict:
    turn = {"messages": [HumanMessage(state["question"])], "draft": "", "answer": "", "tools_used": [],
            "evidence": [], "unverified": [], "revisions": 0, "verified": False}
    if not runtime.context.get_items():
        turn.update(answer=NO_DATA, verified=True)
    return turn


def call_agent(state: AskState, runtime: Runtime[Ctx]) -> dict:
    history = state["messages"][-config.AGENT_MEMORY_MESSAGES:]
    while history[0].type != "human":  # never start with an answer whose question was cut off
        history = history[1:]
    res = agent_mod.run_agent(history, runtime.context.get_items, runtime.context.model)
    return {"draft": res["answer"], "evidence": res["tool_outputs"], "tools_used": res["tools_used"]}


def verify(state: AskState) -> dict:
    bad = ungrounded_numbers(state.get("draft", ""), state.get("evidence", []), state["question"])
    return {"unverified": bad, "verified": not bad and bool(state.get("draft"))}


def revise(state: AskState, runtime: Runtime[Ctx]) -> dict:
    """One tool-free rewrite: keeps the request within the 5-tool-call limit."""
    model = runtime.context.model or agent_mod.get_model()
    evidence = "\n".join(state.get("evidence", []))[:6000] or "(no calculations were run)"
    prompt = (f"Question: {state['question']}\n\nStockWise calculation results:\n{evidence}\n\n"
              f"Your draft answer:\n{state['draft']}\n\n"
              f"These figures in the draft do not appear in the calculation results: {', '.join(state['unverified'])}. "
              "Rewrite the answer using only figures that appear in the results. Do not calculate new numbers; "
              "if a figure is not available, say what information is missing.")
    out = model.invoke([SystemMessage(agent_mod.SYSTEM_PROMPT), HumanMessage(prompt)])
    return {"draft": agent_mod._text(out.content).strip() or state["draft"], "revisions": state.get("revisions", 0) + 1}


def finalize(state: AskState) -> dict:
    answer = state.get("answer") or state.get("draft") or NO_ANSWER
    if state.get("unverified"):
        answer += UNVERIFIED_NOTE
    return {"answer": answer, "messages": [AIMessage(answer)]}


def after_guard(state: AskState) -> str:
    return "finalize" if state.get("answer") else "agent"


def after_verify(state: AskState) -> str:
    if state.get("unverified") and state.get("revisions", 0) < config.ASK_MAX_REVISIONS:
        return "revise"
    return "finalize"


def build_ask_graph(checkpointer=None):
    g = StateGraph(AskState, context_schema=Ctx)
    g.add_node("guard", guard)
    g.add_node("agent", call_agent)
    g.add_node("verify", verify)
    g.add_node("revise", revise)
    g.add_node("finalize", finalize)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", after_guard, ["agent", "finalize"])
    g.add_edge("agent", "verify")
    g.add_conditional_edges("verify", after_verify, ["revise", "finalize"])
    g.add_edge("revise", "verify")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


# ---------------------------------------------------------------- ENTRY graph
EDITABLE = {"sku", "product_name", "category", "supplier", "current_stock", "avg_daily_demand",
            "lead_time_days", "unit_cost", "safety_stock", "incoming_stock", "backorders"}


class EntryState(TypedDict, total=False):
    text: str
    rows: list[dict]      # editable preview shown to the user
    message: str
    decision: dict        # what the user sent back from the review step
    errors: list[str]
    valid: list[dict]
    saved: list[str]      # SKUs written to the inventory
    status: str           # "empty" | "cancelled" | "saved"


def _vague_message(text: str, items: list[dict]) -> str:
    low = text.lower()
    known = [i["product_name"] for i in items if i["product_name"].lower() in low
             or any(w in low for w in i["product_name"].lower().split() if len(w) > 4)]
    msg = ("We couldn't find specific stock numbers in your description. Please tell us: units in stock, "
           "average daily sales, supplier delivery time (days) and cost per unit.")
    if known:
        msg += f" We already have {', '.join(known[:3])} in your inventory — try asking StockWise about it."
    return msg


def extract(state: EntryState, runtime: Runtime[Ctx]) -> dict:
    items = runtime.context.get_items()
    result = lp.extract(state["text"], llm=runtime.context.model)
    rows = lp.build_preview(result, {i["sku"] for i in items}, {i["product_name"].lower(): i for i in items})
    if not rows:
        return {"rows": [], "status": "empty", "message": _vague_message(state["text"], items)}
    return {"rows": rows, "errors": []}


def review(state: EntryState) -> dict:
    """Pause until the user confirms. Resume with Command(resume={"action": "save"|"cancel", ...})."""
    decision = interrupt({"rows": state["rows"], "errors": state.get("errors", [])})
    if not isinstance(decision, dict) or decision.get("action") != "save":
        return {"decision": {}, "status": "cancelled"}
    return {"decision": decision}


def validate(state: EntryState, runtime: Runtime[Ctx]) -> dict:
    d = state["decision"]
    # An update starts from the saved item, so fields the preview doesn't show (price, supplier…) survive.
    saved = {i["sku"]: i for i in runtime.context.get_items()}
    rows = [{**saved.get(str(r.get("sku")), {}), **{k: v for k, v in r.items() if k in EDITABLE}}
            for r in d.get("items") or []]
    errors = [f"Please enter extra buffer units for {r.get('product_name') or 'each product'}, or accept the default buffer."
              for r in rows if r.get("safety_stock") in (None, "") and not d.get("apply_default_buffer", True)]
    items, problems = validate_records(rows) if rows else ([], ["There are no products to save."])
    errors += problems
    return {"errors": errors, "valid": items}  # errors → back to the review step


def commit(state: EntryState, runtime: Runtime[Ctx]) -> dict:
    runtime.context.save_items(state["valid"])
    return {"saved": [i["sku"] for i in state["valid"]], "status": "saved"}


def build_entry_graph(checkpointer=None):
    g = StateGraph(EntryState, context_schema=Ctx)
    g.add_node("extract", extract)
    g.add_node("review", review)
    g.add_node("validate", validate)
    g.add_node("commit", commit)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", lambda s: "review" if s.get("rows") else END, ["review", END])
    g.add_conditional_edges("review", lambda s: END if s.get("status") == "cancelled" else "validate",
                            ["validate", END])
    g.add_conditional_edges("validate", lambda s: "review" if s.get("errors") else "commit", ["review", "commit"])
    g.add_edge("commit", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


ASK_GRAPH = build_ask_graph()
ENTRY_GRAPH = build_entry_graph()


def thread(thread_id: str, recursion_limit: int = config.ASK_GRAPH_RECURSION_LIMIT) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}


def pending_review(result: dict) -> Optional[dict]:
    """The payload of the review interrupt, if the entry graph is paused waiting for the user."""
    intr = result.get("__interrupt__")
    return intr[0].value if intr else None
