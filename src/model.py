"""Demand forecasting: turns daily sales history into a per-product forecast and a safety-stock sigma.

Pipeline: lag / rolling / calendar / promo / festival features -> StandardScaler (numeric) + one-hot (day of week)
-> Ridge, Lasso or HistGradientBoosting, tuned with GridSearchCV on date-aware TimeSeriesSplit folds.
The last FORECAST_HOLDOUT_DAYS days are never used for tuning; they score the chosen model against two baselines:
the flat average (what the inventory engine uses today) and seasonal naive (same weekday last week).
SHAP explains each forecast. The forecast replaces the flat average inside the unchanged inventory engine.

Train:  ~/.venvs/stockwise/bin/python -m src.model     (writes models/forecast_model.joblib + metrics.json)
"""
import json
import math
import time
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Lasso, Ridge
from sklearn.metrics import make_scorer
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import config
from .data import FESTIVAL_DATES, load_sales_history, load_csv_path
from .inventory_engine import analyze_item, ceil

FEATURE_GROUPS = {
    "lags": ["lag_1", "lag_7", "lag_14", "lag_28"],
    "rolling": ["rolling_mean_7", "rolling_mean_28", "rolling_std_7"],
    "level": ["sku_mean"],
    "calendar": ["day_of_week", "month", "is_weekend"],
    "promo": ["on_promo"],
    "festival": ["is_festival", "days_to_festival"],
}
CATEGORICAL_FEATURES = ["day_of_week"]
ALL_FEATURES = [f for g in FEATURE_GROUPS.values() for f in g]
NUMERIC_FEATURES = [f for f in ALL_FEATURES if f not in CATEGORICAL_FEATURES]
FEATURE_LABELS = {
    "lag_1": "Yesterday's sales", "lag_7": "Sales on the same day last week", "lag_14": "Sales 2 weeks ago",
    "lag_28": "Sales 4 weeks ago", "rolling_mean_7": "Last 7-day average", "rolling_mean_28": "Last 28-day average",
    "rolling_std_7": "Recent ups and downs in sales", "sku_mean": "Product's long-run average",
    "day_of_week": "Day of the week", "month": "Month of the year", "is_weekend": "Weekend",
    "on_promo": "Promotion running", "is_festival": "Festival season (Diwali)",
    "days_to_festival": "Days until Diwali",
}
MAX_LAG = 28
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DEFAULT_GRIDS = {
    "ridge": (Ridge(), {"model__alpha": [0.1, 1, 10, 100]}),
    "lasso": (Lasso(max_iter=10000), {"model__alpha": [0.01, 0.1, 1]}),
    "hist_gradient_boosting": (
        HistGradientBoostingRegressor(random_state=config.RANDOM_STATE, early_stopping=False),
        {"model__learning_rate": [0.05, 0.1], "model__max_depth": [4, 8], "model__max_iter": [300],
         "model__l2_regularization": [0.0, 1.0]}),
}


# ---------------------------------------------------------------- features
def calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df["date"]
    day = d.to_numpy().astype("datetime64[D]").astype(int)
    fest = np.sort(pd.to_datetime(FESTIVAL_DATES).to_numpy().astype("datetime64[D]").astype(int))
    nxt = np.searchsorted(fest, day, side="left")                  # next festival on or after each date
    days_to = np.where(nxt < len(fest), fest[np.minimum(nxt, len(fest) - 1)] - day, 999)
    since = day - fest[np.maximum(nxt - 1, 0)]                     # days after the previous festival
    df["day_of_week"] = d.dt.dayofweek
    df["month"] = d.dt.month
    df["is_weekend"] = (d.dt.dayofweek >= 5).astype(int)
    df["is_festival"] = ((days_to <= 21) | ((nxt > 0) & (since <= 2))).astype(int)  # 3 weeks before to 2 days after
    df["days_to_festival"] = np.clip(days_to, 0, 60)
    return df


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    """One row per (sku, date) with lag/rolling features from strictly earlier days only (no look-ahead)."""
    df = history.sort_values(["sku", "date"]).reset_index(drop=True).copy()
    g = df.groupby("sku")["units_sold"]
    for k in (1, 7, 14, 28):
        df[f"lag_{k}"] = g.shift(k)
    past = g.shift(1)
    grp = past.groupby(df["sku"])
    df["rolling_mean_7"] = grp.transform(lambda s: s.rolling(7).mean())
    df["rolling_mean_28"] = grp.transform(lambda s: s.rolling(28).mean())
    df["rolling_std_7"] = grp.transform(lambda s: s.rolling(7).std())
    df["sku_mean"] = grp.transform(lambda s: s.expanding().mean())
    df = calendar_features(df)
    return df.dropna(subset=NUMERIC_FEATURES).reset_index(drop=True)


def make_pipeline(estimator, numeric=NUMERIC_FEATURES, categorical=CATEGORICAL_FEATURES) -> Pipeline:
    steps = [("scale", StandardScaler(), list(numeric))]
    if categorical:
        steps.append(("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False), list(categorical)))
    prep = ColumnTransformer(steps, verbose_feature_names_out=False)
    return Pipeline([("prep", prep), ("model", estimator)])


def date_folds(dates, n_splits: int):
    """Expanding-window folds over unique dates: every test date is later than every training date."""
    dates = pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    uniq = np.sort(dates.unique())
    folds = []
    for tr, te in TimeSeriesSplit(n_splits=n_splits).split(uniq):
        folds.append((np.flatnonzero(dates.isin(uniq[tr]).to_numpy()), np.flatnonzero(dates.isin(uniq[te]).to_numpy())))
    return folds


# ---------------------------------------------------------------- scoring
def wape(y, p):
    return float(np.abs(p - y).sum() / max(y.sum(), 1e-9))


def scores(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    nz = y > 0
    return {"mae": float(np.abs(p - y).mean()), "rmse": float(np.sqrt(((p - y) ** 2).mean())), "wape": wape(y, p),
            "mape_nonzero": float((np.abs(p - y)[nz] / y[nz]).mean()) if nz.any() else 0.0,
            "bias": float((p - y).mean())}


def flat_pred(train: pd.DataFrame, test: pd.DataFrame):
    return test["sku"].map(train.groupby("sku")["units_sold"].mean()).fillna(0.0).to_numpy()


def _group_scores(df, pred) -> dict:
    y = df["units_sold"].to_numpy()
    if not len(y):
        return {"n": 0, "mae": None, "wape": None, "bias": None}
    e = pred - y
    return {"n": int(len(df)), "mae": float(np.abs(e).mean()), "wape": wape(y, pred), "bias": float(e.mean())}


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    return o


def feature_of(col: str) -> str:
    return "day_of_week" if col.startswith("day_of_week_") else col


# ---------------------------------------------------------------- explanations
def _explainer(bundle):
    if "_explainer" not in bundle:
        pipe = bundle["pipeline"]
        est = pipe.named_steps["model"]
        if isinstance(est, HistGradientBoostingRegressor):
            bundle["_explainer"] = shap.TreeExplainer(est)
        else:
            bundle["_explainer"] = shap.LinearExplainer(est, bundle["background"])
    return bundle["_explainer"]


def shap_values(bundle, X: pd.DataFrame):
    """(base_value, contributions DataFrame with one column per original feature, day of week summed)."""
    pipe = bundle["pipeline"]
    Z = pipe.named_steps["prep"].transform(X[bundle["features"]])
    ex = _explainer(bundle)
    sv = np.asarray(ex.shap_values(Z)).reshape(len(X), -1)
    cols = list(pipe.named_steps["prep"].get_feature_names_out())
    out = pd.DataFrame(sv, columns=cols).T.groupby(feature_of).sum().T
    return float(np.ravel(ex.expected_value)[0]), out


def explain_row(bundle, X_row: pd.DataFrame, top: int | None = 6):
    """(base_value, drivers) for one row; drivers = [{feature, label, contribution}] biggest first."""
    base, contrib = shap_values(bundle, X_row.iloc[[0]])
    s = contrib.iloc[0].sort_values(key=abs, ascending=False)
    if top:
        s = s.head(top)
    return base, [{"feature": f, "label": FEATURE_LABELS[f], "contribution": float(v)} for f, v in s.items()]


# ---------------------------------------------------------------- training
def _cv_row(name, res):
    i = res.best_index_
    return {"model": name, "mae_mean": -res.cv_results_["mean_test_mae"][i],
            "mae_std": res.cv_results_["std_test_mae"][i], "rmse_mean": -res.cv_results_["mean_test_rmse"][i],
            "wape_mean": -res.cv_results_["mean_test_wape"][i],
            "fold_mae": [-res.cv_results_[f"split{k}_test_mae"][i] for k in range(res.n_splits_)]}


def train(history: pd.DataFrame, holdout_days: int = config.FORECAST_HOLDOUT_DAYS,
          n_splits: int = config.FORECAST_CV_FOLDS, grids: dict | None = None):
    feats = build_features(history)
    cut = feats["date"].max() - pd.Timedelta(days=holdout_days - 1)
    dev, hold = feats[feats["date"] < cut].reset_index(drop=True), feats[feats["date"] >= cut].reset_index(drop=True)
    y, yh = dev["units_sold"].to_numpy(float), hold["units_sold"].to_numpy(float)
    folds = date_folds(dev["date"], n_splits)
    scoring = {"mae": "neg_mean_absolute_error", "rmse": "neg_root_mean_squared_error",
               "wape": make_scorer(wape, greater_is_better=False)}

    # baselines scored on the same folds
    cv = []
    for name, fn in (("flat_average", lambda tr, te: flat_pred(tr, te)), ("seasonal_naive", lambda tr, te: te["lag_7"].to_numpy())):
        per = [scores(y[te], fn(dev.iloc[tr], dev.iloc[te])) for tr, te in folds]
        cv.append({"model": name, "mae_mean": np.mean([p["mae"] for p in per]), "mae_std": np.std([p["mae"] for p in per]),
                   "rmse_mean": np.mean([p["rmse"] for p in per]), "wape_mean": np.mean([p["wape"] for p in per]),
                   "fold_mae": [p["mae"] for p in per]})
    # tuned models
    cands = DEFAULT_GRIDS if grids is None else {k: (DEFAULT_GRIDS[k][0], g) for k, g in grids.items()}
    fitted = {}
    for name, (est, grid) in cands.items():
        gs = GridSearchCV(make_pipeline(clone(est)), grid, scoring=scoring, refit="mae", cv=folds, n_jobs=1)
        fitted[name] = gs.fit(dev[ALL_FEATURES], y)
        cv.append(_cv_row(name, gs))
    best_name = max(fitted, key=lambda k: fitted[k].best_score_)  # scores are negative MAE
    best = fitted[best_name]
    chosen_est = best.best_estimator_.named_steps["model"]

    # holdout
    holdout = {n: scores(yh, g.best_estimator_.predict(hold[ALL_FEATURES])) for n, g in fitted.items()}
    holdout["flat_average"] = scores(yh, flat_pred(dev, hold))
    holdout["seasonal_naive"] = scores(yh, hold["lag_7"].to_numpy())
    pred_h = best.best_estimator_.predict(hold[ALL_FEATURES])
    imp = {f"vs_{b}": 100 * (holdout[b]["mae"] - holdout[best_name]["mae"]) / holdout[b]["mae"]
           for b in ("flat_average", "seasonal_naive")}

    # feature selection: group ablation, Lasso zeros, SHAP ranking
    base_cv = -best.best_score_
    ablation = []
    for grp, cols in FEATURE_GROUPS.items():
        keep = [f for f in ALL_FEATURES if f not in cols]
        pipe = make_pipeline(clone(chosen_est), [f for f in keep if f in NUMERIC_FEATURES],
                             [f for f in keep if f in CATEGORICAL_FEATURES])
        m = -cross_val_score(pipe, dev[keep], y, cv=folds, scoring="neg_mean_absolute_error").mean()
        ablation.append({"group": grp, "cv_mae_without": m, "delta_mae": m - base_cv})
    lasso_zeroed = []
    if "lasso" in fitted:
        lp = fitted["lasso"].best_estimator_
        coef = pd.Series(lp.named_steps["model"].coef_, index=lp.named_steps["prep"].get_feature_names_out())
        lasso_zeroed = [FEATURE_LABELS[f] for f, c in coef.groupby(feature_of).apply(lambda c: (c == 0).all()).items() if c]
    tmp = {"pipeline": best.best_estimator_, "features": ALL_FEATURES, "background": _background(best.best_estimator_, dev)}
    _, sv = shap_values(tmp, hold)
    ranking = sv.abs().mean().sort_values(ascending=False)
    shap_rank = [{"feature": f, "label": FEATURE_LABELS[f], "mean_abs_shap": v} for f, v in ranking.items()]

    # error analysis on out-of-fold CV predictions (the holdout has no festival; the CV folds do)
    oof_idx, oof = [], []
    for tr, te in folds:
        oof_idx.append(te)
        oof.append(clone(best.best_estimator_).fit(dev.iloc[tr][ALL_FEATURES], y[tr]).predict(dev.iloc[te][ALL_FEATURES]))
    oi, op = np.concatenate(oof_idx), np.clip(np.concatenate(oof), 0, None)
    od = dev.iloc[oi].reset_index(drop=True)
    e = op - od["units_sold"].to_numpy()
    sku_stats = [{"sku": s, **_group_scores(d, op[d.index])} for s, d in od.groupby("sku") if d["units_sold"].sum() > 0]
    sku_mean = od.groupby("sku")["units_sold"].mean()
    bucket = pd.cut(od["sku"].map(sku_mean), [-1, 2, 10, 1e9], labels=["low (<2/day)", "mid (2-10/day)", "high (>10/day)"], right=False)

    def grp(mask):
        return _group_scores(od[mask], op[mask.to_numpy()])
    error_analysis = {
        "source": "out-of-fold CV predictions",
        "by_sku_worst": sorted(sku_stats, key=lambda r: -r["wape"])[:5],
        "by_day_of_week": [{"group": DOW[d], **grp(od["day_of_week"] == d)} for d in range(7)],
        "promo": {n: grp(od["on_promo"] == v) for n, v in (("promo", 1), ("no_promo", 0))},
        "festival": {n: grp(od["is_festival"] == v) for n, v in (("festival", 1), ("normal", 0))},
        "volume_bucket": [{"group": str(b), **grp(bucket == b)} for b in bucket.cat.categories if (bucket == b).any()],
        "bias": {"mean_error": float(e.mean()), "over_forecast_share": float((e > 0).mean()),
                 "under_forecast_share": float((e < 0).mean())},
    }

    # safety-stock sigma from holdout residuals, and the money signal
    res_ml = pd.Series(np.clip(pred_h, 0, None) - yh).groupby(hold["sku"].to_numpy()).std(ddof=0)
    res_flat = pd.Series(flat_pred(dev, hold) - yh).groupby(hold["sku"].to_numpy()).std(ddof=0)
    sigma = {s: {"ml": float(res_ml[s]), "flat": float(res_flat[s])} for s in res_ml.index}
    items = {i["sku"]: i for i in load_csv_path(config.SAMPLE_CSV)}
    ss = {k: [0, 0.0] for k in ("flat", "ml")}
    for s, sg in sigma.items():
        if s in items:
            for k in ss:
                u = ceil(config.SERVICE_Z * sg[k] * math.sqrt(items[s]["lead_time_days"]))
                ss[k][0] += u
                ss[k][1] += u * float(items[s]["unit_cost"])
    roi = {"service_level": 0.95, "z": config.SERVICE_Z,
           "safety_stock_units_flat": ss["flat"][0], "safety_stock_units_ml": ss["ml"][0],
           "safety_stock_value_flat": ss["flat"][1], "safety_stock_value_ml": ss["ml"][1],
           "value_freed": ss["flat"][1] - ss["ml"][1],
           "pct_reduction": 100 * (ss["flat"][1] - ss["ml"][1]) / max(ss["flat"][1], 1e-9)}

    # production model: chosen config refit on every day, including the holdout
    final = clone(best.best_estimator_).fit(feats[ALL_FEATURES], feats["units_sold"].to_numpy(float))
    bundle = {"pipeline": final, "features": ALL_FEATURES, "model_name": best_name,
              "flat_means": feats.groupby("sku")["units_sold"].mean().to_dict(), "residual_sigma": sigma,
              "trained_through": str(history["date"].max().date())}
    bundle["background"] = _background(final, feats)
    metrics = _clean({
        "trained_through": bundle["trained_through"],
        "data": {"n_skus": history["sku"].nunique(), "n_days": history["date"].nunique(), "n_rows": len(history),
                 "holdout_days": holdout_days, "cv_folds": n_splits},
        "chosen_model": {"name": best_name, "params": {k.split("__", 1)[1]: v for k, v in best.best_params_.items()}},
        "cv": cv, "holdout": holdout, "improvement_pct": imp,
        "feature_selection": {"ablation": ablation, "lasso_zeroed": lasso_zeroed, "shap_ranking": shap_rank},
        "error_analysis": error_analysis, "residual_sigma": sigma, "roi_signal": roi})
    return bundle, metrics


def _background(pipe, df):
    """Sample of transformed rows for SHAP's linear explainer (the tree explainer needs none)."""
    if isinstance(pipe.named_steps["model"], HistGradientBoostingRegressor):
        return None
    return pipe.named_steps["prep"].transform(df[ALL_FEATURES].sample(min(300, len(df)), random_state=config.RANDOM_STATE))


def save(bundle, metrics):
    config.MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump({k: v for k, v in bundle.items() if k != "_explainer"}, config.MODEL_PATH)
    config.METRICS_PATH.write_text(json.dumps(metrics, sort_keys=True, indent=2) + "\n")


@lru_cache(maxsize=1)
def load_forecaster() -> dict:
    """The saved model (trained on first use if missing). Only ever reads the fixed MODEL_PATH."""
    if not config.MODEL_PATH.exists():
        save(*train(load_sales_history()))
    return joblib.load(config.MODEL_PATH)


# ---------------------------------------------------------------- inference
def _with_future(history: pd.DataFrame, sku: str, n: int) -> pd.DataFrame:
    h = history[history["sku"] == sku][["date", "sku", "units_sold", "on_promo"]]
    last = h["date"].max()
    fut = pd.DataFrame({"date": pd.date_range(last + pd.Timedelta(days=1), periods=n), "sku": sku,
                        "units_sold": np.nan, "on_promo": 0})  # no promotion planned
    return pd.concat([h, fut], ignore_index=True)


def next_day_features(history: pd.DataFrame, sku: str) -> pd.DataFrame:
    return build_features(_with_future(history, sku, 1)).tail(1)


def forecast_sku(bundle: dict, history: pd.DataFrame, sku: str, horizon: int) -> list[dict]:
    """Recursive multi-step forecast: each predicted day becomes tomorrow's lag."""
    df = _with_future(history, sku, horizon)
    start = len(df) - horizon
    for i in range(start, len(df)):
        row = build_features(df.iloc[: i + 1]).tail(1)
        df.loc[i, "units_sold"] = max(0.0, float(bundle["pipeline"].predict(row[bundle["features"]])[0]))
    return [{"date": d.date().isoformat(), "units": round(float(u), 2)}
            for d, u in zip(df["date"].iloc[start:], df["units_sold"].iloc[start:])]


def inventory_comparison(item: dict, forecast_units: list[float], bundle: dict) -> dict:
    """Same engine, two demand views: flat average vs ML forecast over the lead time."""
    sku, sig = item["sku"], bundle["residual_sigma"].get(item["sku"], {"ml": 0.0, "flat": 0.0})
    lt = max(1, ceil(float(item["lead_time_days"])))
    views = {"simple_average": (bundle["flat_means"].get(sku, 0.0), sig["flat"]),
             "forecast": (float(np.mean(forecast_units[:lt])), sig["ml"])}
    out = {}
    for name, (d, s) in views.items():
        r = analyze_item(dict(item, avg_daily_demand=d, demand_std=s, safety_stock=None))
        out[name] = {"avg_daily_demand": round(d, 2), "demand_std": round(s, 2), **{k: r[k] for k in (
            "safety_stock", "reorder_point", "target_stock", "suggested_qty", "estimated_cost", "status")}}
    return out


if __name__ == "__main__":
    t0 = time.time()
    bundle, metrics = train(load_sales_history())
    save(bundle, metrics)
    h = metrics["holdout"]
    print(f"chosen: {metrics['chosen_model']['name']} {metrics['chosen_model']['params']}")
    print(f"holdout MAE: model {h[metrics['chosen_model']['name']]['mae']} | flat average {h['flat_average']['mae']} "
          f"| seasonal naive {h['seasonal_naive']['mae']}")
    print(f"improvement vs flat average {metrics['improvement_pct']['vs_flat_average']}%, "
          f"vs seasonal naive {metrics['improvement_pct']['vs_seasonal_naive']}%  ({time.time() - t0:.1f}s)")
