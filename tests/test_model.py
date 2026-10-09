import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app as main
from src import config
from src.data import load_csv_path, make_demo_sales_history
from src.model import (ALL_FEATURES, build_features, date_folds, explain_row, forecast_sku, inventory_comparison,
                       next_day_features, train)

TINY = {"ridge": {"model__alpha": [1.0]},
        "hist_gradient_boosting": {"model__learning_rate": [0.1], "model__max_depth": [4], "model__max_iter": [60]}}


@pytest.fixture(scope="module")
def small():
    items = load_csv_path(config.SAMPLE_CSV)[:3]
    hist = make_demo_sales_history(items, days=300)
    bundle, metrics = train(hist, holdout_days=28, n_splits=3, grids=TINY)
    return items, hist, bundle, metrics


def test_features_have_no_lookahead(small):
    _, hist, _, _ = small
    t = hist["date"].max() - pd.Timedelta(days=40)
    full = build_features(hist)
    cut = build_features(hist[hist["date"] <= t])
    a = full[full["date"] <= t].reset_index(drop=True)
    pd.testing.assert_frame_equal(a[["sku", "date"] + ALL_FEATURES], cut[["sku", "date"] + ALL_FEATURES])


def test_date_folds_never_leak(small):
    feats = build_features(small[1])
    folds = date_folds(feats["date"], 5)
    assert len(folds) == 5
    prev_end = None
    for tr, te in folds:
        assert feats["date"].iloc[tr].max() < feats["date"].iloc[te].min()
        assert not set(tr) & set(te)
        if prev_end is not None:
            assert feats["date"].iloc[te].max() > prev_end
        prev_end = feats["date"].iloc[te].max()


def test_model_beats_flat_average_on_holdout(small):
    _, _, _, m = small
    name = m["chosen_model"]["name"]
    assert m["holdout"][name]["mae"] < m["holdout"]["flat_average"]["mae"]
    assert m["improvement_pct"]["vs_flat_average"] > 0
    assert m["data"]["cv_folds"] == 3 and len(m["cv"][2]["fold_mae"]) == 3


def test_forecast_horizon_dates_and_non_negative(small):
    _, hist, bundle, _ = small
    fc = forecast_sku(bundle, hist, "SKU-A", 9)
    dates = pd.to_datetime([p["date"] for p in fc])
    assert len(fc) == 9 and dates[0] == hist["date"].max() + pd.Timedelta(days=1)
    assert (np.diff(dates.to_numpy()) == np.timedelta64(1, "D")).all()
    assert min(p["units"] for p in fc) >= 0


def test_shap_is_additive(small):
    _, hist, bundle, _ = small
    row = next_day_features(hist, "SKU-B")
    base, drivers = explain_row(bundle, row, top=None)
    pred = float(bundle["pipeline"].predict(row[bundle["features"]])[0])
    assert base + sum(d["contribution"] for d in drivers) == pytest.approx(pred, rel=1e-3)


def test_inventory_comparison_uses_engine(small):
    items, hist, bundle, _ = small
    fc = [p["units"] for p in forecast_sku(bundle, hist, "SKU-A", 12)]
    inv = inventory_comparison(items[0], fc, bundle)
    assert set(inv) == {"simple_average", "forecast"}
    assert inv["forecast"]["reorder_point"] > 0


@pytest.fixture
def client():
    return TestClient(main.app)


def test_api_model_card(client):
    r = client.get("/api/forecast/model").json()
    assert r["ok"]
    for k in ("chosen_model", "cv", "holdout", "improvement_pct", "feature_selection", "error_analysis", "roi_signal"):
        assert k in r
    assert r["improvement_pct"]["vs_flat_average"] > 0


def test_api_forecast(client):
    r = client.get("/api/forecast/SKU-101").json()
    assert r["ok"] and len(r["history"]) == 60 and len(r["forecast"]) == 13  # lead time 6 + review 7
    assert r["drivers"] and {"simple_average", "forecast"} <= set(r["inventory"])
    assert len(client.get("/api/forecast/SKU-101?horizon=5").json()["forecast"]) == 5


def test_api_forecast_unknown_sku_and_bad_horizon(client):
    r = client.get("/api/forecast/NOPE")
    assert r.status_code == 404 and r.json()["ok"] is False
    assert client.get("/api/forecast/SKU-101?horizon=91").status_code == 422
