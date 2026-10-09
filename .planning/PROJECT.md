# StockWise AI — Applied AI & ML Capstone

**What:** Inventory replenishment and procurement decision-support web app for small/mid-sized Indian retailers and distributors (FastAPI back end, vanilla HTML/CSS/JS front end, LangChain/LangGraph assistant).

**Course brief (AI and ML for Digital Business Managers):** teams of 8–9 build an end-to-end AI/ML business product.
Deliverables: (A) Python web prototype usable by non-technical executives + production-grade Python ML pipeline (scikit-learn / XGBoost / PyTorch / HF) doing real-time inference; (B) 15-min presentation — 5-min executive pitch (opportunity, persona, ROI, market strategy) + 10-min technical deep dive (architecture diagram, feature selection, model optimisation, cross-validation results, error analysis) + live demo; (C) clean modular GitHub repo with `src/data.py`, `src/model.py`, `app.py`, complete `requirements.txt`, and a 1-page Vibe Coding Log.

**Rubric:** Business value & usability 30 · Technical rigor & pipeline (preprocessing, scaling, tuning, CV, SHAP/LIME) 40 · Under-the-hood defence 20 · Engineering efficiency & vibe coding 10.

**Track:** 4 — Predictive Operations (demand forecasting feeding inventory decisions).

**Constraints:** venv lives at `~/.venvs/stockwise` (path contains ":"); `.env` must never be read or committed; existing 73 tests must keep passing; unit tests never call a live LLM.
