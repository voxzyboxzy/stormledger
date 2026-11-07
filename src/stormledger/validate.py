"""Pandera schema checks and quarantine of malformed or duplicate source rows."""

from __future__ import annotations

import pandas as pd

from stormledger.constants import DECLARATION_KEY_FIELDS, HOUSING_KEY_FIELDS

try:
    import pandera.pandas as pa
except ImportError:  # pragma: no cover
    import pandera as pa


def _schema_error_type():
    return pa.errors.SchemaErrors


DECLARATION_SCHEMA = pa.DataFrameSchema(
    {
        "femaDeclarationString": pa.Column(str, pa.Check.str_matches(r"^(DR|EM|FM)-\d+-[A-Z]{2}$")),
        "disasterNumber": pa.Column(int, pa.Check.ge(1), coerce=True),
        "state": pa.Column(str, pa.Check.equal_to("FL")),
        "declarationType": pa.Column(str, pa.Check.isin(["DR", "EM", "FM"])),
        "declarationDate": pa.Column(pa.DateTime, nullable=False, coerce=True),
        "incidentType": pa.Column(str, pa.Check.equal_to("Hurricane")),
        "declarationTitle": pa.Column(str, pa.Check.str_length(min_value=3)),
        "incidentBeginDate": pa.Column(pa.DateTime, nullable=False, coerce=True),
        "fipsStateCode": pa.Column(str, pa.Check.str_matches(r"^\d{2}$")),
        "fipsCountyCode": pa.Column(str, pa.Check.str_matches(r"^\d{3}$")),
        "placeCode": pa.Column(str, pa.Check.str_matches(r"^\d{5}$")),
        "designatedArea": pa.Column(str, pa.Check.str_length(min_value=2)),
        "ihProgramDeclared": pa.Column(bool, coerce=True),
        "iaProgramDeclared": pa.Column(bool, coerce=True),
        "paProgramDeclared": pa.Column(bool, coerce=True),
        "hmProgramDeclared": pa.Column(bool, coerce=True),
    },
    strict=False,
    coerce=False,
)

HOUSING_SCHEMA = pa.DataFrameSchema(
    {
        "disasterNumber": pa.Column(int, pa.Check.ge(1), coerce=True),
        "state": pa.Column(str, pa.Check.equal_to("FL")),
        "county": pa.Column(str, pa.Check.str_length(min_value=2)),
        "city": pa.Column(str, nullable=False),
        "zipCode": pa.Column(str, pa.Check.str_matches(r"^\d{5}$")),
        "validRegistrations": pa.Column(int, pa.Check.ge(0), coerce=True),
        "totalApprovedIhpAmount": pa.Column(float, pa.Check.ge(0), coerce=True),
        "approvedForFemaAssistance": pa.Column(int, pa.Check.ge(0), coerce=True),
    },
    strict=False,
    coerce=False,
)


def _prepare_declarations(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    frame["fipsStateCode"] = frame["fipsStateCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(2)
    frame["fipsCountyCode"] = frame["fipsCountyCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(3)
    frame["placeCode"] = frame["placeCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    frame["declarationDate"] = pd.to_datetime(frame["declarationDate"], utc=True, errors="coerce")
    frame["incidentBeginDate"] = pd.to_datetime(frame["incidentBeginDate"], utc=True, errors="coerce")
    for column in ("ihProgramDeclared", "iaProgramDeclared", "paProgramDeclared", "hmProgramDeclared"):
        frame[column] = frame[column].astype("boolean")
    return frame


def _prepare_housing(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    frame["zipCode"] = frame["zipCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    frame["city"] = frame["city"].fillna("").astype(str)
    frame["county"] = frame["county"].astype(str)
    frame["state"] = frame["state"].astype(str)
    return frame


def _failing_indices(exc: Exception) -> set[int]:
    failure_cases = getattr(exc, "failure_cases", None)
    if failure_cases is None or "index" not in failure_cases.columns:
        return set()
    indices: set[int] = set()
    for value in failure_cases["index"].tolist():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        if isinstance(value, (int,)):
            indices.add(int(value))
            continue
        try:
            if pd.notna(value):
                indices.add(int(value))
        except (TypeError, ValueError):
            continue
    return indices


def _apply_schema(frame: pd.DataFrame, schema: pa.DataFrameSchema) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = frame.copy().reset_index(drop=True)
    try:
        schema.validate(working, lazy=True)
        return working, working.iloc[0:0].copy()
    except _schema_error_type() as exc:
        bad = _failing_indices(exc)
        if not bad:
            quarantined = working.copy()
            quarantined["quarantine_reason"] = "schema_validation_failed"
            return working.iloc[0:0].copy(), quarantined
        reason = working.index.map(lambda idx: "schema_validation_failed" if idx in bad else "")
        quarantined = working.loc[sorted(bad)].copy()
        quarantined["quarantine_reason"] = "schema_validation_failed"
        kept = working.drop(index=sorted(bad)).copy()
        del reason
        return kept, quarantined


def _quarantine_duplicates(frame: pd.DataFrame, key_fields: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        return frame, frame.copy()
    duplicate_mask = frame.duplicated(list(key_fields), keep=False)
    if not duplicate_mask.any():
        return frame, frame.iloc[0:0].copy()
    conflict_indexes: list[int] = []
    extra_indexes: list[int] = []
    for _, group in frame.loc[duplicate_mask].groupby(list(key_fields), dropna=False):
        content = group.drop(columns=list(key_fields)).astype(str)
        if content.drop_duplicates().shape[0] > 1:
            conflict_indexes.extend(group.index.tolist())
        else:
            extra_indexes.extend(group.index.tolist()[1:])
    pieces = []
    if conflict_indexes:
        conflicted = frame.loc[conflict_indexes].copy()
        conflicted["quarantine_reason"] = "conflicting_duplicate_natural_key"
        pieces.append(conflicted)
    if extra_indexes:
        extras = frame.loc[extra_indexes].copy()
        extras["quarantine_reason"] = "duplicate_natural_key"
        pieces.append(extras)
    quarantined = pd.concat(pieces) if pieces else frame.iloc[0:0].copy()
    drop_indexes = conflict_indexes + extra_indexes
    kept = frame.drop(index=drop_indexes).copy()
    return kept, quarantined


def _with_natural_key(frame: pd.DataFrame, fields: tuple[str, ...]) -> pd.DataFrame:
    out = frame.copy()
    out["natural_key"] = out[list(fields)].astype(str).agg("|".join, axis=1)
    return out


def validate_declarations(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    prepared = _prepare_declarations(records)
    valid, quarantined = _apply_schema(prepared, DECLARATION_SCHEMA)
    valid = _with_natural_key(valid, DECLARATION_KEY_FIELDS)
    valid, duplicate_quarantine = _quarantine_duplicates(valid, DECLARATION_KEY_FIELDS)
    quarantined = pd.concat([quarantined, duplicate_quarantine], ignore_index=True)
    return valid.reset_index(drop=True), quarantined.reset_index(drop=True)


def validate_housing(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    prepared = _prepare_housing(records)
    valid, quarantined = _apply_schema(prepared, HOUSING_SCHEMA)
    valid = _with_natural_key(valid, HOUSING_KEY_FIELDS)
    valid, duplicate_quarantine = _quarantine_duplicates(valid, HOUSING_KEY_FIELDS)
    quarantined = pd.concat([quarantined, duplicate_quarantine], ignore_index=True)
    return valid.reset_index(drop=True), quarantined.reset_index(drop=True)
