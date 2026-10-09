# Vibe Coding Log

**Platforms.** Claude Code in VS Code as the main pair programmer; GSD planner and executor agents for multi-step work; CodeRabbit for pull-request style review; the "ponytail" simplification skill to delete bloat; OpenRouter free and Claude models for live tests of the AI features.

**Prompt-engineering strategies**
- Hand the planner *locked decisions* and *verified facts* (library versions, file layout, formulas), so it never invents them.
- Write acceptance gates as runnable commands: test counts, `git diff --exit-code` on trained artifacts, a timing limit on training.
- Mock the language model in every unit test; only a few hand-run live checks touch a real model.
- Constrain the AI itself: it calls checked functions for numbers, and a verify step rejects any figure that is not in a tool result.

**Agentic workflow.** Plan, then execute in small steps, then one atomic commit per task, then review. Examples: the first full app `95c52d2`; LangGraph ask and entry workflows `8b131ef`; bloat removed with ponytail `16861c2`; agent-limit crash fixed `1cc0f81`; OpenRouter support `089a701`; flexible CSV reading `bead6c9`; review fixes `c9e3a15`; layout restructure `09f5cfb`; the ML forecast `638d6f2`.

**What humans owned and verified**
- Scope and the rubric: which problem, which persona, what is out of scope.
- Every formula: safety stock Z x sigma x sqrt(lead time), reorder point, budget allocation, WAPE; checked by hand against test cases with exact expected numbers.
- Accepting or rejecting each review comment before it was applied.
- Live demo checks in a real browser and with real CSV files.
- The final numbers: every figure in the docs was copied from `models/metrics.json` after a clean retrain, not from memory. The retrain is deterministic, so the same numbers come back.

**Where the AI got it wrong, and how we caught it.** The agent leaked internal limit text and crashed on multi-tool questions (found in manual testing, fixed in `1cc0f81`). For the forecast we report the holdout result as measured (4.1% better than the flat average), not a hoped-for one.
