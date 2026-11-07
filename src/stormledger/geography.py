"""County interior points and spherical distance. No GeoPandas dependency."""

from __future__ import annotations

import math
import re
from typing import Iterable

EARTH_KM = 6371.0


def name_key(name: str) -> str:
    """Compact county-name key used to join FEMA housing county labels to Census names."""
    text = name.upper().strip()
    text = text.replace("(COUNTY)", "")
    text = text.replace(" COUNTY", "")
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = text.replace("-", "")
    text = re.sub(r"\s+", "", text)
    text = text.replace("SAINT", "ST")
    return text


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def _ring_area(ring: list[list[float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        total += x1 * y2 - x2 * y1
    return total / 2


def interior_point(ring: list[list[float]]) -> tuple[float, float]:
    """A point on a scanline through the ring, so coastal counties are not represented by an outside centroid."""
    unique = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not unique:
        raise ValueError("Empty ring")
    lat = sum(point[1] for point in unique) / len(unique)
    crossings: list[float] = []
    closed = unique + [unique[0]]
    for (x1, y1), (x2, y2) in zip(closed, closed[1:]):
        if y1 == y2:
            continue
        if (y1 <= lat < y2) or (y2 <= lat < y1):
            fraction = (lat - y1) / (y2 - y1)
            crossings.append(x1 + fraction * (x2 - x1))
    crossings.sort()
    best_span = -1.0
    best_lon = sum(point[0] for point in unique) / len(unique)
    for index in range(0, len(crossings) - 1, 2):
        span = crossings[index + 1] - crossings[index]
        if span > best_span:
            best_span = span
            best_lon = (crossings[index] + crossings[index + 1]) / 2
    return best_lon, lat


def _polygons(geometry: dict) -> Iterable[list]:
    kind = geometry["type"]
    if kind == "Polygon":
        yield geometry["coordinates"]
    elif kind == "MultiPolygon":
        yield from geometry["coordinates"]
    else:
        raise ValueError(f"Unsupported geometry {kind}")


def feature_interior_point(geometry: dict) -> tuple[float, float]:
    best_area = -1.0
    best_point: tuple[float, float] | None = None
    for polygon in _polygons(geometry):
        exterior = polygon[0]
        area = abs(_ring_area(exterior))
        if area > best_area:
            best_area = area
            best_point = interior_point(exterior)
    if best_point is None:
        raise ValueError("Geometry has no polygons")
    return best_point


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 to point 2, degrees clockwise from north, in [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x)) % 360


def quadrant_index(bearing_deg: float) -> int:
    """NE, SE, SW, NW — the HURDAT2 wind-radii order."""
    if bearing_deg < 90:
        return 0
    if bearing_deg < 180:
        return 1
    if bearing_deg < 270:
        return 2
    return 3


def point_to_segment_km(
    lat: float,
    lon: float,
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> tuple[float, float]:
    """Distance from a point to a track segment, plus the fraction along the segment.

    Uses a local equirectangular projection centered on the county. Accurate
    enough for county-to-track distances around Florida.
    """
    lat0 = math.radians(lat)
    lon0 = math.radians(lon)

    def xy(latitude: float, longitude: float) -> tuple[float, float]:
        x = math.radians(longitude - lon) * math.cos(lat0) * EARTH_KM
        y = math.radians(latitude - lat) * EARTH_KM
        return x, y

    ax, ay = xy(lat_a, lon_a)
    bx, by = xy(lat_b, lon_b)
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return math.hypot(ax, ay), 0.0
    # The county is the projection origin, so the vector from A to the county is -A.
    fraction = max(0.0, min(1.0, (-ax * dx + -ay * dy) / denom))
    closest_x = ax + fraction * dx
    closest_y = ay + fraction * dy
    return math.hypot(closest_x, closest_y), fraction
