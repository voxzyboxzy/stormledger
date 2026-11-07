"""Locked model-selection and conformal rules."""

from __future__ import annotations

import numpy as np

from stormledger.model import choose_published_model, conformal_radius


def test_boosted_model_is_published_only_when_clearly_better_on_calibration():
    assert choose_published_model(100.0, 90.0) == "boosted"
    assert choose_published_model(100.0, 90.1) == "linear"
    assert choose_published_model(100.0, 89.9) == "boosted"
    assert choose_published_model(50.0, 80.0) == "linear"


def test_conformal_radius_uses_the_finite_sample_level():
    residuals = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    # n=5, ceil(6*0.8)/5 = 5/5 = 1, so the radius is the maximum.
    assert conformal_radius(residuals, 0.8) == 10.0
    # A looser check: the radius is one of the residuals.
    wider = np.arange(1, 21, dtype=float)
    radius = conformal_radius(wider, 0.8)
    assert radius in set(wider)
    assert radius >= np.quantile(wider, 0.8)
