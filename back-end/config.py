"""Central configuration. All policy defaults live here so they are easy to disclose and change."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()

# Inventory policy defaults
REVIEW_PERIOD_DAYS = 7
SERVICE_Z = 1.65                 # ~95% one-sided service level
DEFAULT_BUFFER_DAYS = 2          # fallback buffer when no safety stock / variability supplied
EXCESS_COVERAGE_DAYS = 60        # coverage above this = excess stock
LOW_DEMAND_THRESHOLD = 0.5       # units/day at or below this = low demand

# Agent guardrails
AGENT_MAX_TOOL_CALLS = 5
AGENT_RECURSION_LIMIT = 40       # graph steps, not turns: ~5 per tool turn; the call limits above stop by 33
AGENT_TIMEOUT_SECONDS = 60
AGENT_MAX_RETRIES = 1
AGENT_MEMORY_MESSAGES = 6        # recent chat turns (questions + answers) passed back to the agent
ASK_MAX_REVISIONS = 1            # rewrites allowed when an answer contains unverified figures
ASK_GRAPH_RECURSION_LIMIT = 10   # outer LangGraph workflow steps

SAMPLE_CSV = ROOT / "data" / "sample_inventory.csv"
FRONTEND_DIR = ROOT.parent / "front-end"


def ai_available() -> bool:
    return bool(ANTHROPIC_API_KEY)
