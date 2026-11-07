"""Baseline linear model, boosted tree, and split-conformal intervals.

The published model is chosen on the calibration window only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from stormledger.constants import (
    BOOSTED_CALIBRATION_MARGIN,
    CONFORMAL_COVERAGE,
    FEATURES,
    TARGET,
    TRAIN_END,
    CALIBRATION_END,
)


def assign_split(incident_begin: pd.Timestamp) -> str:
    stamp = pd.Timestamp(incident_begin)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    train_end = pd.Timestamp(TRAIN_END)
    calibration_end = pd.Timestamp(CALIBRATION_END)
    if stamp < train_end:
        return "train"
    if stamp < calibration_end:
        return "calibration"
    return "test"


def choose_published_model(mae_linear: float, mae_boosted: float) -> str:
    if mae_boosted <= BOOSTED_CALIBRATION_MARGIN * mae_linear:
        return "boosted"
    return "linear"


def conformal_radius(abs_residuals: np.ndarray, coverage: float = CONFORMAL_COVERAGE) -> float:
    """Finite-sample split-conformal radius. Level is ceil((n+1)*coverage)/n."""
    residuals = np.asarray(abs_residuals, dtype=float)
    n = int(residuals.size)
    if n == 0:
        raise ValueError("Calibration residuals are empty")
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(np.quantile(residuals, level, method="higher"))


class LogCountModel:
    """Regress log1p(y) and predict on the registration scale, clipped at zero."""

    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, features: pd.DataFrame, target: pd.Series):
        self.estimator.fit(features, np.log1p(target.to_numpy(dtype=float)))
        return self

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        raw = np.expm1(self.estimator.predict(features))
        return np.clip(raw, 0, None)


def _boosted() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        loss="squared_error",
        max_depth=3,
        max_iter=120,
        learning_rate=0.06,
        min_samples_leaf=5,
        l2_regularization=1.0,
        random_state=0,
    )


def _linear() -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            ("linear", LinearRegression()),
        ]
    )


@dataclass
class FittedModels:
    linear: LogCountModel
    boosted: LogCountModel
    published_name: str
    pressure_median: float
    feature_medians: dict[str, float]
    conformal_log_radius: float
    calibration_mae: dict[str, float]
    test_metrics: dict
    permutation_importance: list[dict]


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _medae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.median(np.abs(y_true - y_pred)))


def _prepare(frame: pd.DataFrame, pressure_median: float) -> pd.DataFrame:
    features = frame[FEATURES].copy()
    features["min_pressure_hpa"] = features["min_pressure_hpa"].fillna(pressure_median)
    return features


def fit_models(frame: pd.DataFrame) -> FittedModels:
    """`frame` is the modeling universe: one row per storm-county in IA/IH counties."""
    working = frame.copy()
    working["split"] = working["incident_begin"].map(assign_split)
    train = working[working["split"] == "train"]
    calibration = working[working["split"] == "calibration"]
    test = working[working["split"] == "test"]
    if train.empty or calibration.empty or test.empty:
        raise RuntimeError(
            f"Split is empty (train={len(train)}, calibration={len(calibration)}, test={len(test)})"
        )
    pressure_median = float(train["min_pressure_hpa"].dropna().median())
    feature_medians = {name: float(_prepare(train, pressure_median)[name].median()) for name in FEATURES}

    linear = LogCountModel(_linear()).fit(_prepare(train, pressure_median), train[TARGET])
    boosted = LogCountModel(_boosted()).fit(_prepare(train, pressure_median), train[TARGET])

    def predict_both(split_frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        features = _prepare(split_frame, pressure_median)
        y_true = split_frame[TARGET].to_numpy(dtype=float)
        return y_true, linear.predict(features), boosted.predict(features)

    y_cal, linear_cal, boosted_cal = predict_both(calibration)
    y_test, linear_test, boosted_test = predict_both(test)
    calibration_mae = {"linear": _mae(y_cal, linear_cal), "boosted": _mae(y_cal, boosted_cal)}
    published = choose_published_model(calibration_mae["linear"], calibration_mae["boosted"])
    published_cal = boosted_cal if published == "boosted" else linear_cal
    published_test = boosted_test if published == "boosted" else linear_test
    log_residuals = np.abs(np.log1p(y_cal) - np.log1p(published_cal))
    radius = conformal_radius(log_residuals, CONFORMAL_COVERAGE)
    lower = np.clip(np.expm1(np.log1p(published_test) - radius), 0, None)
    upper = np.expm1(np.log1p(published_test) + radius)
    covered = (y_test >= lower) & (y_test <= upper)
    test_metrics = {
        "n_rows": int(len(test)),
        "n_storms": int(test["storm_id"].nunique()),
        "storms": sorted(test["storm_id"].unique().tolist()),
        "mae_linear": _mae(y_test, linear_test),
        "mae_boosted": _mae(y_test, boosted_test),
        "medae_linear": _medae(y_test, linear_test),
        "medae_boosted": _medae(y_test, boosted_test),
        "mae_log1p_linear": _mae(np.log1p(y_test), np.log1p(linear_test)),
        "mae_log1p_boosted": _mae(np.log1p(y_test), np.log1p(boosted_test)),
        "mae_published": _mae(y_test, published_test),
        "medae_published": _medae(y_test, published_test),
        "interval": {
            "method": "split_conformal_log1p_absolute_residual",
            "nominal_coverage": CONFORMAL_COVERAGE,
            "calibration_n": int(len(calibration)),
            "log_radius": radius,
            "empirical_coverage": float(np.mean(covered)),
            "mean_width": float(np.mean(upper - lower)),
        },
    }
    published_model = boosted if published == "boosted" else linear
    importance = _permutation_importance(published_model, _prepare(calibration, pressure_median), calibration[TARGET])
    return FittedModels(
        linear=linear,
        boosted=boosted,
        published_name=published,
        pressure_median=pressure_median,
        feature_medians=feature_medians,
        conformal_log_radius=radius,
        calibration_mae=calibration_mae,
        test_metrics=test_metrics,
        permutation_importance=importance,
    )


def _permutation_importance(model: LogCountModel, features: pd.DataFrame, target: pd.Series) -> list[dict]:
    """Calibration-set permutation importance. Not computed on the test storms."""
    observed = target.to_numpy(dtype=float)
    baseline = _mae(observed, model.predict(features))
    rng = np.random.default_rng(0)
    rows = []
    for name in features.columns:
        increases = []
        values = features[name].to_numpy().copy()
        for _ in range(8):
            shuffled = features.copy()
            shuffled[name] = rng.permutation(values)
            increases.append(_mae(observed, model.predict(shuffled)) - baseline)
        rows.append({"feature": name, "mean_mae_increase": float(np.mean(increases))})
    rows.sort(key=lambda item: item["mean_mae_increase"], reverse=True)
    return rows


def predict_published(models: FittedModels, frame: pd.DataFrame) -> np.ndarray:
    model = models.boosted if models.published_name == "boosted" else models.linear
    return model.predict(_prepare(frame, models.pressure_median))


def predict_named(models: FittedModels, name: str, frame: pd.DataFrame) -> np.ndarray:
    model = models.boosted if name == "boosted" else models.linear
    return model.predict(_prepare(frame, models.pressure_median))


def interval_bounds(point: np.ndarray, log_radius: float) -> tuple[np.ndarray, np.ndarray]:
    lower = np.clip(np.expm1(np.log1p(point) - log_radius), 0, None)
    upper = np.expm1(np.log1p(point) + log_radius)
    return lower, upper


def ablation_deltas(models: FittedModels, row: pd.DataFrame) -> list[dict]:
    """One-at-a-time replacement of each feature with the training median."""
    base = float(predict_published(models, row)[0])
    rows = []
    for name in FEATURES:
        altered = row.copy()
        altered[name] = models.feature_medians[name]
        if name == "min_pressure_hpa":
            altered["pressure_missing"] = row["pressure_missing"]
        predicted = float(predict_published(models, altered)[0])
        delta = base - predicted
        rows.append(
            {
                "feature": name,
                "value": None if pd.isna(row.iloc[0][name]) else float(row.iloc[0][name]),
                "training_median": models.feature_medians[name],
                "ablation_delta": delta,
                "note": (
                    "Change in the published estimate when this feature is replaced "
                    "by its training-set median. Positive means this county's value "
                    "raises the estimate relative to a typical training county."
                ),
            }
        )
    rows.sort(key=lambda item: abs(item["ablation_delta"]), reverse=True)
    return rows
