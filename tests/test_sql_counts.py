"""DuckDB counts disasters, not declaration-area rows, and joins on FIPS."""

from __future__ import annotations

import duckdb
import pandas as pd

from stormledger.transform.sql_loader import execute_script, read_sql


def test_distinct_disaster_count_and_county_sum():
    declarations = pd.DataFrame(
        [
            {
                "disaster_number": 4337,
                "fema_declaration_string": "DR-4337-FL",
                "declaration_type": "DR",
                "declaration_title": "HURRICANE IRMA",
                "incident_begin_date": "2017-09-04",
                "declaration_date": "2017-09-10",
                "ih_program_declared": True,
                "ia_program_declared": False,
                "pa_program_declared": True,
                "hm_program_declared": True,
                "county_fips": "12086",
                "place_code": "99086",
                "designated_area": "Miami-Dade (County)",
                "natural_key": "DR-4337-FL|99086",
            },
            {
                "disaster_number": 4337,
                "fema_declaration_string": "DR-4337-FL",
                "declaration_type": "DR",
                "declaration_title": "HURRICANE IRMA",
                "incident_begin_date": "2017-09-04",
                "declaration_date": "2017-09-10",
                "ih_program_declared": True,
                "ia_program_declared": False,
                "pa_program_declared": True,
                "hm_program_declared": False,
                "county_fips": "12071",
                "place_code": "99071",
                "designated_area": "Lee (County)",
                "natural_key": "DR-4337-FL|99071",
            },
            {
                "disaster_number": 4399,
                "fema_declaration_string": "DR-4399-FL",
                "declaration_type": "DR",
                "declaration_title": "HURRICANE MICHAEL",
                "incident_begin_date": "2018-10-07",
                "declaration_date": "2018-10-11",
                "ih_program_declared": False,
                "ia_program_declared": False,
                "pa_program_declared": True,
                "hm_program_declared": False,
                "county_fips": "00000",
                "place_code": "00000",
                "designated_area": "Statewide",
                "natural_key": "DR-4399-FL|00000",
            },
        ]
    )
    housing = pd.DataFrame(
        [
            {
                "disaster_number": 4337,
                "county_name_key": "MIAMIDADE",
                "county": "Miami-Dade (County)",
                "valid_registrations": 10,
                "total_approved_ihp_amount": 100.0,
            },
            {
                "disaster_number": 4337,
                "county_name_key": "MIAMIDADE",
                "county": "Miami-Dade (County)",
                "valid_registrations": 5,
                "total_approved_ihp_amount": 40.0,
            },
            {
                "disaster_number": 4337,
                "county_name_key": "TAMPARESERVATION",
                "county": "Tampa Reservation",
                "valid_registrations": 3,
                "total_approved_ihp_amount": 9.0,
            },
        ]
    )
    counties = pd.DataFrame(
        [
            {"county_fips": "12086", "county_name": "Miami-Dade", "name_key": "MIAMIDADE", "centroid_lat": 25.6, "centroid_lon": -80.5},
            {"county_fips": "12071", "county_name": "Lee", "name_key": "LEE", "centroid_lat": 26.6, "centroid_lon": -81.8},
        ]
    )
    population = pd.DataFrame(
        [
            {"county_fips": "12086", "population": 100, "reference_date": "2010-04-01", "vintage_id": "census_2010", "source_column": "CENSUS2010POP"},
            {"county_fips": "12071", "population": 50, "reference_date": "2010-04-01", "vintage_id": "census_2010", "source_column": "CENSUS2010POP"},
            {"county_fips": "12086", "population": 200, "reference_date": "2020-04-01", "vintage_id": "census_2020_estimates_base", "source_column": "ESTIMATESBASE2020"},
            {"county_fips": "12071", "population": 80, "reference_date": "2020-04-01", "vintage_id": "census_2020_estimates_base", "source_column": "ESTIMATESBASE2020"},
        ]
    )
    population["reference_date"] = pd.to_datetime(population["reference_date"])
    connection = duckdb.connect()
    connection.register("declarations", declarations)
    connection.register("housing", housing)
    connection.register("counties", counties)
    connection.register("population", population)
    execute_script(connection, read_sql("01_facts.sql"))
    rollup = connection.execute("SELECT * FROM disaster_rollup").fetchone()
    assert rollup[0] == 3  # area rows
    assert rollup[1] == 2  # distinct disasters
    housing_county = connection.execute("SELECT county_fips, owner_valid_registrations FROM housing_county").fetchall()
    assert housing_county == [("12086", 15)]
    unmatched = connection.execute("SELECT county_name_key, owner_valid_registrations FROM housing_unmatched").fetchall()
    assert unmatched == [("TAMPARESERVATION", 3)]
    storms = pd.DataFrame(
        [{"storm_id": "AL112017", "storm_name": "IRMA", "season_year": 2017, "incident_begin": "2017-09-04"}]
    )
    storms["incident_begin"] = pd.to_datetime(storms["incident_begin"])
    link = pd.DataFrame(
        [
            {
                "storm_id": "AL112017",
                "disaster_number": 4337,
                "fema_declaration_string": "DR-4337-FL",
                "declaration_title": "HURRICANE IRMA",
                "match_rule": "test",
            }
        ]
    )
    connection.register("storms", storms)
    connection.register("storm_disaster_link", link)
    execute_script(connection, read_sql("02_model_base.sql"))
    vintage = connection.execute(
        "SELECT DISTINCT population_vintage_id FROM modeling_base"
    ).fetchall()
    assert vintage == [("census_2010",)]
