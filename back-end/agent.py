"""LangChain agent (create_agent + Claude) with bounded execution."""
import logging

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware

import config
from tools import build_tools

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
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=config.ANTHROPIC_MODEL, api_key=config.ANTHROPIC_API_KEY,
                         temperature=0, timeout=config.AGENT_TIMEOUT_SECONDS,
                         max_retries=config.AGENT_MAX_RETRIES, max_tokens=1500)


def build_agent(get_items, tool_log: list, model=None):
    return create_agent(
        model=model or get_model(),
        tools=build_tools(get_items, tool_log),
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            ToolCallLimitMiddleware(run_limit=config.AGENT_MAX_TOOL_CALLS, exit_behavior="end"),
            ModelCallLimitMiddleware(run_limit=config.AGENT_MAX_TOOL_CALLS + 2, exit_behavior="end"),
        ],
    )


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(c.get("text", "") for c in content if isinstance(c, dict))


def ask(question: str, get_items, model=None) -> dict:
    tool_log: list = []
    agent = build_agent(get_items, tool_log, model)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]},
                          config={"recursion_limit": config.AGENT_RECURSION_LIMIT})
    answer = ""
    for m in reversed(result["messages"]):
        if getattr(m, "type", "") == "ai" and _text(m.content).strip():
            answer = _text(m.content).strip()
            break
    log.info("question=%r tools=%s", question, tool_log)
    return {"answer": answer or "I couldn't complete that request. Please try rephrasing it.",
            "tools_used": [t["tool"] for t in tool_log]}
