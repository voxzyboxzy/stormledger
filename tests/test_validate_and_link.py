"""Schema quarantine, duplicate keys, and declaration linking."""

from __future__ import annotations

import pandas as pd

from stormledger.ingest.hurdat2 import StormTrack, TrackPoint
from stormledger.link import hurricane_names, is_tribal_title, link_storms
from stormledger.validate import validate_declarations, validate_housing

from datetime import datetime, timezone


def _declaration(**overrides):
    row = {
        "femaDeclarationString": "DR-4673-FL",
        "disasterNumber": 4673,
        "state": "FL",
        "declarationType": "DR",
        "declarationDate": "2022-09-29T00:00:00.000Z",
        "incidentType": "Hurricane",
        "declarationTitle": "HURRICANE IAN",
        "incidentBeginDate": "2022-09-23T00:00:00.000Z",
        "fipsStateCode": "12",
        "fipsCountyCode": "071",
        "placeCode": "99071",
        "designatedArea": "Lee (County)",
        "ihProgramDeclared": True,
        "iaProgramDeclared": False,
        "paProgramDeclared": True,
        "hmProgramDeclared": True,
        "hash": "abc",
        "id": "should-not-be-the-key",
    }
    row.update(overrides)
    return row


def _housing(**overrides):
    row = {
        "disasterNumber": 4673,
        "state": "FL",
        "county": "Lee (County)",
        "city": "CAPE CORAL",
        "zipCode": "33904",
        "validRegistrations": 10,
        "totalApprovedIhpAmount": 1000.0,
        "approvedForFemaAssistance": 4,
        "id": "api-guid",
    }
    row.update(overrides)
    return row


def test_malformed_and_duplicate_rows_are_quarantined():
    bad = _declaration(placeCode="NOPE", zipCode=None)
    duplicate_a = _declaration(placeCode="99015", fipsCountyCode="015", id="one")
    duplicate_b = _declaration(placeCode="99015", fipsCountyCode="015", id="two", designatedArea="Other")
    valid, quarantined = validate_declarations([_declaration(), bad, duplicate_a, duplicate_b])
    assert list(valid["natural_key"]) == ["DR-4673-FL|99071"]
    reasons = set(quarantined["quarantine_reason"])
    assert "schema_validation_failed" in reasons
    assert "conflicting_duplicate_natural_key" in reasons
    assert "should-not-be-the-key" not in set(valid["natural_key"])


def test_housing_exact_duplicate_keeps_one_copy():
    first = _housing()
    second = _housing()
    valid, quarantined = validate_housing([first, second, _housing(validRegistrations=-1)])
    assert len(valid) == 1
    assert valid.iloc[0]["natural_key"] == "4673|FL|Lee (County)|CAPE CORAL|33904"
    assert set(quarantined["quarantine_reason"]) == {"duplicate_natural_key", "schema_validation_failed"}


def test_hurricane_name_extraction_skips_the_other_storm_in_the_title():
    assert hurricane_names("TROPICAL STORM BONNIE AND HURRICANE CHARLEY") == ["CHARLEY"]
    assert hurricane_names("FL-HURRICANE IRENE-DR-REQ") == ["IRENE"]
    assert is_tribal_title("HURRICANE IRMA - SEMINOLE TRIBE OF FLORIDA")


def _storm(storm_id: str, name: str, year: int) -> StormTrack:
    point = TrackPoint(
        storm_id=storm_id,
        yyyymmdd=f"{year}0915",
        hhmm="1800",
        record_identifier="",
        status="HU",
        lat=26.5,
        lon=-82.0,
        max_wind_kt=100,
        min_pressure_hpa=950,
        radii_34_nm=(10, 10, 10, 10),
        radii_50_nm=(5, 5, 5, 5),
        radii_64_nm=(5, 5, 5, 5),
        valid_time=datetime(year, 9, 15, 18, tzinfo=timezone.utc),
    )
    return StormTrack(storm_id=storm_id, name=name, season_year=year, points=(point,))


def test_linker_prefers_the_dr_with_more_designated_counties_and_skips_tribal():
    disasters = pd.DataFrame(
        [
            {
                "disaster_number": 4337,
                "declaration_type": "DR",
                "declaration_title": "HURRICANE IRMA",
                "incident_begin": "2017-09-04T00:00:00Z",
                "fema_declaration_string": "DR-4337-FL",
            },
            {
                "disaster_number": 4341,
                "declaration_type": "DR",
                "declaration_title": "HURRICANE IRMA - SEMINOLE TRIBE OF FLORIDA",
                "incident_begin": "2017-09-04T00:00:00Z",
                "fema_declaration_string": "DR-4341-FL",
            },
            {
                "disaster_number": 4834,
                "declaration_type": "DR",
                "declaration_title": "HURRICANE MILTON",
                "incident_begin": "2024-10-05T00:00:00Z",
                "fema_declaration_string": "DR-4834-FL",
            },
            {
                "disaster_number": 4844,
                "declaration_type": "DR",
                "declaration_title": "HURRICANE MILTON",
                "incident_begin": "2024-10-05T00:00:00Z",
                "fema_declaration_string": "DR-4844-FL",
            },
            {
                "disaster_number": 3584,
                "declaration_type": "EM",
                "declaration_title": "TROPICAL STORM IAN",
                "incident_begin": "2022-09-23T00:00:00Z",
                "fema_declaration_string": "EM-3584-FL",
            },
        ]
    )
    counts = pd.Series({4337: 49, 4341: 6, 4834: 35, 4844: 7, 3584: 0})
    links, rejected = link_storms(
        disasters,
        counts,
        [_storm("AL112017", "IRMA", 2017), _storm("AL142024", "MILTON", 2024), _storm("AL092022", "IAN", 2022)],
    )
    chosen = {link.storm_id: link.disaster_number for link in links}
    assert chosen["AL112017"] == 4337
    assert chosen["AL142024"] == 4834
    assert "AL092022" not in chosen  # EM only, no DR title match for IAN in this fixture
    assert any(item.disaster_number == 4844 for item in rejected)
