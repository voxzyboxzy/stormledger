export type StormSummary = {
  storm_id: string;
  name: string;
  season_year: number;
  disaster_number: number;
  fema_declaration_string: string;
  declaration_title: string;
  incident_begin: string;
  split: string;
  featured: boolean;
  frame_count: number;
  universe_counties: number;
  observed_owner_registrations: number;
  max_county_observed: number;
  match_rule: string;
};

export type Summary = {
  banner: string;
  counting_note: string;
  declaration_area_rows: number;
  distinct_disasters: number;
  published_model: string;
  target_label: string;
  storms: StormSummary[];
  disasters: Array<{
    disaster_number: number;
    fema_declaration_string: string;
    declaration_type: string;
    declaration_title: string;
    incident_begin: string;
    area_rows: number;
  }>;
};

export type Metrics = {
  banner: string;
  published_model: string;
  selection_rule: string;
  n_rows: { train: number; calibration: number; test: number };
  calibration_mae: { linear: number; boosted: number };
  test: {
    n_rows: number;
    n_storms: number;
    storms: string[];
    mae_linear: number;
    mae_boosted: number;
    medae_linear: number;
    medae_boosted: number;
    mae_published: number;
    mae_log1p_linear: number;
    mae_log1p_boosted: number;
    interval: {
      nominal_coverage: number;
      empirical_coverage: number;
      mean_width: number;
      calibration_n: number;
      method: string;
    };
  };
  leakage_checks: Array<{ name: string; passed: boolean }>;
};

export type Quality = {
  counting_note: string;
  quarantine: { declarations: number; housing: number };
  housing_unmatched_labels: Array<{ county_label: string; source_rows: number; owner_valid_registrations: number }>;
  housing_unmatched_registrations: number;
  non_county_designation_rows: number;
};

export type FrameCounty = {
  estimate: number;
  lower: number;
  upper: number;
  observed: number;
  in_universe: boolean;
  distance_km: number;
  wind_kt: number;
};

export type Frame = {
  index: number;
  valid_time: string;
  status: string;
  status_label: string;
  wind_kt: number | null;
  position: [number, number];
  track: [number, number][];
  track_point_key: string;
  provisional: boolean;
  counties: Record<string, FrameCounty>;
};

export type FramesFile = { storm_id: string; frames: Frame[] };

export type Explanation = {
  feature: string;
  value: number | null;
  training_median: number;
  ablation_delta: number;
};

export type CountyProvenance = {
  estimate_id: string;
  banner: string;
  county_fips: string;
  county_name: string;
  in_modeling_universe: boolean;
  support: string;
  published_model: string;
  estimate: number;
  baseline_estimate: number;
  boosted_estimate: number;
  interval: { lower: number; upper: number; nominal_coverage: number; method: string };
  observed_owner_valid_registrations: number;
  observed_owner_approved_ihp_amount: number;
  explanation: Explanation[];
  features: Record<string, number | null>;
  sources: {
    declaration: null | {
      natural_key: string;
      key_fields: string[];
      fema_declaration_string: string;
      place_code: string;
      designated_area: string;
      snapshot_id: string;
    };
    housing_rows: {
      natural_key_fields: string[];
      snapshot_id: string;
      row_count: number;
      natural_keys: string[];
    };
    track_points: {
      natural_key_fields: string[];
      snapshot_id: string;
      closest_segment_keys: string[];
      exposure_point_keys: string[];
    };
    population: {
      vintage_id: string;
      reference_date: string;
      source_column: string;
      population: number;
      snapshot_id: string;
    };
  };
  match_rule: string;
  target: { name: string; definition: string; unit: string };
};

export type ProvenanceFile = { storm_id: string; counties: Record<string, CountyProvenance> };

export type FeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string;
    properties: Record<string, unknown>;
    geometry: { type: string; coordinates: unknown };
  }>;
};

export type Bundle = {
  summary: Summary;
  metrics: Metrics;
  quality: Quality;
  geojson: FeatureCollection;
};
