---
phase: quick-261009-ooa
plan: 01
subsystem: ml-forecasting
tags: [scikit-learn, shap, fastapi, time-series-cv, docs]
status: complete
requirements-completed: [BRIEF-A-ML-PIPELINE, BRIEF-A-WEB-PROTOTYPE, BRIEF-B-PRESENTATION, BRIEF-C-REPO-LAYOUT, BRIEF-C-VIBE-LOG, RUBRIC-BUSINESS-ROI]
plan_head_before: c9e3a15
plan_head_after: 243e9d3
commits: 4
actuals:
  tasks: 3
  commits: 4
key-files:
  created: [src/model.py, tests/test_model.py, data/sales_history.csv, models/forecast_model.joblib, models/metrics.json, docs/BUSINESS_CASE.md, docs/PRESENTATION_OUTLINE.md, VIBE_CODING_LOG.md, requirements.txt, pytest.ini]
  modified: [app.py, src/config.py, src/data.py, README.md]
---

# Quick 261009-ooa: Close capstone gaps (layout, ML forecast, docs)

One-liner: back-end/ restructured into src/ + app.py with exact pins, plus a deterministic scikit-learn demand forecast (time-series CV, GridSearchCV, SHAP, error analysis) exposed only through FastAPI; front-end/ untouched.

## Commits
| Task | Hash | Message |
|---|---|---|
| A | 09f5cfb | refactor: move back-end into src/ package with app.py entry point and pinned requirements |
| B | 638d6f2 | feat: ML demand forecasting with time-series CV, tuning, SHAP and error analysis via FastAPI |
| C | c503a22 | docs: business case, vibe coding log, presentation outline and README for ML + new layout |
| C (follow-up, coordinator request) | 243e9d3 | docs: restructure presentation outline into 11 slides with bullets, notes and presenters |

## Headline metrics (models/metrics.json, synthetic data)
- Chosen model: HistGradientBoostingRegressor (learning_rate 0.05, max_depth 4, max_iter 300, l2 0.0)
- 5-fold TimeSeriesSplit CV MAE: boosting 3.02 +/- 0.09; Lasso 3.07; Ridge 3.08; flat average 3.14; seasonal naive 4.21
- Untouched 56-day holdout MAE: boosting 3.06 vs flat average 3.19 vs seasonal naive 4.26
- Improvement: 4.1% vs flat average, 28.2% vs seasonal naive
- ROI signal: safety stock for 24 demo products Rs 48,570 (361 units) to Rs 46,690 (345 units), 3.9% less, Rs 1,880 freed
- Honest note: the gain over the flat average is modest (noisy synthetic demand, the model under-forecasts festival/promo days and the upward trend); docs say so.
- Tests: 82 passed (73 original + 9 new). Training 33-38 s, byte-identical metrics.json / sales_history.csv / joblib on rerun (git diff clean).

## Deviations from Plan
- Holdout scores are reported for all three learned models (not only the chosen one); the choice is made on CV only.
- Presentation outline restructured to the coordinator's 11-slide format in a follow-up commit (instruction arrived after Task C was committed).
- Added a "summary" plain-English string to both forecast endpoints (per the no-front-end instruction).
- `_group_scores` returns n=0/None for empty groups (small test data has no festival rows).
- Rule 3 note: the first Task C docs gate failed on the "4%" check because the exact figure is 4.1%; added "about 4%" wording to README and outline.

## Known Stubs
None. Sales history is intentionally synthetic and labelled so everywhere.

## Verification
- Task A gate (73 passed, no old imports, exact pins match venv, app serves health, index, sample.csv) passed.
- Task B gate: tests, <60 s training, deterministic artifacts, improvement > 0, front-end unchanged: passed. The human-check (browser #forecast page) does not apply: the front end was deliberately not changed.
- Task C gate passed; .env never staged. Nothing pushed. Docs artifacts under .planning/ left uncommitted for the orchestrator.

## Self-Check: PASSED
