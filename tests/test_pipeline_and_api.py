"""Offline rebuild of the bundled ledger, plus the read API."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stormledger.api import create_app
from stormledger.paths import repo_root
from stormledger.pipeline import run_build

ROOT = repo_root()
GOLDEN = json.loads((ROOT / "data" / "curated" / "metrics.json").read_text())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    original = urllib.request.urlopen

    def blocked(*args, **kwargs):
        raise AssertionError("build tried to use the network")

    urllib.request.urlopen = blocked  # type: ignore[assignment]
    output = tmp_path_factory.mktemp("curated")
    try:
        metrics = run_build(ROOT, output)
    finally:
        urllib.request.urlopen = original
    return output, metrics


def test_rebuild_matches_published_backtest_without_network(built):
    _, metrics = built
    assert metrics["published_model"] == GOLDEN["published_model"] == "linear"
    assert metrics["test"]["mae_linear"] == pytest.approx(GOLDEN["test"]["mae_linear"], abs=1e-3)
    assert metrics["test"]["mae_boosted"] == pytest.approx(GOLDEN["test"]["mae_boosted"], abs=1e-3)
    assert metrics["test"]["interval"]["empirical_coverage"] == pytest.approx(
        GOLDEN["test"]["interval"]["empirical_coverage"], abs=1e-4
    )
    assert all(check["passed"] for check in metrics["leakage_checks"])
    assert metrics["n_rows"]["train"] == 248
    assert metrics["n_rows"]["calibration"] == 17
    assert metrics["n_rows"]["test"] == 115
    assert "owner_valid_registrations" not in metrics["feature_list"]


def test_api_traces_a_county_estimate_to_source_keys(built):
    output, _ = built
    client = TestClient(create_app(curated_dir=output, static_dir=output / "missing-static"))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["not_emergency_guidance"] is True
    summary = client.get("/api/summary").json()
    assert summary["distinct_disasters"] < summary["declaration_area_rows"]
    assert summary["distinct_disasters"] == 60
    assert "not a separate disaster" in summary["counting_note"]
    irma = next(storm for storm in summary["storms"] if storm["storm_id"] == "AL112017")
    assert irma["disaster_number"] == 4337
    assert irma["universe_counties"] > 1
    county = client.get("/api/storms/AL092022/counties/12071")
    assert county.status_code == 200
    body = county.json()
    assert body["research_demonstration"] is True
    assert body["sources"]["declaration"]["natural_key"].startswith("DR-4673-FL|")
    assert body["sources"]["housing_rows"]["natural_key_fields"] == [
        "disasterNumber",
        "state",
        "county",
        "city",
        "zipCode",
    ]
    assert body["sources"]["housing_rows"]["row_count"] > 0
    assert body["sources"]["track_points"]["closest_segment_keys"]
    assert body["interval"]["lower"] <= body["estimate"] <= body["interval"]["upper"]
    assert "id" not in body["sources"]["declaration"]
    frames = client.get("/api/storms/AL092022/frames").json()["frames"]
    assert frames[-1]["provisional"] is False
    assert frames[0]["provisional"] is True
    assert abs(frames[-1]["counties"]["12071"]["estimate"] - body["estimate"]) < 0.05
    card = client.get("/api/model-card")
    assert card.status_code == 200
    assert "Not emergency guidance" in card.text
    assert "8181.8" in card.text or "8181.7896" in card.text
