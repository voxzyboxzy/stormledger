"""HURDAT2 keys and track features."""

from __future__ import annotations

from datetime import datetime, timezone

from stormledger.features import features_from_points
from stormledger.geography import haversine_km, name_key, quadrant_index
from stormledger.ingest.hurdat2 import TrackPoint, parse_hurdat2

SAMPLE = """AL092022,                IAN,      3,
20220928, 1200,  , HU, 26.0N,  82.7W, 140,  937,  90,  90,  70,  80,  50,  50,  40,  50,  40,  40,  30,  40,  20
20220928, 1905, L, HU, 26.7N,  82.2W, 130,  941,  90,  90,  70,  80,  50,  50,  40,  50,  30,  40,  30,  45,  15
20220929, 0600,  , HU, 27.7N,  81.1W,  65,  985, 120,  80,  40, 100,  40,  20,   0,  40,  30,   0,   0,  30,  20
"""


def _point(**kwargs) -> TrackPoint:
    base = dict(
        storm_id="AL000001",
        yyyymmdd="20220928",
        hhmm="1200",
        record_identifier="",
        status="HU",
        lat=26.0,
        lon=-82.0,
        max_wind_kt=100,
        min_pressure_hpa=950,
        radii_34_nm=(0, 0, 0, 0),
        radii_50_nm=(0, 0, 0, 0),
        radii_64_nm=(0, 0, 0, 0),
        valid_time=datetime(2022, 9, 28, 12, tzinfo=timezone.utc),
    )
    base.update(kwargs)
    return TrackPoint(**base)


def test_parse_hurdat_natural_key_and_landfall():
    storms = parse_hurdat2(SAMPLE)
    assert len(storms) == 1
    storm = storms[0]
    assert storm.storm_id == "AL092022"
    assert storm.name == "IAN"
    assert storm.points[1].natural_key == "AL092022|20220928|1905|L"
    assert storm.points[1].lon < 0
    assert storm.points[0].max_wind_kt == 140


def test_distance_is_near_zero_on_the_segment():
    start = _point(lat=27.0, lon=-82.0, hhmm="1200", valid_time=datetime(2022, 9, 28, 12, tzinfo=timezone.utc))
    end = _point(
        lat=27.0,
        lon=-80.0,
        hhmm="1800",
        max_wind_kt=40,
        valid_time=datetime(2022, 9, 28, 18, tzinfo=timezone.utc),
    )
    features = features_from_points(27.0, -81.0, [start, end])
    assert features["min_distance_km"] < 1.0
    assert 60 < features["closest_wind_kt"] < 80


def test_far_county_is_farther_than_a_nearby_one():
    point = _point(lat=26.5, lon=-82.0)
    near = features_from_points(26.6, -82.1, [point])
    far = features_from_points(30.5, -87.2, [point])
    assert near["min_distance_km"] < far["min_distance_km"]


def test_name_key_and_quadrants():
    assert name_key("Miami-Dade (County)") == name_key("Miami Dade")
    assert name_key("St. Johns") == name_key("Saint Johns")
    assert name_key("DeSoto County") == "DESOTO"
    assert quadrant_index(10) == 0
    assert quadrant_index(100) == 1
    assert quadrant_index(200) == 2
    assert quadrant_index(300) == 3
    # Miami to a point a degree north is about 111 km.
    distance = haversine_km(25.0, -80.0, 26.0, -80.0)
    assert 110 < distance < 112
