"""Methodology constants. Changing these changes the published estimate identity."""

from __future__ import annotations

MODEL_VERSION = "stormledger-0.1.0"
METHODOLOGY_ID = "fl-owner-valid-registrations-v1"

# Time-separated splits use the disaster incident begin date.
TRAIN_END = "2018-01-01"  # train: incident_begin < TRAIN_END
CALIBRATION_END = "2022-01-01"  # calibration: TRAIN_END <= incident_begin < CALIBRATION_END
# test: incident_begin >= CALIBRATION_END

# Publish the boosted tree only when it is clearly better on the calibration
# window. Otherwise publish the linear baseline. The test set is not used.
BOOSTED_CALIBRATION_MARGIN = 0.90

CONFORMAL_COVERAGE = 0.80

FEATURES = [
    "min_distance_km",
    "closest_wind_kt",
    "peak_wind_within_250km",
    "min_pressure_hpa",
    "pressure_missing",
    "hours_within_150km",
    "inside_34kt",
    "inside_50kt",
    "inside_64kt",
    "radii_missing",
    "log_population",
]

# Fields that would leak the outcome, the place identity, or the designation decision.
BANNED_FEATURES = {
    "owner_valid_registrations",
    "owner_approved_ihp_amount",
    "approved_for_fema_assistance",
    "valid_registrations",
    "total_approved_ihp_amount",
    "county_fips",
    "disaster_number",
    "storm_id",
    "ih_program_declared",
    "ia_program_declared",
    "pa_program_declared",
    "hm_program_declared",
    "in_modeling_universe",
}

TARGET = "owner_valid_registrations"

FEATURED_STORM_IDS = ("AL092022", "AL112017", "AL142018")  # Ian, Irma, Michael

RESEARCH_BANNER = (
    "Research demonstration. Not emergency guidance. Not a forecast and not for "
    "decisions about safety, insurance, or assistance."
)

OPENFEMA_PAGE_SIZE = 1000
USER_AGENT = "StormLedger/0.1 (research; public-data snapshot)"

DECLARATION_FILTER = "state eq 'FL' and incidentType eq 'Hurricane'"
HOUSING_FILTER = "state eq 'FL'"

DECLARATION_ENTITY = "DisasterDeclarationsSummaries"
HOUSING_ENTITY = "HousingAssistanceOwners"

# Stable source keys. OpenFEMA `id` is an API-assigned GUID and is not used.
DECLARATION_KEY_FIELDS = ("femaDeclarationString", "placeCode")
HOUSING_KEY_FIELDS = ("disasterNumber", "state", "county", "city", "zipCode")
HURDAT_KEY_FIELDS = ("storm_id", "yyyymmdd", "hhmm", "record_identifier")
