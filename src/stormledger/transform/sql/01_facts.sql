-- Declaration-area rows are not disasters. Counts use disaster_number.
CREATE OR REPLACE TABLE disaster_rollup AS
SELECT
  COUNT(*)::BIGINT AS declaration_area_rows,
  COUNT(DISTINCT disaster_number)::BIGINT AS distinct_disasters,
  COUNT(DISTINCT fema_declaration_string)::BIGINT AS distinct_declaration_strings
FROM declarations;

CREATE OR REPLACE TABLE disasters AS
SELECT
  disaster_number,
  ANY_VALUE(fema_declaration_string) AS fema_declaration_string,
  ANY_VALUE(declaration_type) AS declaration_type,
  ANY_VALUE(declaration_title) AS declaration_title,
  MIN(incident_begin_date) AS incident_begin,
  MIN(declaration_date) AS declaration_date,
  COUNT(*)::BIGINT AS area_rows,
  COUNT(*) FILTER (WHERE ih_program_declared)::BIGINT AS ih_area_rows,
  COUNT(*) FILTER (WHERE ia_program_declared)::BIGINT AS ia_area_rows,
  COUNT(*) FILTER (WHERE pa_program_declared)::BIGINT AS pa_area_rows
FROM declarations
GROUP BY disaster_number;

-- County geography join is on the 5-digit FIPS code, not on a regenerated id.
CREATE OR REPLACE TABLE county_designations AS
SELECT
  disaster_number,
  county_fips,
  BOOL_OR(ih_program_declared) AS ih_program_declared,
  BOOL_OR(ia_program_declared) AS ia_program_declared,
  BOOL_OR(pa_program_declared) AS pa_program_declared,
  BOOL_OR(hm_program_declared) AS hm_program_declared,
  ARG_MAX(natural_key, CASE WHEN place_code LIKE '99%' THEN 1 ELSE 0 END) AS declaration_natural_key,
  ARG_MAX(place_code, CASE WHEN place_code LIKE '99%' THEN 1 ELSE 0 END) AS place_code,
  ARG_MAX(designated_area, CASE WHEN place_code LIKE '99%' THEN 1 ELSE 0 END) AS designated_area,
  ARG_MAX(fema_declaration_string, CASE WHEN place_code LIKE '99%' THEN 1 ELSE 0 END) AS fema_declaration_string
FROM declarations
WHERE county_fips IN (SELECT county_fips FROM counties)
GROUP BY disaster_number, county_fips;

CREATE OR REPLACE TABLE non_county_designations AS
SELECT
  disaster_number,
  county_fips,
  designated_area,
  place_code,
  natural_key
FROM declarations
WHERE county_fips NOT IN (SELECT county_fips FROM counties);

-- Housing Assistance Owners has no FIPS column. Join the published county label
-- to the Census county name key, then aggregate with the FIPS code.
CREATE OR REPLACE TABLE housing_county AS
SELECT
  h.disaster_number,
  c.county_fips,
  SUM(h.valid_registrations)::BIGINT AS owner_valid_registrations,
  SUM(h.total_approved_ihp_amount)::DOUBLE AS owner_approved_ihp_amount,
  COUNT(*)::BIGINT AS source_row_count
FROM housing h
JOIN counties c ON h.county_name_key = c.name_key
GROUP BY h.disaster_number, c.county_fips;

CREATE OR REPLACE TABLE housing_unmatched AS
SELECT
  h.county_name_key,
  ANY_VALUE(h.county) AS county_label,
  COUNT(*)::BIGINT AS source_rows,
  SUM(h.valid_registrations)::BIGINT AS owner_valid_registrations
FROM housing h
LEFT JOIN counties c ON h.county_name_key = c.name_key
WHERE c.county_fips IS NULL
GROUP BY h.county_name_key
ORDER BY source_rows DESC;
