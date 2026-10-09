---
phase: quick-261009-ooa
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/__init__.py
  - src/config.py
  - src/data.py
  - src/model.py
  - src/schemas.py
  - src/session_store.py
  - src/tools.py
  - src/agent.py
  - src/graph.py
  - src/language_parser.py
  - src/inventory_engine.py
  - src/procurement_engine.py
  - src/explanation_engine.py
  - app.py
  - requirements.txt
  - pytest.ini
  - data/sample_inventory.csv
  - data/sales_history.csv
  - models/forecast_model.joblib
  - models/metrics.json
  - tests/conftest.py
  - tests/test_api.py
  - tests/test_csv_formats.py
  - tests/test_graph.py
  - tests/test_inventory.py
  - tests/test_language_parser.py
  - tests/test_procurement.py
  - tests/test_model.py
  - docs/BUSINESS_CASE.md
  - docs/PRESENTATION_OUTLINE.md
  - VIBE_CODING_LOG.md
  - README.md
files_deleted:
  - back-end/requirements.txt
  - back-end/main.py
  - back-end/data_processing.py
autonomous: true
requirements:
  - BRIEF-A-ML-PIPELINE
  - BRIEF-A-WEB-PROTOTYPE
  - BRIEF-B-PRESENTATION
  - BRIEF-C-REPO-LAYOUT
  - BRIEF-C-VIBE-LOG
  - RUBRIC-BUSINESS-ROI

estimate:
  tokens: 190000
  raw_tokens: 190000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "From the repo root, `~/.venvs/stockwise/bin/python -m pytest -q` passes the original 73 tests plus the new model tests, with the brief-mandated layout src/data.py, src/model.py, app.py and an exactly-pinned root requirements.txt; back-end/ no longer exists."
    - "`~/.venvs/stockwise/bin/python -m src.model` trains in under 60 s and deterministically writes models/forecast_model.joblib and models/metrics.json, which show 5-fold date-aware time-series CV, GridSearchCV-tuned params, feature-group ablation, Lasso-zeroed features, SHAP ranking, error analysis, and a chosen model that beats the flat-average baseline on the untouched 56-day holdout."
    - "GET /api/forecast/{sku}?horizon=N runs real-time inference and returns 60 days of actuals, a non-negative daily forecast of the requested horizon, plain-English SHAP drivers, and a simple-average vs ML-forecast reorder point / order qty / cost comparison computed by the unchanged inventory engine; GET /api/forecast/model returns the model card."
    - "GET /api/forecast/model and GET /api/forecast/{sku} return the accuracy scorecard, daily forecast, plain-English drivers and simple-average-vs-forecast ordering impact without an AI key; front-end/ is unchanged."
    - "docs/BUSINESS_CASE.md, docs/PRESENTATION_OUTLINE.md, a <=1-page VIBE_CODING_LOG.md and the README all quote the real numbers in models/metrics.json."
  artifacts:
    - path: app.py
      provides: "FastAPI app (moved from back-end/main.py) + /api/forecast/model and /api/forecast/{sku}"
    - path: src/data.py
      provides: "CSV reading (moved from back-end/data_processing.py) + make_demo_sales_history / load_sales_history / festival calendar"
    - path: src/model.py
      provides: "build_features, date_folds, train, load_forecaster, forecast_sku, explain_row, inventory_comparison; `python -m src.model` entry point"
    - path: requirements.txt
      provides: "Exact == pins for every runtime + test dependency"
    - path: models/metrics.json
      provides: "Model card consumed by API and docs"
    - path: tests/test_model.py
      provides: "Leakage, fold, baseline, horizon, SHAP-additivity and API tests"
  key_links:
    - from: app.py
      to: src/model.py
      via: "load_forecaster() (cached) used by both forecast endpoints; /api/forecast/model declared BEFORE /api/forecast/{sku}"
    - from: src/model.py
      to: src/inventory_engine.py
      via: "inventory_comparison calls analyze_item on copies of the item (safety_stock=None, demand_std=sigma)"
    - from: tests/*.py
      to: src/config.py, src/agent.py, app.py
      via: "monkeypatch targets the same module objects the package uses (from src import config / agent as agent_mod; import app as main)"
---

<objective>
Close the capstone brief/rubric gaps in one sequential pass: (A) restructure into the brief-mandated src/data.py, src/model.py, app.py layout with a pinned root requirements.txt, behaviour unchanged; (B) add a production-grade scikit-learn demand-forecasting pipeline (lag/rolling/calendar features, scaling, date-aware TimeSeriesSplit CV, GridSearchCV, SHAP, error analysis vs the flat-average baseline) that feeds safety stock / reorder point through the existing engine and is exposed through FastAPI endpoints (front end untouched); (C) write the business case, Vibe Coding Log, presentation outline and README using the real metrics.

Purpose: Rubric = Business value 30 / Technical rigor 40 / Defence 20 / Engineering 10. The current app has no ML model and the wrong repo layout, so most of the 40 technical points and the repo deliverable are unearned.
Output: src/ package, app.py, requirements.txt, data/sales_history.csv, models/{forecast_model.joblib, metrics.json}, tests/test_model.py, docs/BUSINESS_CASE.md, docs/PRESENTATION_OUTLINE.md, VIBE_CODING_LOG.md, updated README. Three atomic commits.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@README.md
@back-end/config.py
@back-end/main.py
@back-end/tests/conftest.py
@back-end/inventory_engine.py

Ground rules (all tasks):
- cwd for every command = repo root (stockwise-ai/). Python = `~/.venvs/stockwise/bin/python` (scikit-learn 1.9.1, shap 0.53.0, joblib 1.6.0 already installed — no installs needed).
- NEVER read, print, `git add` or commit `.env`. Stage files by explicit path, never `git add -A` / `git add .`.
- Every commit message ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Do NOT modify data/sample_inventory.csv contents (tests depend on exact values). Engine defaults in src/config.py stay unchanged.
<!-- planner-discipline-allow: back-end -->
- Task A must name the old folder to move it; the Task C README gate bans it only in README.md.
- Tracer-first is applied INSIDE Task B (thin end-to-end slice first, then expansion); the 3-task A/B/C decomposition is fixed by the orchestrator.

<interfaces>
Existing engine (unchanged, moves to src/inventory_engine.py):
- analyze_item(item: dict, lead_time_override=None) -> dict with keys incl. avg_daily_demand, safety_stock, safety_stock_method, reorder_point, target_stock, needs_reorder, suggested_qty, estimated_cost, status, coverage_days.
- safety_stock(): supplied value wins; else if demand_std truthy -> ceil(config.SERVICE_Z * demand_std * sqrt(lead_time)); else 2-day default buffer.
- load_csv_path(path) (currently in data_processing, becomes src/data.py) returns list[dict] items with sku, product_name, avg_daily_demand, lead_time_days, unit_cost, current_stock, ...
- app error helper: err(msg, code=400, **extra) -> JSONResponse({"ok": False, "message": ...}); success payloads carry "ok": True. Front end API.call throws when ok === false.

New contracts to create (Task B):
- src/config.py: SALES_HISTORY_CSV = ROOT/"data"/"sales_history.csv"; MODELS_DIR = ROOT/"models"; MODEL_PATH = MODELS_DIR/"forecast_model.joblib"; METRICS_PATH = MODELS_DIR/"metrics.json"; FORECAST_HOLDOUT_DAYS = 56; FORECAST_CV_FOLDS = 5; RANDOM_STATE = 42.
- src/data.py: FESTIVAL_DATES (Diwali: 2023-11-12, 2024-11-01, 2025-10-21, 2026-11-08, 2027-10-29 — approximate, synthetic demo); make_demo_sales_history(items=None, days=730, end="2026-09-30", seed=42) -> DataFrame[date, sku, units_sold, on_promo]; load_sales_history(path=config.SALES_HISTORY_CSV) -> DataFrame with parsed dates sorted by (sku, date).
- src/model.py: NUMERIC_FEATURES, CATEGORICAL_FEATURES=["day_of_week"], FEATURE_GROUPS (lags, rolling, calendar, promo, festival, level), FEATURE_LABELS (plain English); build_features(history) -> DataFrame; date_folds(dates, n_splits) -> list[(train_idx, test_idx)]; train(history, holdout_days=56, n_splits=5, grids=None) -> (bundle: dict, metrics: dict); save(bundle, metrics); load_forecaster() (lru_cached; trains+saves if MODEL_PATH missing); forecast_sku(bundle, history, sku, horizon) -> list[{date, units}]; explain_row(bundle, X_row) -> (base_value, drivers list); inventory_comparison(item, forecast_units, bundle) -> {simple_average:{...}, forecast:{...}}. Do NOT name anything get_model in src/model.py (src/agent.py already owns get_model for the LLM).
- metrics.json top-level keys (API and docs depend on them): trained_through, data {n_skus, n_days, n_rows, holdout_days, cv_folds}, chosen_model {name, params}, cv [ {model, mae_mean, mae_std, rmse_mean, wape_mean, fold_mae[]} ], holdout {<model>: {mae, rmse, wape, mape_nonzero, bias}, flat_average: {...}, seasonal_naive: {...}}, improvement_pct {vs_flat_average, vs_seasonal_naive} (holdout MAE % reduction), feature_selection {ablation [ {group, cv_mae_without, delta_mae} ], lasso_zeroed [], shap_ranking [ {feature, label, mean_abs_shap} ]}, error_analysis {source, by_sku_worst [], by_day_of_week [], promo {}, festival {}, volume_bucket [], bias {}}, residual_sigma {sku: {ml, flat}}, roi_signal {service_level, z, safety_stock_units_flat, safety_stock_units_ml, safety_stock_value_flat, safety_stock_value_ml, value_freed, pct_reduction}. No wall-clock timing in metrics.json (it must be byte-identical across reruns).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task A: Restructure into src/ package + app.py + pinned root requirements.txt (behaviour unchanged)</name>
  <files>src/__init__.py, src/config.py, src/data.py, src/schemas.py, src/session_store.py, src/tools.py, src/agent.py, src/graph.py, src/language_parser.py, src/inventory_engine.py, src/procurement_engine.py, src/explanation_engine.py, app.py, requirements.txt, pytest.ini, data/sample_inventory.csv, tests/conftest.py, tests/test_api.py, tests/test_csv_formats.py, tests/test_graph.py, tests/test_inventory.py, tests/test_language_parser.py, tests/test_procurement.py</files>
  <action>
Pure move/rename per the orchestrator's Task A design; no logic changes.
1. Use `git mv` (preserves history): back-end/data_processing.py -> src/data.py; back-end/main.py -> app.py; every other back-end/*.py (config, schemas, session_store, tools, agent, graph, language_parser, inventory_engine, procurement_engine, explanation_engine) -> src/ with the same name; back-end/tests -> tests; back-end/data -> data. Create empty src/__init__.py.
2. Inside src/, convert every flat sibling import to package-relative form: module imports become `from . import <module>` (keep existing aliases, e.g. the graph module's agent alias `agent_mod` and language_parser alias `lp`), and name imports become `from .<module> import ...`; the data_processing module is now `.data`. Third-party imports untouched.
3. app.py: import the package as `from src import config, graph` and `from src.data import ...`, `from src.explanation_engine import ...`, etc. Update its module docstring run line to: run `~/.venvs/stockwise/bin/uvicorn app:app --port 8000` from the repo root.
4. src/config.py: ROOT = Path(__file__).resolve().parent.parent (repo root); load only ROOT/".env" (the old second back-end/.env load goes away); SAMPLE_CSV = ROOT/"data"/"sample_inventory.csv"; FRONTEND_DIR = ROOT/"front-end". Everything else unchanged.
5. Tests: conftest.py drops the sys.path hack and imports `from src import config` (keeps blanking both API keys). In test files: `import main` becomes `import app as main` (rest of each file unchanged); `import agent as agent_mod` -> `from src import agent as agent_mod`; `import config` -> `from src import config`; `import graph` -> `from src import graph`; the function-local language_parser import in test_api.py -> `from src import language_parser` plus `from src.language_parser import ...`; other module name imports -> `from src.<module> import ...`. `from conftest import A, B, C` stays. Monkeypatches must hit the same module objects the package uses (src.config, src.agent, src.language_parser, app).
6. pytest.ini at repo root: section [pytest] with testpaths = tests and pythonpath = .
7. Root requirements.txt with EXACT pins, one per line: fastapi==0.143.0, uvicorn[standard]==0.54.0, python-multipart==0.0.32, pandas==3.0.6, numpy==2.5.3, pydantic==2.12.5, python-dotenv==1.2.4, langchain==1.4.3, langgraph==1.2.14, langchain-anthropic==1.7.5, langchain-openrouter==0.2.9, scikit-learn==1.9.1, shap==0.53.0, joblib==1.6.0, pytest==9.1.1, httpx==0.28.1 (group with short # comments: web, data/ML, AI, tests). Confirm each against `~/.venvs/stockwise/bin/pip freeze`; if any differs, pin the installed version. `git rm back-end/requirements.txt`, then remove the leftover back-end/ directory (only untracked __pycache__ should remain; `rm -rf back-end`).
8. Run the gate, then commit: `refactor: move back-end into src/ package with app.py entry point and pinned requirements` + trailer. Stage only src/, app.py, tests/, data/, pytest.ini, requirements.txt and the deletions.
  </action>
  <verify>
    <automated>~/.venvs/stockwise/bin/python -m pytest -q 2>&1 | tail -1 | grep -E "^73 passed" && test ! -d back-end && test -f src/__init__.py && test -f src/data.py && test -f app.py && test -f data/sample_inventory.csv && ! grep -rEn '^(import|from) (config|data_processing|schemas|agent|graph|tools|inventory_engine|procurement_engine|explanation_engine|language_parser|session_store)( |\.|$)' src tests app.py && ~/.venvs/stockwise/bin/python -c "import re,importlib.metadata as m;L=[l.strip() for l in open('requirements.txt') if l.strip() and not l.startswith('#')];bad=[l for l in L if (lambda p: len(p)!=2 or m.version(p[0])!=p[1])(re.split(r'(?:\[.*\])?==',l))];print('bad pins:',bad);assert not bad" && ~/.venvs/stockwise/bin/python -c "from fastapi.testclient import TestClient;import app;c=TestClient(app.app);assert c.get('/api/health').json()['ok'];assert c.get('/').status_code==200;assert c.get('/api/sample.csv').status_code==200"</automated>
  </verify>
  <done>73 passed from repo root with plain `python -m pytest -q`; back-end/ gone; app.py serves API + front-end + sample CSV from the new paths; requirements.txt fully == pinned and matches the venv; one refactor commit with the trailer.</done>
</task>

<task type="auto" tdd="true">
  <name>Task B: ML demand-forecasting pipeline (src/model.py) wired into the FastAPI API (no front-end changes), with tests and committed artifacts</name>
  <files>src/config.py, src/data.py, src/model.py, data/sales_history.csv, models/forecast_model.joblib, models/metrics.json, app.py, tests/test_model.py</files>
  <behavior>
    - build_features: for any cutoff date t, features of rows dated <= t are identical whether computed on the full history or on history truncated at t (no look-ahead in lag/rolling/expanding features).
    - date_folds(n_splits=5): every fold has max(train date) < min(test date), no date appears in both, test dates increase fold to fold.
    - On small seasonal synthetic data (3 SKUs, ~300 days, tiny grid, 3 folds, 28-day holdout) the chosen model's holdout MAE is lower than the flat-average baseline's.
    - forecast_sku returns exactly `horizon` consecutive dates starting the day after the last history date, all units >= 0.
    - SHAP: base_value + sum(contributions) ≈ model prediction for the explained row (relative tol 1e-3).
    - API: GET /api/forecast/model returns ok + chosen_model, cv, holdout, improvement_pct, feature_selection, error_analysis, roi_signal; GET /api/forecast/SKU-101 returns ok + history (60), forecast (len = lead time 6 + review 7 = 13), drivers, inventory.simple_average and inventory.forecast; ?horizon=5 returns 5 points; unknown SKU returns 404 with ok false.
  </behavior>
  <action>
Implement exactly the orchestrator's Task B design. Order of work (tracer-first inside the task): first wire the thinnest end-to-end slice — generator -> build_features -> one Ridge pipeline -> forecast_sku -> GET /api/forecast/{sku} — and make one API test pass; then expand to the full candidate set, grid search, ablation, SHAP, error analysis, ROI.

1. Data (src/data.py, src/config.py): add the config constants from <interfaces>. make_demo_sales_history: for each item in data/sample_inventory.csv (via load_csv_path), 730 daily rows ending 2026-09-30, numpy default_rng(seed=42). Mean mu_t = level x weekly[dow] x (1 + 0.10 x t/730 trend) x festival x promo, where level = avg_daily_demand, weekly multipliers Mon..Sun ≈ 0.90, 0.90, 0.95, 1.00, 1.05, 1.25, 1.30 (normalised to mean 1), festival = 1 + 0.6 x linear ramp over the 21 days before each FESTIVAL_DATES entry through 2 days after (peak day before Diwali), on_promo ~ 8% of days per SKU (rng) with x1.4 uplift. Draw units with negative binomial (n=8, p=8/(8+mu)) when mu>0, else 0 (SKU-117 has zero demand: all zeros). Write data/sales_history.csv once (columns date, sku, units_sold, on_promo) and commit it; load_sales_history reads it with parsed dates.
2. Features (src/model.py build_features): sort by (sku, date); per-SKU groupby transforms: lag_1, lag_7, lag_14, lag_28 = shift(k); rolling_mean_7, rolling_mean_28, rolling_std_7 computed on shift(1); sku_mean = shift(1).expanding().mean(); calendar: day_of_week (0-6), month, is_weekend; on_promo; is_festival (inside the festival window) and days_to_festival (days to next FESTIVAL_DATES entry, clipped 0..60). Drop rows with NaN lags (first 28 days per SKU), reset_index. Pipeline factory make_pipeline(estimator, numeric, categorical): ColumnTransformer(StandardScaler on numeric, OneHotEncoder(handle_unknown="ignore", sparse_output=False) on day_of_week — dense output is required for HGB and SHAP; omit the categorical transformer when its list is empty) followed by the estimator.
3. CV (date_folds): TimeSeriesSplit(n_splits) over the sorted unique dates, mapped to row positions with isin, returned as a list of (train_idx, test_idx) numpy arrays — passed as cv= to GridSearchCV and reused everywhere. Holdout = last 56 dates, never seen by CV or tuning.
4. train(): candidates = flat_average (per-SKU mean of training y — what the engine does today), seasonal_naive (prediction = lag_7), Ridge(alpha in [0.1, 1, 10, 100]), Lasso(alpha in [0.01, 0.1, 1], max_iter=10000), HistGradientBoostingRegressor(random_state=42, early_stopping=False; learning_rate [0.05, 0.1], max_depth [4, 8], max_iter [300], l2_regularization [0.0, 1.0]). GridSearchCV(scoring="neg_mean_absolute_error", n_jobs=1, refit=True). Record per-model CV mean ± std MAE, RMSE, WAPE and per-fold MAE (baselines scored on the same folds). Choose the lowest CV MAE learned model; refit on all pre-holdout rows; score holdout for chosen model + both baselines (MAE, RMSE, WAPE = sum|e|/sum y, MAPE on non-zero actuals only, bias = mean(pred - y)); improvement_pct = MAE % reduction vs each baseline. Feature selection: group ablation (CV MAE of the chosen model with each FEATURE_GROUPS group removed; delta vs full), Lasso coefficients that are exactly zero (names mapped to FEATURE_LABELS), SHAP global ranking (mean |SHAP| on holdout rows, one-hot day_of_week columns summed back into one feature). Error analysis on OUT-OF-FOLD CV predictions of the chosen model (manual fold loop with clone() — cross_val_predict rejects non-partition splits; OOF covers the Oct–Nov 2025 festival, the holdout does not): worst-5 SKUs by WAPE (skip zero-sales SKUs), by day of week, promo vs non-promo, festival vs normal, volume buckets (low <2/day, mid 2-10, high >10), over/under bias; source field says "out-of-fold CV predictions". residual_sigma per SKU = std of holdout residuals for the chosen model and for flat_average. roi_signal: per SKU safety stock = ceil(config.SERVICE_Z x sigma x sqrt(lead_time_days)) under each sigma, summed in units and in Rs (x unit_cost); value_freed and pct_reduction. Production bundle = chosen pipeline refit on ALL 730 days + feature lists + labels + residual_sigma + flat means + trained_through + metrics. Round floats to 4 dp and json.dump with sort_keys=True, indent=2 so reruns are byte-identical; cast numpy scalars to float/int.
5. Inference: forecast_sku recursive multi-step — append one future row (units NaN, on_promo 0 = no promotion planned, calendar features from the date), rebuild features for that SKU's series, predict, clip at 0, write the prediction back, repeat for horizon steps. explain_row: TreeExplainer(final estimator) on the transformed row for HGB, LinearExplainer (background = transformed training sample) if a linear model wins; returns base_value and top-6 drivers [{feature, label, contribution}] with day_of_week one-hot aggregated. inventory_comparison: run analyze_item on two COPIES of the item with safety_stock=None — simple_average (avg_daily_demand = flat mean, demand_std = flat sigma) vs forecast (avg_daily_demand = mean of the first lead_time_days forecast values, demand_std = ML sigma); return avg_daily_demand, demand_std, safety_stock, reorder_point, target_stock, suggested_qty, estimated_cost, status for each. Engine and config defaults untouched.
6. `python -m src.model` (if __name__ == "__main__"): load history, train with defaults, save MODEL_PATH + METRICS_PATH, print chosen model, holdout MAE vs baselines, improvement % and elapsed seconds (printed, not stored). Must finish under 60 s — time it; if over, shrink the HGB grid (e.g. max_iter 200) and note it. load_forecaster(): functools.lru_cache; joblib.load MODEL_PATH, or train+save if missing.
7. API (app.py): add a FastAPI lifespan that warms load_forecaster(). Declare GET /api/forecast/model BEFORE GET /api/forecast/{sku} (otherwise "model" is captured as a SKU); both above the StaticFiles mount. /api/forecast/model -> {"ok": True, **metrics}. /api/forecast/{sku}?horizon= (Query, ge=1, le=90; default item lead_time_days + config.REVIEW_PERIOD_DAYS) -> look up the item in the sample inventory (load_csv_path(config.SAMPLE_CSV)) and the history; unknown SKU -> err("...", 404). Response: ok, sku, product_name, horizon, history (last 60 days [{date, units}]), forecast, base_value, drivers, inventory {simple_average, forecast}, assumptions (no promotions planned; demo history is synthetic; sigma from 56-day holdout). ISO date strings, plain floats.
8. NO FRONT-END CHANGES (user instruction, overrides the orchestrator design): do not create, edit, move or delete anything under front-end/. The front end stays HTML/CSS/JS served by FastAPI exactly as it is. The ML forecast is exposed only through the FastAPI endpoints above (also browsable at /docs). Make the endpoint JSON self-explanatory for non-technical readers (plain-English `summary` string and feature `label`s).
9. tests/test_model.py implementing every <behavior> bullet; model tests use make_demo_sales_history on 3 items x 300 days with a tiny grid (n_splits=3, holdout_days=28) so the file runs in a few seconds; API tests use TestClient(app.app) with the committed artifact.
10. Run the test gate, then commit: `feat: ML demand forecasting with time-series CV, tuning, SHAP and error analysis via FastAPI` + trailer. Stage src/, app.py, tests/test_model.py, data/sales_history.csv, models/ explicitly (never front-end/). AFTER the commit run the full <automated> verify (it retrains and uses `git diff --exit-code`, which only proves determinism once the artifacts are tracked). Keep timing out of metrics.json (print it only) so reruns stay byte-identical.
  </action>
  <verify>
    <automated>~/.venvs/stockwise/bin/python -m pytest -q tests/test_model.py && ~/.venvs/stockwise/bin/python -m pytest -q 2>&1 | tail -1 | grep -E "^(79|[89][0-9]|1[0-9][0-9]) passed" && ~/.venvs/stockwise/bin/python -c "import time,subprocess,sys;t=time.time();subprocess.run([sys.executable,'-m','src.model'],check=True);d=time.time()-t;print('train s',round(d,1));assert d<60" && git diff --exit-code models/metrics.json data/sales_history.csv && ~/.venvs/stockwise/bin/python -c "import json;m=json.load(open('models/metrics.json'));assert m['improvement_pct']['vs_flat_average']>0 and m['data']['cv_folds']==5 and m['data']['holdout_days']==56;print(m['chosen_model'],m['improvement_pct'])" && git diff --quiet HEAD~2 -- front-end/</automated>
    <human-check>Run `~/.venvs/stockwise/bin/uvicorn app:app --port 8000`, open http://localhost:8000/#forecast with no AI key: scorecard, chart, drivers and ordering impact render for SKU-101 and update when another product is selected.</human-check>
  </verify>
  <done>All new + original tests pass; retraining reproduces the committed metrics.json and sales_history.csv byte-for-byte (diff check runs after the commit); chosen model beats the flat average on the holdout; both endpoints return the documented keys; front-end/ is unchanged (git diff empty); one feat commit with the trailer.</done>
</task>

<task type="auto">
  <name>Task C: Business case, Vibe Coding Log, presentation outline and README using real metrics</name>
  <files>docs/BUSINESS_CASE.md, docs/PRESENTATION_OUTLINE.md, VIBE_CODING_LOG.md, README.md</files>
  <action>
Read models/metrics.json first; every model number quoted below must come from it (round consistently: percentages as Python f'{round(x)}%', MAE to 2 dp). Label measured-on-synthetic-data figures as such and label every business input as an assumption. Do the ROI arithmetic with a short throwaway python calculation (not committed) so the figures are exact.
1. docs/BUSINESS_CASE.md (per orchestrator Task C): persona — owner / purchase manager of a Rs 5–10 crore/yr FMCG distributor or multi-store retailer in a tier-2 Indian city (~1,000 SKUs, spreadsheets today); problem size; ROI model as a table of explicit assumptions (inventory value, carrying cost % per year, stockout-loss % of revenue, gross margin, manager hours and hourly cost) plus formulas: (a) working capital freed = safety-stock value x roi_signal.pct_reduction, annual saving = freed x carrying cost %; (b) lost-sales recovered = revenue x stockout-loss % x assumed reduction x margin (state that the reduction is tied to the measured improvement_pct and needs a pilot to confirm); (c) hours saved x hourly cost; total annual benefit; pricing (3 SaaS tiers in Rs/month by SKU count); payback period = annual price / monthly benefit; go-to-market (distributor associations, Tally/ERP partners, WhatsApp-led demos, pilot-to-paid); risks and the synthetic-data caveat.
2. VIBE_CODING_LOG.md at repo root, max ~450 words (one page): platforms (Claude Code in VS Code; GSD planner/executor agents; CodeRabbit review; ponytail simplification skill; OpenRouter live model tests); prompt-engineering strategies (locked decisions + verified facts handed to planner, explicit acceptance gates, mocked-LLM tests, number-verify node); agentic workflow (plan -> execute -> atomic commits -> review); what humans owned and verified (scope, formulas, accepting/rejecting review comments, live demo checks, the final numbers); cite 5–8 real commit hashes from `git log --oneline`.
3. docs/PRESENTATION_OUTLINE.md: 15-minute slide-by-slide plan with timings — 5 min executive (opportunity, persona, ROI, pricing/GTM) + 10 min technical (architecture, data + features, feature selection, model optimisation, CV results, holdout vs baselines, SHAP, error analysis, forecast -> reorder point, live demo ~3 min); talking points quoting real metrics; a mermaid flowchart of the architecture (browser -> app.py -> src.data / src.model / inventory + procurement engines / LangGraph agent); a step-by-step live-demo script (existing dashboard screens + the forecast shown via /api/forecast/{sku} in the FastAPI /docs page); Q&A prep table mapping 9 team members to components, each with likely questions + crisp answers covering: TimeSeriesSplit vs KFold, why scale for Ridge/Lasso but not needed for trees, why HGB, how SHAP works (additivity), MAPE with zero-sales days (why WAPE), the safety-stock formula Z x sigma x sqrt(LT), greedy budget allocation, the LLM number-verify step.
4. README.md: update folder structure and the architecture mermaid to the new layout (src/, app.py, data/, models/, tests/, docs/); remove every mention of the old pre-restructure folder (paths, `cd` steps, module names such as data_processing / main:app) and use these commands instead: install `~/.venvs/stockwise/bin/pip install -r requirements.txt`, train `~/.venvs/stockwise/bin/python -m src.model`, run `~/.venvs/stockwise/bin/uvicorn app:app --port 8000`, test `~/.venvs/stockwise/bin/python -m pytest -q` (new total count); add a "Demand forecasting (ML)" section (features, pipeline, CV, tuning, SHAP, error analysis, forecast -> engine, headline metrics); add test_model.py to the tests table; add a rubric -> file map table (Business value -> docs/BUSINESS_CASE.md + existing web app; Technical rigor -> src/model.py, models/metrics.json, tests/test_model.py; Defence -> docs/PRESENTATION_OUTLINE.md; Engineering -> VIBE_CODING_LOG.md, requirements.txt, layout); fix the Limitations / Future improvements / references lines that still say forecasting is missing (the engine default is still the average; ML forecast runs on the demo history).
5. Gate, then commit: `docs: business case, vibe coding log, presentation outline and README for ML + new layout` + trailer, staging only the four files.
  </action>
  <verify>
    <automated>test -f docs/BUSINESS_CASE.md && test -f docs/PRESENTATION_OUTLINE.md && test -f VIBE_CODING_LOG.md && test "$(wc -w < VIBE_CODING_LOG.md)" -le 550 && grep -q 'mermaid' docs/PRESENTATION_OUTLINE.md && ! grep -n 'back-end' README.md && grep -q 'python -m src.model' README.md && grep -q 'uvicorn app:app' README.md && ~/.venvs/stockwise/bin/python -c "import json;m=json.load(open('models/metrics.json'));p=f\"{round(m['improvement_pct']['vs_flat_average'])}%\";bad=[f for f in ('docs/BUSINESS_CASE.md','docs/PRESENTATION_OUTLINE.md','README.md') if p not in open(f).read()];print(p,'missing in',bad);assert not bad" && ~/.venvs/stockwise/bin/python -m pytest -q && S="$(git status --porcelain)" && ! printf '%s\n' "$S" | grep -E '(^| )\.env$'</automated>
  </verify>
  <done>Four docs committed; the headline accuracy improvement from metrics.json appears verbatim in the business case, presentation outline and README; VIBE_CODING_LOG.md fits on one page; README describes only the new layout and commands; tests still green; .env never staged.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser -> API | `sku` path param and `horizon` query param on the new forecast endpoints are untrusted |
| filesystem -> app | models/forecast_model.joblib is unpickled at startup (pickle executes code if tampered) |
| repo -> git remote | .env holds API keys and must never be staged |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ooa-01 | Denial of service | GET /api/forecast/{sku} horizon | medium | mitigate | Query(ge=1, le=90) bound on horizon; recursive loop is O(horizon) on one SKU |
| T-ooa-02 | Tampering / Info disclosure | GET /api/forecast/{sku} sku | low | mitigate | SKU is only looked up against the known sample-inventory/history set; unknown -> 404 err(); never used in file paths |
| T-ooa-03 | Elevation of privilege | load_forecaster joblib.load | medium | mitigate | Only loads the fixed config.MODEL_PATH produced by `python -m src.model` in this repo; no upload/remote model path; documented in README |
| T-ooa-04 | Information disclosure | .env secrets | high | mitigate | Explicit-path staging only; Task C gate fails if .env shows in git status; .env stays in .gitignore |
| T-ooa-05 | Repudiation / integrity of claims | docs ROI numbers | low | mitigate | Gate checks the metrics.json improvement % appears in docs; synthetic-data caveat required |
| T-ooa-SC | Tampering | pip installs | high | accept | No install tasks: scikit-learn 1.9.1, shap 0.53.0, joblib 1.6.0 already installed and verified by the orchestrator; requirements.txt only pins the exact installed versions (checked against importlib.metadata in Task A gate) |
</threat_model>

<verification>
- `~/.venvs/stockwise/bin/python -m pytest -q` from repo root: 73 original + new model tests, 0 failed.
- `~/.venvs/stockwise/bin/python -m src.model` < 60 s, reproduces committed metrics.json; improvement_pct.vs_flat_average > 0.
- `~/.venvs/stockwise/bin/uvicorn app:app --port 8000` serves the dashboard, /api/forecast/model and /api/forecast/SKU-101.
- `git log --oneline -3` shows the refactor, feat and docs commits, each with the Co-Authored-By trailer; nothing pushed; .env untracked.
</verification>

<success_criteria>
- Brief layout satisfied: src/data.py, src/model.py, app.py, pinned requirements.txt, 1-page VIBE_CODING_LOG.md.
- Rubric technical items demonstrably present in code + metrics.json: preprocessing/scaling, feature selection (ablation, Lasso, SHAP), GridSearchCV tuning, date-aware TimeSeriesSplit CV, SHAP explainability, error analysis vs flat-average and seasonal-naive baselines, real-time inference.
- ML forecast feeds safety stock / reorder point / order qty / cost through the unchanged engine, exposed via FastAPI endpoints; front-end/ is byte-for-byte unchanged.
- Business case, presentation outline and README quote real metrics.
</success_criteria>

<output>
Create `.planning/quick/261009-ooa-close-capstone-gaps-ml-demand-forecastin/261009-ooa-SUMMARY.md` when done
</output>
