"""Link a HURDAT2 storm to one Florida major-disaster declaration.

A disaster is a `disasterNumber`, not a declaration-area row. Tribal declarations
are kept in the ledger and are not used as the modeling declaration when a
statewide DR for the same hurricane exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from stormledger.geography import haversine_km
from stormledger.ingest.hurdat2 import StormTrack

HURRICANE_NAME = re.compile(r"HURRICANE\s+([A-Z]+)")
FLORIDA_REFERENCE = (27.8, -81.8)


@dataclass(frozen=True)
class StormLink:
    storm_id: str
    storm_name: str
    season_year: int
    disaster_number: int
    fema_declaration_string: str
    declaration_title: str
    incident_begin: str
    match_rule: str
    ih_counties: int


@dataclass(frozen=True)
class RejectedLink:
    storm_id: str
    disaster_number: int
    declaration_title: str
    reason: str


def hurricane_names(title: str) -> list[str]:
    return HURRICANE_NAME.findall(title.upper())


def is_tribal_title(title: str) -> bool:
    text = title.upper()
    return "TRIBE" in text or "TRIBAL" in text or "INDIAN RESERVATION" in text


def _approach_km(storm: StormTrack) -> float:
    return min(haversine_km(FLORIDA_REFERENCE[0], FLORIDA_REFERENCE[1], point.lat, point.lon) for point in storm.points)


def link_storms(
    disasters: pd.DataFrame,
    ih_county_counts: pd.Series,
    storms: list[StormTrack],
) -> tuple[list[StormLink], list[RejectedLink]]:
    """Pick at most one DR per storm.

    `disasters` has one row per disasterNumber. `ih_county_counts` is indexed by
    disaster number and counts Florida counties designated for IA or IH.
    """
    by_name_year: dict[tuple[str, int], list[StormTrack]] = {}
    for storm in storms:
        by_name_year.setdefault((storm.name.upper(), storm.season_year), []).append(storm)

    links: list[StormLink] = []
    rejected: list[RejectedLink] = []
    used_storms: set[str] = set()

    candidates_by_storm: dict[str, list[tuple[int, pd.Series]]] = {}
    for _, row in disasters.iterrows():
        if row["declaration_type"] != "DR":
            continue
        title = str(row["declaration_title"])
        if is_tribal_title(title):
            continue
        year = int(str(row["incident_begin"])[:4])
        for name in hurricane_names(title):
            matches = by_name_year.get((name, year), [])
            if not matches:
                continue
            storm = min(matches, key=_approach_km) if len(matches) > 1 else matches[0]
            designated = ih_county_counts.get(int(row["disaster_number"]), 0)
            candidates_by_storm.setdefault(storm.storm_id, []).append((int(designated), row))

    for storm_id, candidates in candidates_by_storm.items():
        storm = next(item for item in storms if item.storm_id == storm_id)
        ordered = sorted(candidates, key=lambda item: (-item[0], int(item[1]["disaster_number"])))
        chosen_count, chosen = ordered[0]
        rule = (
            "declarationType=DR; title contains HURRICANE {name}; incident year equals "
            "HURDAT2 season; tribal titles excluded; if several DRs match, keep the DR "
            "with the most IA/IH-designated Florida counties"
        ).format(name=storm.name)
        links.append(
            StormLink(
                storm_id=storm.storm_id,
                storm_name=storm.name,
                season_year=storm.season_year,
                disaster_number=int(chosen["disaster_number"]),
                fema_declaration_string=str(chosen["fema_declaration_string"]),
                declaration_title=str(chosen["declaration_title"]),
                incident_begin=str(chosen["incident_begin"]),
                match_rule=rule,
                ih_counties=int(chosen_count),
            )
        )
        used_storms.add(storm.storm_id)
        for _, other in ordered[1:]:
            rejected.append(
                RejectedLink(
                    storm_id=storm.storm_id,
                    disaster_number=int(other["disaster_number"]),
                    declaration_title=str(other["declaration_title"]),
                    reason="Another DR for the same storm has more IA/IH-designated Florida counties",
                )
            )
    return links, rejected
