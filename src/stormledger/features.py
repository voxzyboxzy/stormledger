"""Storm-track features for one county. Shared by training and historical replay."""

from __future__ import annotations

import math

from stormledger.geography import (
    haversine_km,
    initial_bearing_deg,
    point_to_segment_km,
    quadrant_index,
)
from stormledger.ingest.hurdat2 import TrackPoint

KM_PER_NM = 1.852


def _radius_nm(radii: tuple[int | None, int | None, int | None, int | None], quadrant: int) -> int | None:
    value = radii[quadrant]
    if value is None:
        return None
    return value


def features_from_points(lat: float, lon: float, points: list[TrackPoint] | tuple[TrackPoint, ...]) -> dict:
    """Features from a (possibly partial) best-track prefix.

    Distance is the minimum distance to any track segment. Wind radii use the
    nearer endpoint of the closest segment, because HURDAT2 publishes radii at
    fixes rather than along segments.
    """
    if not points:
        raise ValueError("Track prefix is empty")
    best_distance = math.inf
    best_fraction = 0.0
    best_index = 0
    best_wind = 0.0
    best_pressure = None
    best_pressure_missing = 1.0
    best_keys: list[str] = [points[0].natural_key]
    radii_missing = 1.0
    inside = {34: 0.0, 50: 0.0, 64: 0.0}

    if len(points) == 1:
        only = points[0]
        best_distance = haversine_km(lat, lon, only.lat, only.lon)
        best_wind = float(only.max_wind_kt or 0)
        best_pressure = only.min_pressure_hpa
        best_pressure_missing = 0.0 if only.min_pressure_hpa is not None else 1.0
        best_keys = [only.natural_key]
        radii_missing, inside = _wind_flags(lat, lon, only, best_distance)
    else:
        for index in range(len(points) - 1):
            start, end = points[index], points[index + 1]
            distance, fraction = point_to_segment_km(lat, lon, start.lat, start.lon, end.lat, end.lon)
            if distance < best_distance:
                best_distance = distance
                best_fraction = fraction
                best_index = index
                wind_a = float(start.max_wind_kt or 0)
                wind_b = float(end.max_wind_kt or 0)
                best_wind = (1 - fraction) * wind_a + fraction * wind_b
                pressure_point = end if fraction >= 0.5 else start
                best_pressure = pressure_point.min_pressure_hpa
                best_pressure_missing = 0.0 if best_pressure is not None else 1.0
                best_keys = [start.natural_key, end.natural_key]
        nearer = points[best_index + 1] if best_fraction >= 0.5 else points[best_index]
        radii_missing, inside = _wind_flags(lat, lon, nearer, best_distance)

    peak_wind = 0.0
    hours = 0.0
    contributing: list[str] = []
    for index, point in enumerate(points):
        distance = haversine_km(lat, lon, point.lat, point.lon)
        wind = float(point.max_wind_kt or 0)
        if distance <= 250:
            peak_wind = max(peak_wind, wind)
        if distance <= 150:
            contributing.append(point.natural_key)
            previous_hours = 0.0
            next_hours = 0.0
            if index > 0:
                previous_hours = (point.valid_time - points[index - 1].valid_time).total_seconds() / 3600
            if index < len(points) - 1:
                next_hours = (points[index + 1].valid_time - point.valid_time).total_seconds() / 3600
            if index == 0 and len(points) > 1:
                hours += next_hours / 2
            elif index == len(points) - 1 and len(points) > 1:
                hours += previous_hours / 2
            else:
                hours += previous_hours / 2 + next_hours / 2
    if peak_wind == 0.0:
        peak_wind = best_wind

    return {
        "min_distance_km": best_distance,
        "closest_wind_kt": best_wind,
        "peak_wind_within_250km": peak_wind,
        "min_pressure_hpa": float(best_pressure) if best_pressure is not None else None,
        "pressure_missing": best_pressure_missing,
        "hours_within_150km": hours,
        "inside_34kt": inside[34],
        "inside_50kt": inside[50],
        "inside_64kt": inside[64],
        "radii_missing": radii_missing,
        "closest_point_keys": best_keys,
        "exposure_point_keys": contributing,
    }


def _wind_flags(lat: float, lon: float, point: TrackPoint, distance_km: float) -> tuple[float, dict[int, float]]:
    bearing = initial_bearing_deg(point.lat, point.lon, lat, lon)
    quadrant = quadrant_index(bearing)
    distance_nm = distance_km / KM_PER_NM
    families = {34: point.radii_34_nm, 50: point.radii_50_nm, 64: point.radii_64_nm}
    missing = 0.0
    inside = {34: 0.0, 50: 0.0, 64: 0.0}
    for threshold, radii in families.items():
        radius = _radius_nm(radii, quadrant)
        if radius is None:
            missing = 1.0
            continue
        if radius > 0 and distance_nm <= radius:
            inside[threshold] = 1.0
    return missing, inside
