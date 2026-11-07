"""Offline build: snapshots -> validation -> DuckDB -> model -> provenance artifacts."""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd

from stormledger.constants import (
    BANNED_FEATURES,
    CALIBRATION_END,
    CONFORMAL_COVERAGE,
    DECLARATION_ENTITY,
    FEATURED_STORM_IDS,
    FEATURES,
    HOUSING_ENTITY,
    METHODOLOGY_ID,
    MODEL_VERSION,
    RESEARCH_BANNER,
    TARGET,
    TRAIN_END,
)
from stormledger.features import features_from_points
from stormledger.geography import feature_interior_point, name_key
from stormledger.hashutil import estimate_id
from stormledger.ingest.hurdat2 import duplicate_track_keys, load_hurdat_snapshot
from stormledger.ingest.openfema import load_snapshot_records
from stormledger.ingest.reference import load_county_geojson, load_population_snapshot
from stormledger.link import RejectedLink, link_storms
from stormledger.model import (
    ablation_deltas,
    assign_split,
    fit_models,
    interval_bounds,
    predict_named,
    predict_published,
)
from stormledger.paths import repo_root
from stormledger.transform.sql_loader import execute_script, read_sql
from stormledger.validate import validate_declarations, validate_housing


class BuildError(RuntimeError):
    pass


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            return str(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, payload, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_jsonable(payload), indent=indent)
    path.write_text(text + "\n")


def _r(value, digits: int) -> float:
    return round(float(value), digits)


def _snapshot_paths(root: Path) -> dict[str, Path]:
    manifest = json.loads((root / "data" / "manifest.json").read_text())
    return {key: root / value for key, value in manifest["snapshots"].items()}


def _counties_frame(geojson: dict) -> pd.DataFrame:
    rows = []
    for feature in geojson["features"]:
        props = feature["properties"]
        fips = str(feature.get("id") or f"{props['STATE']}{props['COUNTY']}")
        lon, lat = feature_interior_point(feature["geometry"])
        rows.append(
            {
                "county_fips": fips,
                "county_name": props["NAME"],
                "name_key": name_key(props["NAME"]),
                "centroid_lat": lat,
                "centroid_lon": lon,
            }
        )
    frame = pd.DataFrame(rows)
    if frame["county_fips"].duplicated().any() or frame["name_key"].duplicated().any():
        raise BuildError("County FIPS or name keys are not unique")
    if len(frame) != 67:
        raise BuildError(f"Expected 67 Florida counties, found {len(frame)}")
    return frame


def _declaration_frame(valid: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "disaster_number": valid["disasterNumber"].astype(int),
            "fema_declaration_string": valid["femaDeclarationString"].astype(str),
            "declaration_type": valid["declarationType"].astype(str),
            "declaration_title": valid["declarationTitle"].astype(str),
            "incident_begin_date": pd.to_datetime(valid["incidentBeginDate"], utc=True),
            "declaration_date": pd.to_datetime(valid["declarationDate"], utc=True),
            "ih_program_declared": valid["ihProgramDeclared"].astype(bool),
            "ia_program_declared": valid["iaProgramDeclared"].astype(bool),
            "pa_program_declared": valid["paProgramDeclared"].astype(bool),
            "hm_program_declared": valid["hmProgramDeclared"].astype(bool),
            "county_fips": valid["fipsStateCode"].astype(str) + valid["fipsCountyCode"].astype(str),
            "place_code": valid["placeCode"].astype(str),
            "designated_area": valid["designatedArea"].astype(str),
            "natural_key": valid["natural_key"].astype(str),
            "source_hash": valid["hash"].astype(str) if "hash" in valid.columns else "",
        }
    )
    strings = frame.groupby("disaster_number")["fema_declaration_string"].nunique()
    if (strings > 1).any():
        raise BuildError("A disasterNumber maps to more than one femaDeclarationString")
    return frame


def _housing_frame(valid: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "disaster_number": valid["disasterNumber"].astype(int),
            "state": valid["state"].astype(str),
            "county": valid["county"].astype(str),
            "county_name_key": valid["county"].map(name_key),
            "city": valid["city"].astype(str),
            "zip_code": valid["zipCode"].astype(str),
            "valid_registrations": valid["validRegistrations"].astype(int),
            "total_approved_ihp_amount": valid["totalApprovedIhpAmount"].astype(float),
            "approved_for_fema_assistance": valid["approvedForFemaAssistance"].astype(int),
            "natural_key": valid["natural_key"].astype(str),
            "source_api_id": valid["id"].astype(str) if "id" in valid.columns else "",
        }
    )


def _population_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["reference_date"] = pd.to_datetime(frame["reference_date"])
    frame["population"] = frame["population"].astype(int)
    return frame[
        ["county_fips", "population", "reference_date", "vintage_id", "source_column"]
    ]


def _attach_features(base: pd.DataFrame, points_by_storm: dict) -> pd.DataFrame:
    pieces = []
    for storm_id, group in base.groupby("storm_id", sort=False):
        points = points_by_storm[storm_id]
        feature_rows = [
            features_from_points(lat, lon, points)
            for lat, lon in zip(group["centroid_lat"], group["centroid_lon"])
        ]
        features = pd.DataFrame(feature_rows, index=group.index)
        features["log_population"] = np.log(group["population"].astype(float))
        pieces.append(pd.concat([group, features], axis=1))
    return pd.concat(pieces, ignore_index=True)


def _leakage_checks(featured: pd.DataFrame, universe: pd.DataFrame) -> list[dict]:
    checks = []
    splits = {name: universe[universe["split"] == name] for name in ("train", "calibration", "test")}
    train_max = splits["train"]["incident_begin"].max()
    cal_min = splits["calibration"]["incident_begin"].min()
    cal_max = splits["calibration"]["incident_begin"].max()
    test_min = splits["test"]["incident_begin"].min()
    checks.append(
        {
            "name": "time_separation",
            "passed": bool(train_max < cal_min <= cal_max < test_min),
            "detail": {
                "train_max": str(train_max),
                "calibration_min": str(cal_min),
                "calibration_max": str(cal_max),
                "test_min": str(test_min),
            },
        }
    )
    shared = set(splits["train"]["storm_id"]) & set(splits["test"]["storm_id"])
    shared |= set(splits["calibration"]["storm_id"]) & set(splits["test"]["storm_id"])
    shared |= set(splits["train"]["storm_id"]) & set(splits["calibration"]["storm_id"])
    checks.append({"name": "storms_do_not_cross_splits", "passed": not shared, "detail": sorted(shared)})
    banned_present = sorted(set(FEATURES) & BANNED_FEATURES)
    checks.append({"name": "features_exclude_target_and_identifiers", "passed": not banned_present, "detail": banned_present})
    checks.append(
        {
            "name": "population_reference_precedes_incident",
            "passed": bool((featured["population_reference_date"] < featured["incident_begin"]).all()),
            "detail": "Census reference date is strictly before incident begin for every storm-county row",
        }
    )
    irma = featured[featured["storm_id"] == "AL112017"]["population_vintage_id"].unique().tolist()
    ian = featured[featured["storm_id"] == "AL092022"]["population_vintage_id"].unique().tolist()
    checks.append({"name": "irma_uses_2010_census", "passed": irma == ["census_2010"], "detail": irma})
    checks.append(
        {
            "name": "ian_uses_2020_census",
            "passed": ian == ["census_2020_estimates_base"],
            "detail": ian,
        }
    )
    return checks


def _status_label(status: str) -> str:
    return {
        "HU": "Hurricane",
        "TS": "Tropical storm",
        "TD": "Tropical depression",
        "EX": "Extratropical",
        "SS": "Subtropical storm",
        "SD": "Subtropical depression",
        "LO": "Low",
        "WV": "Tropical wave",
        "DB": "Disturbance",
    }.get(status, status)


def _model_card(metrics: dict, quality: dict) -> str:
    test = metrics["test"]
    interval = test["interval"]
    lines = [
        "# StormLedger model card",
        "",
        f"> {RESEARCH_BANNER}",
        "",
        "## What this estimates",
        "",
        "The published number is a retrospective estimate of **owner valid registrations**",
        "for one Florida county in one hurricane's major disaster declaration.",
        "",
        "- Source dataset: OpenFEMA `HousingAssistanceOwners`",
        "- Source field: `validRegistrations`",
        "- Geography: summed from the published zip/city rows to a Census county FIPS",
        "- Universe: Florida counties designated for Individual Assistance or the Individuals and Households program on the linked DR",
        "- Counties with no owner-assistance rows are treated as zero inside that universe",
        "- This is not renter assistance, not all IA applicants, and not a forecast",
        "",
        "## How a storm is linked",
        "",
        "A HURDAT2 storm links to a FEMA `disasterNumber` when the declaration is a DR,",
        "the title contains `HURRICANE <NAME>`, the incident year equals the HURDAT2 season,",
        "and the title is not a tribal declaration. If two DRs match, the one with more",
        "IA/IH-designated Florida counties is the modeling declaration. The other disaster",
        "stays in the declaration ledger.",
        "",
        "## Splits",
        "",
        f"- Train: incident begin before {TRAIN_END}",
        f"- Calibration: incident begin from {TRAIN_END} until before {CALIBRATION_END}",
        f"- Test: incident begin on or after {CALIBRATION_END}",
        "",
        "The published model is chosen on calibration mean absolute error only.",
        f"The boosted tree is published when its calibration MAE is at most {metrics['selection_margin']} times the linear MAE.",
        "Otherwise the linear model is published. Test storms are scored once and are not used to choose.",
        "",
        f"Published model: **{metrics['published_model']}**.",
        "",
        "## Test results",
        "",
        "| Model | Test MAE (registrations) | Test median AE | Test MAE on log1p |",
        "| --- | ---: | ---: | ---: |",
        f"| Linear baseline | {test['mae_linear']:.1f} | {test['medae_linear']:.1f} | {test['mae_log1p_linear']:.3f} |",
        f"| Boosted tree | {test['mae_boosted']:.1f} | {test['medae_boosted']:.1f} | {test['mae_log1p_boosted']:.3f} |",
        f"| Published ({metrics['published_model']}) | {test['mae_published']:.1f} | {test['medae_published']:.1f} | |",
        "",
        f"Calibration MAE: linear {metrics['calibration_mae']['linear']:.1f}, boosted {metrics['calibration_mae']['boosted']:.1f}.",
        f"Test rows: {test['n_rows']} counties across {test['n_storms']} storms ({', '.join(test['storms'])}).",
        "",
        "## Uncertainty",
        "",
        "The 80% interval is split conformal on the calibration storms. Residuals are absolute",
        "errors of log1p(registrations). The radius uses the finite-sample level",
        "`ceil((n+1) * 0.80) / n` and is transformed back with expm1, so the interval is multiplicative.",
        "",
        f"- Calibration rows: {interval['calibration_n']}",
        f"- Nominal coverage: {interval['nominal_coverage']:.0%}",
        f"- Empirical coverage on the test storms: {interval['empirical_coverage']:.1%}",
        f"- Mean interval width on the test storms: {interval['mean_width']:.0f} registrations",
        "",
        "On this bundle the empirical test coverage is below the nominal 80%. The calibration",
        "storms (Michael 2018 and Sally 2020, 17 county rows) are smaller events than Ian,",
        "Helene, and Milton, so a radius fit on that window is too narrow. That miss is a",
        "result, not a number that was adjusted after seeing the test storms.",
        "",
        "Standardized linear coefficients are associations on the log1p scale after scaling.",
        "Wind, pressure, and distance move together, so a single coefficient sign is not a",
        "physical claim. Local explanations use ablation, not those coefficients.",
        "",
        "## Explanation",
        "",
        "Each county estimate stores an ablation: the change in the published prediction when",
        "one feature is replaced by its training-set median. That is a local explanation of this",
        "fitted model, not a causal effect of wind or distance.",
        "",
        "Global permutation importance is computed on the calibration window, not the test storms.",
        "",
        "## Provenance",
        "",
        "Every estimate names the declaration natural key (`femaDeclarationString|placeCode`),",
        "the housing natural keys (`disasterNumber|state|county|city|zipCode`), the HURDAT2 fix",
        "keys (`storm_id|YYYYMMDD|HHMM|record_identifier`), and the Census vintage. OpenFEMA `id`",
        "values are API-assigned and are not used as keys.",
        "",
        f"Declaration-area rows in the snapshot: {quality['declaration_area_rows']}.",
        f"Distinct disasters (`disasterNumber`): {quality['distinct_disasters']}.",
        "",
        "## Leakage checks",
        "",
        "| Check | Passed |",
        "| --- | --- |",
    ]
    for check in metrics["leakage_checks"]:
        lines.append(f"| {check['name']} | {check['passed']} |")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Best-track positions are a post-storm reanalysis. Replay frames are not real-time forecasts.",
            "- Owner registrations omit renters and are not the full Individuals and Households caseload.",
            "- Treating a missing housing row as zero is an assumption. Tribal geographies that do not join to a county FIPS are excluded and counted in the quality report.",
            "- County interior points are geometric, not population-weighted.",
            "- Storm-county rows are not independent, and there are few storms.",
            "- Estimates outside IA/IH-designated counties are extrapolations.",
            "- Do not use these numbers for emergency decisions, insurance pricing, or assistance allocation.",
            "",
        ]
    )
    return "\n".join(lines)


def run_build(root: Path | None = None, output_dir: Path | None = None) -> dict:
    root = root or repo_root()
    output_dir = output_dir or (root / "data" / "curated")
    output_dir.mkdir(parents=True, exist_ok=True)
    snaps = _snapshot_paths(root)

    declarations_raw, declaration_meta = load_snapshot_records(snaps["disaster_declarations_summaries"], DECLARATION_ENTITY)
    housing_raw, housing_meta = load_snapshot_records(snaps["housing_assistance_owners"], HOUSING_ENTITY)
    decl_valid, decl_quarantine = validate_declarations(declarations_raw)
    housing_valid, housing_quarantine = validate_housing(housing_raw)
    geojson, geo_meta = load_county_geojson(snaps["florida_counties"])
    population_rows, population_meta = load_population_snapshot(snaps["census_county_population"])
    storms, hurdat_meta = load_hurdat_snapshot(snaps["hurdat2_atlantic"])
    duplicate_keys = duplicate_track_keys(storms)
    if duplicate_keys:
        raise BuildError(f"HURDAT2 natural keys are not unique, for example {duplicate_keys[:3]}")

    counties = _counties_frame(geojson)
    declarations = _declaration_frame(decl_valid)
    housing = _housing_frame(housing_valid)
    population = _population_frame(population_rows)

    connection = duckdb.connect()
    connection.register("declarations", declarations)
    connection.register("housing", housing)
    connection.register("counties", counties)
    connection.register("population", population)
    execute_script(connection, read_sql("01_facts.sql"))

    disaster_table = connection.execute("SELECT * FROM disasters").df()
    disaster_table["incident_begin"] = pd.to_datetime(disaster_table["incident_begin"], utc=True)
    ih_counts = connection.execute(
        """
        SELECT disaster_number,
               SUM(CASE WHEN ih_program_declared OR ia_program_declared THEN 1 ELSE 0 END)::BIGINT AS ih_counties
        FROM county_designations
        GROUP BY disaster_number
        """
    ).df()
    ih_series = ih_counts.set_index("disaster_number")["ih_counties"]
    links, rejected = link_storms(disaster_table, ih_series, storms)
    # Census vintages begin on 2000-04-01. Earlier storms stay in the declaration
    # ledger, but they are not modeled because no pre-incident population exists.
    modeled_links = []
    for link in links:
        if pd.Timestamp(link.incident_begin) < pd.Timestamp("2000-04-02", tz="UTC"):
            rejected.append(
                RejectedLink(
                    storm_id=link.storm_id,
                    disaster_number=link.disaster_number,
                    declaration_title=link.declaration_title,
                    reason="Incident begins before the April 1, 2000 Census, so there is no leakage-safe population vintage",
                )
            )
        else:
            modeled_links.append(link)
    links = modeled_links
    linked_ids = {link.storm_id for link in links}
    missing = [storm_id for storm_id in FEATURED_STORM_IDS if storm_id not in linked_ids]
    if missing:
        raise BuildError(f"Featured storms did not link to a DR: {missing}")

    link_frame = pd.DataFrame([link.__dict__ for link in links])
    storm_frame = pd.DataFrame(
        {
            "storm_id": link_frame["storm_id"],
            "storm_name": link_frame["storm_name"],
            "season_year": link_frame["season_year"].astype(int),
            "incident_begin": pd.to_datetime(link_frame["incident_begin"], utc=True),
        }
    )
    connection.register("storms", storm_frame)
    connection.register(
        "storm_disaster_link",
        link_frame[
            [
                "storm_id",
                "disaster_number",
                "fema_declaration_string",
                "declaration_title",
                "match_rule",
            ]
        ],
    )
    execute_script(connection, read_sql("02_model_base.sql"))
    base = connection.execute("SELECT * FROM modeling_base").df()
    base["incident_begin"] = pd.to_datetime(base["incident_begin"], utc=True)
    base["population_reference_date"] = pd.to_datetime(base["population_reference_date"], utc=True)
    rollup = connection.execute("SELECT * FROM disaster_rollup").df().iloc[0].to_dict()
    disasters_out = connection.execute(
        """
        SELECT disaster_number, fema_declaration_string, declaration_type, declaration_title,
               incident_begin, area_rows, ih_area_rows, ia_area_rows, pa_area_rows
        FROM disasters
        ORDER BY incident_begin, disaster_number
        """
    ).df()
    unmatched = connection.execute("SELECT * FROM housing_unmatched").df()
    non_county = connection.execute("SELECT COUNT(*) AS rows FROM non_county_designations").fetchone()[0]

    points_by_storm = {storm.storm_id: storm.points for storm in storms}
    featured = _attach_features(base, points_by_storm)
    if featured["population"].isna().any():
        raise BuildError("A storm-county row is missing a pre-incident Census population")
    universe = featured[featured["in_modeling_universe"]].copy()
    universe["split"] = universe["incident_begin"].map(assign_split)
    featured["split"] = featured["incident_begin"].map(assign_split)
    models = fit_models(universe)
    checks = _leakage_checks(featured, universe)
    failed = [check["name"] for check in checks if not check["passed"]]
    if failed:
        raise BuildError(f"Leakage checks failed: {failed}")

    # Provenance must reproduce the housing sum from the listed source keys.
    housing_joined = housing.merge(
        counties[["name_key", "county_fips"]],
        left_on="county_name_key",
        right_on="name_key",
        how="inner",
    )
    housing_joined["disaster_number"] = housing_joined["disaster_number"].astype(int)
    housing_joined["county_fips"] = housing_joined["county_fips"].astype(str)
    housing_groups = housing_joined.groupby(["disaster_number", "county_fips"], sort=False)
    keys_by_pair = housing_groups["natural_key"].apply(list).to_dict()
    sum_by_pair = housing_groups["valid_registrations"].sum().to_dict()

    prepared = featured.copy()
    for column in FEATURES:
        if column not in prepared.columns:
            raise BuildError(f"Missing feature {column}")
    point = predict_published(models, prepared)
    linear_point = predict_named(models, "linear", prepared)
    boosted_point = predict_named(models, "boosted", prepared)
    lower, upper = interval_bounds(point, models.conformal_log_radius)
    prepared = prepared.reset_index(drop=True)
    prepared["estimate"] = point
    prepared["linear_estimate"] = linear_point
    prepared["boosted_estimate"] = boosted_point
    prepared["lower"] = lower
    prepared["upper"] = upper

    audit_mismatches = []
    for row in prepared.itertuples():
        pair = (int(row.disaster_number), row.county_fips)
        summed = int(sum_by_pair.get(pair, 0))
        if summed != int(row.owner_valid_registrations):
            audit_mismatches.append((pair, summed, int(row.owner_valid_registrations)))
    if audit_mismatches:
        raise BuildError(f"Housing provenance sums do not match county totals, for example {audit_mismatches[:3]}")

    # Batch ablations for the final best-track estimate.
    ablations = {name: np.zeros(len(prepared)) for name in FEATURES}
    for name in FEATURES:
        altered = prepared.copy()
        altered[name] = models.feature_medians[name]
        ablations[name] = predict_published(models, altered)

    snapshot_ids = {
        "declarations": declaration_meta["retrieved_at"] + ":" + declaration_meta["pages"][0]["sha256"][:12],
        "housing": housing_meta["retrieved_at"] + ":" + housing_meta["pages"][0]["sha256"][:12],
        "hurdat2": hurdat_meta["retrieved_at"] + ":" + hurdat_meta["sha256"][:12],
        "population": population_meta["retrieved_at"],
        "counties": geo_meta["retrieved_at"] + ":" + geo_meta["extract_sha256"][:12],
    }

    provenance_dir = output_dir / "provenance"
    frames_dir = output_dir / "frames"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    storm_payloads = []
    for link in sorted(links, key=lambda item: item.incident_begin):
        storm_rows = prepared[prepared["storm_id"] == link.storm_id].reset_index(drop=True)
        split = assign_split(pd.Timestamp(link.incident_begin))
        points = list(points_by_storm[link.storm_id])
        frames = []
        for index in range(len(points)):
            prefix = points[: index + 1]
            feature_rows = [
                features_from_points(lat, lon, prefix)
                for lat, lon in zip(storm_rows["centroid_lat"], storm_rows["centroid_lon"])
            ]
            frame_features = storm_rows[FEATURES].copy()
            for column in FEATURES:
                if column == "log_population":
                    continue
                if column == "min_pressure_hpa":
                    frame_features[column] = [row["min_pressure_hpa"] for row in feature_rows]
                elif column in feature_rows[0]:
                    frame_features[column] = [row[column] for row in feature_rows]
            frame_features["log_population"] = storm_rows["log_population"].to_numpy()
            estimate = predict_published(models, frame_features)
            bound_low, bound_high = interval_bounds(estimate, models.conformal_log_radius)
            counties_payload = {}
            for row_index, county in storm_rows.iterrows():
                counties_payload[county.county_fips] = {
                    "estimate": _r(estimate[row_index], 2),
                    "lower": _r(bound_low[row_index], 2),
                    "upper": _r(bound_high[row_index], 2),
                    "observed": int(county.owner_valid_registrations),
                    "in_universe": bool(county.in_modeling_universe),
                    "distance_km": _r(feature_rows[row_index]["min_distance_km"], 2),
                    "wind_kt": _r(feature_rows[row_index]["closest_wind_kt"], 1),
                }
            current = prefix[-1]
            frames.append(
                {
                    "index": index,
                    "valid_time": current.valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": current.status,
                    "status_label": _status_label(current.status),
                    "wind_kt": current.max_wind_kt,
                    "position": [round(current.lon, 3), round(current.lat, 3)],
                    "track": [[round(point.lon, 3), round(point.lat, 3)] for point in prefix],
                    "track_point_key": current.natural_key,
                    "provisional": index != len(points) - 1,
                    "counties": counties_payload,
                }
            )
        final = frames[-1]
        for _, county in storm_rows.iterrows():
            final_county = final["counties"][county.county_fips]
            if abs(final_county["estimate"] - _r(county.estimate, 2)) > 0.05:
                raise BuildError(
                    f"Final replay frame does not match the published estimate for {link.storm_id} {county.county_fips}"
                )
        _write_json(frames_dir / f"{link.storm_id}.json", {"storm_id": link.storm_id, "frames": frames}, indent=None)

        county_payloads = {}
        prepared_positions = {
            str(row.county_fips): int(idx)
            for idx, row in prepared.loc[prepared["storm_id"] == link.storm_id].iterrows()
        }
        for _, county in storm_rows.iterrows():
            pair = (int(county.disaster_number), str(county.county_fips))
            position = prepared_positions[str(county.county_fips)]
            explanation = []
            for name in FEATURES:
                value = county[name]
                delta = float(county.estimate - ablations[name][position])
                explanation.append(
                    {
                        "feature": name,
                        "value": None if pd.isna(value) else _r(value, 3),
                        "training_median": _r(models.feature_medians[name], 3),
                        "ablation_delta": _r(delta, 2),
                    }
                )
            explanation.sort(key=lambda item: abs(item["ablation_delta"]), reverse=True)
            feature_blob = features_from_points(county.centroid_lat, county.centroid_lon, points)
            county_payloads[county.county_fips] = {
                "estimate_id": estimate_id(link.storm_id, county.county_fips, MODEL_VERSION, METHODOLOGY_ID),
                "research_demonstration": True,
                "not_emergency_guidance": True,
                "banner": RESEARCH_BANNER,
                "storm_id": link.storm_id,
                "storm_name": link.storm_name,
                "season_year": link.season_year,
                "county_fips": county.county_fips,
                "county_name": county.county_name,
                "in_modeling_universe": bool(county.in_modeling_universe),
                "support": "in_support" if county.in_modeling_universe else "extrapolated",
                "split": split,
                "target": {
                    "name": TARGET,
                    "definition": (
                        "Sum of OpenFEMA HousingAssistanceOwners.validRegistrations for this "
                        "disasterNumber and county. Missing zip rows count as zero inside the "
                        "IA/IH designated universe."
                    ),
                    "unit": "owner valid registrations",
                },
                "published_model": models.published_name,
                "estimate": _r(county.estimate, 2),
                "baseline_estimate": _r(county.linear_estimate, 2),
                "boosted_estimate": _r(county.boosted_estimate, 2),
                "interval": {
                    "lower": _r(county.lower, 2),
                    "upper": _r(county.upper, 2),
                    "nominal_coverage": CONFORMAL_COVERAGE,
                    "method": "split_conformal_log1p_absolute_residual",
                    "calibration_storms": f"incident begin in [{TRAIN_END}, {CALIBRATION_END})",
                },
                "observed_owner_valid_registrations": int(county.owner_valid_registrations),
                "observed_owner_approved_ihp_amount": _r(county.owner_approved_ihp_amount, 2),
                "explanation": explanation[:8],
                "features": {
                    name: None if pd.isna(county[name]) else _r(county[name], 3) for name in FEATURES
                },
                "sources": {
                    "declaration": None
                    if pd.isna(county.declaration_natural_key)
                    else {
                        "natural_key": county.declaration_natural_key,
                        "key_fields": ["femaDeclarationString", "placeCode"],
                        "fema_declaration_string": county.fema_declaration_string,
                        "place_code": county.place_code,
                        "designated_area": county.designated_area,
                        "snapshot_id": snapshot_ids["declarations"],
                    },
                    "housing_rows": {
                        "natural_key_fields": ["disasterNumber", "state", "county", "city", "zipCode"],
                        "snapshot_id": snapshot_ids["housing"],
                        "row_count": len(keys_by_pair.get(pair, [])),
                        "natural_keys": keys_by_pair.get(pair, []),
                        "api_id_note": "OpenFEMA id is an API GUID and is not a StormLedger key.",
                    },
                    "track_points": {
                        "natural_key_fields": ["storm_id", "yyyymmdd", "hhmm", "record_identifier"],
                        "snapshot_id": snapshot_ids["hurdat2"],
                        "closest_segment_keys": feature_blob["closest_point_keys"],
                        "exposure_point_keys": feature_blob["exposure_point_keys"],
                    },
                    "population": {
                        "vintage_id": county.population_vintage_id,
                        "reference_date": pd.Timestamp(county.population_reference_date).date().isoformat(),
                        "source_column": county.population_source_column,
                        "population": int(county.population),
                        "snapshot_id": snapshot_ids["population"],
                        "county_fips": county.county_fips,
                    },
                    "model": {
                        "model_version": MODEL_VERSION,
                        "methodology_id": METHODOLOGY_ID,
                        "published_model": models.published_name,
                        "training_snapshot_ids": snapshot_ids,
                    },
                },
                "match_rule": link.match_rule,
            }
        _write_json(
            provenance_dir / f"{link.storm_id}.json",
            {"storm_id": link.storm_id, "counties": county_payloads},
            indent=None,
        )
        max_observed = int(storm_rows["owner_valid_registrations"].max())
        storm_payloads.append(
            {
                "storm_id": link.storm_id,
                "name": link.storm_name.title(),
                "season_year": int(link.season_year),
                "disaster_number": int(link.disaster_number),
                "fema_declaration_string": link.fema_declaration_string,
                "declaration_title": link.declaration_title,
                "incident_begin": pd.Timestamp(link.incident_begin).strftime("%Y-%m-%d"),
                "split": split,
                "featured": link.storm_id in FEATURED_STORM_IDS,
                "frame_count": len(frames),
                "universe_counties": int(storm_rows["in_modeling_universe"].sum()),
                "observed_owner_registrations": int(storm_rows["owner_valid_registrations"].sum()),
                "max_county_observed": max_observed,
                "match_rule": link.match_rule,
            }
        )

    area_rows = int(rollup["declaration_area_rows"])
    distinct = int(rollup["distinct_disasters"])
    if distinct >= area_rows:
        raise BuildError("Distinct disasters must be fewer than declaration-area rows")
    quality = {
        "declaration_area_rows": area_rows,
        "distinct_disasters": distinct,
        "distinct_declaration_strings": int(rollup["distinct_declaration_strings"]),
        "counting_note": (
            f"{area_rows:,} declaration-area rows describe {distinct:,} distinct disasters. "
            "Each row is one designated place on a declaration, not a separate disaster. "
            "The count is distinct disasterNumber."
        ),
        "quarantine": {
            "declarations": int(len(decl_quarantine)),
            "housing": int(len(housing_quarantine)),
            "declaration_reasons": decl_quarantine["quarantine_reason"].value_counts().to_dict()
            if len(decl_quarantine) and "quarantine_reason" in decl_quarantine.columns
            else {},
            "housing_reasons": housing_quarantine["quarantine_reason"].value_counts().to_dict()
            if len(housing_quarantine) and "quarantine_reason" in housing_quarantine.columns
            else {},
        },
        "housing_rows": int(len(housing)),
        "housing_unmatched_labels": unmatched.to_dict(orient="records"),
        "housing_unmatched_registrations": int(unmatched["owner_valid_registrations"].sum()) if len(unmatched) else 0,
        "non_county_designation_rows": int(non_county),
        "rejected_links": [item.__dict__ for item in rejected],
        "snapshot_ids": snapshot_ids,
        "snapshot_retrieved_at": {
            "declarations": declaration_meta["retrieved_at"],
            "housing": housing_meta["retrieved_at"],
            "hurdat2": hurdat_meta["retrieved_at"],
            "population": population_meta["retrieved_at"],
            "counties": geo_meta["retrieved_at"],
        },
    }
    coefficients = models.linear.estimator.named_steps["linear"].coef_
    metrics = {
        "research_demonstration": True,
        "not_emergency_guidance": True,
        "banner": RESEARCH_BANNER,
        "model_version": MODEL_VERSION,
        "methodology_id": METHODOLOGY_ID,
        "target": {
            "name": TARGET,
            "unit": "owner valid registrations",
            "dataset": HOUSING_ENTITY,
            "field": "validRegistrations",
        },
        "published_model": models.published_name,
        "selection_rule": (
            "Publish the boosted tree only when its calibration MAE is at most "
            "0.90 times the linear baseline MAE. Otherwise publish the linear model. "
            "The test set is not used for selection."
        ),
        "selection_margin": 0.90,
        "splits": {
            "train": f"incident_begin < {TRAIN_END}",
            "calibration": f"{TRAIN_END} <= incident_begin < {CALIBRATION_END}",
            "test": f"incident_begin >= {CALIBRATION_END}",
        },
        "n_rows": {
            "train": int((universe["split"] == "train").sum()),
            "calibration": int((universe["split"] == "calibration").sum()),
            "test": int((universe["split"] == "test").sum()),
        },
        "calibration_mae": {key: _r(value, 4) for key, value in models.calibration_mae.items()},
        "test": {
            **models.test_metrics,
            "mae_linear": _r(models.test_metrics["mae_linear"], 4),
            "mae_boosted": _r(models.test_metrics["mae_boosted"], 4),
            "medae_linear": _r(models.test_metrics["medae_linear"], 4),
            "medae_boosted": _r(models.test_metrics["medae_boosted"], 4),
            "mae_log1p_linear": _r(models.test_metrics["mae_log1p_linear"], 4),
            "mae_log1p_boosted": _r(models.test_metrics["mae_log1p_boosted"], 4),
            "mae_published": _r(models.test_metrics["mae_published"], 4),
            "medae_published": _r(models.test_metrics["medae_published"], 4),
            "interval": {
                **models.test_metrics["interval"],
                "log_radius": _r(models.test_metrics["interval"]["log_radius"], 6),
                "empirical_coverage": _r(models.test_metrics["interval"]["empirical_coverage"], 4),
                "mean_width": _r(models.test_metrics["interval"]["mean_width"], 4),
            },
        },
        "permutation_importance_calibration": models.permutation_importance,
        "standardized_linear_coefficients": [
            {"feature": name, "coefficient_on_log1p": _r(coef, 4)} for name, coef in zip(FEATURES, coefficients)
        ],
        "leakage_checks": checks,
        "feature_list": FEATURES,
    }
    summary = {
        "research_demonstration": True,
        "not_emergency_guidance": True,
        "banner": RESEARCH_BANNER,
        "counting_note": quality["counting_note"],
        "declaration_area_rows": quality["declaration_area_rows"],
        "distinct_disasters": quality["distinct_disasters"],
        "published_model": models.published_name,
        "target_label": "Owner valid registrations",
        "storms": storm_payloads,
        "disasters": json.loads(disasters_out.to_json(orient="records", date_format="iso")),
    }
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "quality.json", quality)
    _write_json(output_dir / "counties.geojson", geojson, indent=None)
    card = _model_card(metrics, quality)
    (output_dir / "model_card.md").write_text(card)
    if output_dir.resolve() == (root / "data" / "curated").resolve():
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "model_card.md").write_text(card)
    joblib.dump(
        {
            "model_version": MODEL_VERSION,
            "published_model": models.published_name,
            "pressure_median": models.pressure_median,
            "feature_medians": models.feature_medians,
            "conformal_log_radius": models.conformal_log_radius,
            "linear": models.linear.estimator,
            "boosted": models.boosted.estimator,
            "features": FEATURES,
        },
        output_dir / "model.joblib",
    )
    if len(decl_quarantine):
        decl_quarantine.to_json(output_dir / "quarantine_declarations.jsonl", orient="records", lines=True)
    if len(housing_quarantine):
        housing_quarantine.to_json(output_dir / "quarantine_housing.jsonl", orient="records", lines=True)
    return metrics
