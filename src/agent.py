"""LangChain agent (create_agent + Claude) with bounded execution."""
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError

from . import config
from .tools import build_tools

log = logging.getLogger("stockwise.agent")

SYSTEM_PROMPT = """You are StockWise, an inventory and purchasing advisor for a non-technical supply chain manager.
Currency is Indian Rupees (₹).

Rules:
- ALWAYS call a tool to get numbers. Never calculate, estimate or invent any number yourself;
  only repeat numbers exactly as the tools returned them.
- Use as few tool calls as possible (usually 1-2), then answer and stop.
- If a product is not found or information is missing, say exactly what information is needed.
  Do not assume quantities from vague words like "very little".
- You cannot place orders or change saved data. What-if scenarios do not change the saved inventory.
- Only answer inventory and purchasing questions.

Answer format (markdown, short, business language, no jargon, no JSON, never mention tools):
**What we found** – 1-2 sentences.
**Why it matters** – 1-2 sentences.
**What we recommend** – specific action; a small table if listing several products.
**Estimated cost** – from tool output, or "No purchase needed".
Mention key assumptions briefly (e.g. 7-day review period, default buffer) when relevant."""


def get_model():
    """The one chat model behind both AI features: OpenRouter if its key is set, else Anthropic."""
    opts = dict(model=config.AI_MODEL, temperature=0, max_retries=config.AGENT_MAX_RETRIES, max_tokens=2000)
    if config.OPENROUTER_API_KEY:
        from langchain_openrouter import ChatOpenRouter
        return ChatOpenRouter(api_key=config.OPENROUTER_API_KEY, timeout=config.AGENT_TIMEOUT_SECONDS * 1000, **opts)  # ms
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(api_key=config.ANTHROPIC_API_KEY, timeout=config.AGENT_TIMEOUT_SECONDS, **opts)  # seconds


def build_agent(get_items, model=None):
    return create_agent(
        model=model or get_model(),
        tools=build_tools(get_items),
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # Calls past the limit don't run; the model is told to answer with what it already has.
            ToolCallLimitMiddleware(run_limit=config.AGENT_MAX_TOOL_CALLS, exit_behavior="continue"),
            # Hard stop for a model that keeps going anyway ("end" would show its limit text to the user).
            ModelCallLimitMiddleware(run_limit=config.AGENT_MAX_TOOL_CALLS + 2, exit_behavior="error"),
        ],
    )


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


def run_agent(messages: list, get_items, model=None) -> dict:
    """Run the tool-using agent on a short conversation (oldest first, last = current question).
    Returns the draft answer plus the raw tool outputs, which the LangGraph verify step checks against."""
    try:
        result = build_agent(get_items, model).invoke(
            {"messages": messages}, config={"recursion_limit": config.AGENT_RECURSION_LIMIT})
    except ModelCallLimitExceededError:
        log.warning("model call limit reached")
        return {"answer": "", "tools_used": [], "tool_outputs": []}  # → "couldn't complete that request"
    new = result["messages"][len(messages):]  # ignore the conversation history we passed in
    ran = [m for m in new if m.type == "tool" and m.status == "success"]  # blocked calls come back as errors
    answer = next((_text(m.content).strip() for m in reversed(new) if m.type == "ai" and _text(m.content).strip()), "")
    log.info("tool calls=%s", [(c["name"], c["args"]) for m in new if m.type == "ai" for c in m.tool_calls])
    return {"answer": answer, "tools_used": [m.name for m in ran], "tool_outputs": [_text(m.content) for m in ran]}
