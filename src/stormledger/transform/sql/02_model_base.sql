-- Population vintage is the latest Census reference date strictly before the incident.
CREATE OR REPLACE TABLE population_for_storm AS
SELECT
  storm_id,
  county_fips,
  population,
  reference_date,
  vintage_id,
  source_column
FROM (
  SELECT
    s.storm_id,
    p.county_fips,
    p.population,
    p.reference_date,
    p.vintage_id,
    p.source_column,
    ROW_NUMBER() OVER (
      PARTITION BY s.storm_id, p.county_fips
      ORDER BY p.reference_date DESC
    ) AS rn
  FROM storms s
  JOIN population p
    ON CAST(p.reference_date AS DATE) < CAST(s.incident_begin AS DATE)
) ranked
WHERE rn = 1;

CREATE OR REPLACE TABLE modeling_base AS
SELECT
  l.storm_id,
  s.storm_name,
  s.season_year,
  l.disaster_number,
  l.fema_declaration_string,
  l.declaration_title,
  s.incident_begin,
  l.match_rule,
  c.county_fips,
  c.county_name,
  c.centroid_lat,
  c.centroid_lon,
  pop.population,
  pop.reference_date AS population_reference_date,
  pop.vintage_id AS population_vintage_id,
  pop.source_column AS population_source_column,
  COALESCE(des.ih_program_declared, FALSE) AS ih_program_declared,
  COALESCE(des.ia_program_declared, FALSE) AS ia_program_declared,
  (COALESCE(des.ih_program_declared, FALSE) OR COALESCE(des.ia_program_declared, FALSE)) AS in_modeling_universe,
  des.place_code,
  des.designated_area,
  des.declaration_natural_key,
  COALESCE(h.owner_valid_registrations, 0)::BIGINT AS owner_valid_registrations,
  COALESCE(h.owner_approved_ihp_amount, 0)::DOUBLE AS owner_approved_ihp_amount,
  COALESCE(h.source_row_count, 0)::BIGINT AS housing_source_row_count
FROM storm_disaster_link l
JOIN storms s ON s.storm_id = l.storm_id
CROSS JOIN counties c
LEFT JOIN population_for_storm pop
  ON pop.storm_id = l.storm_id AND pop.county_fips = c.county_fips
LEFT JOIN county_designations des
  ON des.disaster_number = l.disaster_number AND des.county_fips = c.county_fips
LEFT JOIN housing_county h
  ON h.disaster_number = l.disaster_number AND h.county_fips = c.county_fips;
