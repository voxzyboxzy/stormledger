import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { App } from "./App";
import type { Bundle, FramesFile, ProvenanceFile } from "./types";

vi.mock("./components/MapView", () => ({
  MapView: ({ onSelect }: { onSelect: (fips: string) => void }) => (
    <button type="button" onClick={() => onSelect("12071")}>
      Map county Lee
    </button>
  ),
}));

const frames: FramesFile = {
  storm_id: "AL092022",
  frames: [
    {
      index: 0,
      valid_time: "2022-09-28T00:00:00Z",
      status: "HU",
      status_label: "Hurricane",
      wind_kt: 105,
      position: [-83.0, 24.4],
      track: [[-83.0, 24.4]],
      track_point_key: "AL092022|20220928|0000|",
      provisional: true,
      counties: {
        "12071": { estimate: 1200, lower: 400, upper: 3000, observed: 8000, in_universe: true, distance_km: 180, wind_kt: 40 },
      },
    },
    {
      index: 1,
      valid_time: "2022-09-28T19:05:00Z",
      status: "HU",
      status_label: "Hurricane",
      wind_kt: 130,
      position: [-82.2, 26.7],
      track: [
        [-83.0, 24.4],
        [-82.2, 26.7],
      ],
      track_point_key: "AL092022|20220928|1905|L",
      provisional: false,
      counties: {
        "12071": { estimate: 9400, lower: 3000, upper: 22000, observed: 8000, in_universe: true, distance_km: 12, wind_kt: 130 },
      },
    },
  ],
};

const provenance: ProvenanceFile = {
  storm_id: "AL092022",
  counties: {
    "12071": {
      estimate_id: "abc",
      banner: "Research demonstration. Not emergency guidance.",
      county_fips: "12071",
      county_name: "Lee",
      in_modeling_universe: true,
      support: "in_support",
      published_model: "linear",
      estimate: 9400,
      baseline_estimate: 9100,
      boosted_estimate: 8700,
      interval: { lower: 3000, upper: 22000, nominal_coverage: 0.8, method: "split_conformal_log1p_absolute_residual" },
      observed_owner_valid_registrations: 8000,
      observed_owner_approved_ihp_amount: 100,
      explanation: [
        { feature: "min_distance_km", value: 12, training_median: 140, ablation_delta: 2500 },
      ],
      features: { min_distance_km: 12 },
      sources: {
        declaration: {
          natural_key: "DR-4673-FL|99071",
          key_fields: ["femaDeclarationString", "placeCode"],
          fema_declaration_string: "DR-4673-FL",
          place_code: "99071",
          designated_area: "Lee (County)",
          snapshot_id: "snap",
        },
        housing_rows: {
          natural_key_fields: ["disasterNumber", "state", "county", "city", "zipCode"],
          snapshot_id: "snap",
          row_count: 2,
          natural_keys: ["4673|FL|Lee (County)|CAPE CORAL|33904", "4673|FL|Lee (County)|FORT MYERS|33901"],
        },
        track_points: {
          natural_key_fields: ["storm_id", "yyyymmdd", "hhmm", "record_identifier"],
          snapshot_id: "snap",
          closest_segment_keys: ["AL092022|20220928|1905|L"],
          exposure_point_keys: [],
        },
        population: {
          vintage_id: "census_2020_estimates_base",
          reference_date: "2020-04-01",
          source_column: "ESTIMATESBASE2020",
          population: 760822,
          snapshot_id: "snap",
        },
      },
      match_rule: "test rule",
      target: { name: "owner_valid_registrations", definition: "Sum of validRegistrations.", unit: "owner valid registrations" },
    },
  },
};

const bundle: Bundle = {
  summary: {
    banner: "Research demonstration. Not emergency guidance. Not a forecast and not for decisions about safety, insurance, or assistance.",
    counting_note: "1,447 declaration-area rows describe 60 distinct disasters. Each row is one designated place on a declaration, not a separate disaster.",
    declaration_area_rows: 1447,
    distinct_disasters: 60,
    published_model: "linear",
    target_label: "Owner valid registrations",
    storms: [
      {
        storm_id: "AL092022",
        name: "Ian",
        season_year: 2022,
        disaster_number: 4673,
        fema_declaration_string: "DR-4673-FL",
        declaration_title: "HURRICANE IAN",
        incident_begin: "2022-09-23",
        split: "test",
        featured: true,
        frame_count: 2,
        universe_counties: 26,
        observed_owner_registrations: 485552,
        max_county_observed: 1000,
        match_rule: "test",
      },
    ],
    disasters: [],
  },
  metrics: {
    banner: "Research demonstration.",
    published_model: "linear",
    selection_rule: "Publish the boosted tree only when calibration MAE is clearly lower.",
    n_rows: { train: 248, calibration: 17, test: 115 },
    calibration_mae: { linear: 2057.4, boosted: 2196.9 },
    test: {
      n_rows: 115,
      n_storms: 5,
      storms: ["AL092022"],
      mae_linear: 8181.8,
      mae_boosted: 7419.1,
      medae_linear: 1553.2,
      medae_boosted: 1522.4,
      mae_published: 8181.8,
      mae_log1p_linear: 0.924,
      mae_log1p_boosted: 0.899,
      interval: {
        nominal_coverage: 0.8,
        empirical_coverage: 0.5652,
        mean_width: 8033,
        calibration_n: 17,
        method: "split_conformal_log1p_absolute_residual",
      },
    },
    leakage_checks: [{ name: "time_separation", passed: true }],
  },
  quality: {
    counting_note: "1,447 declaration-area rows describe 60 distinct disasters.",
    quarantine: { declarations: 0, housing: 0 },
    housing_unmatched_labels: [{ county_label: "Tampa Reservation", source_rows: 749, owner_valid_registrations: 3168 }],
    housing_unmatched_registrations: 3168,
    non_county_designation_rows: 44,
  },
  geojson: { type: "FeatureCollection", features: [] },
};

describe("StormLedger demo", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/frames")) return { json: async () => frames };
        if (String(url).endsWith("/provenance")) return { json: async () => provenance };
        throw new Error(String(url));
      }),
    );
  });

  it("keeps the research banner visible and does not count area rows as disasters", async () => {
    render(<App initial={bundle} />);
    expect(screen.getByRole("note")).toHaveTextContent("Not emergency guidance");
    expect(screen.getByText(/not a separate disaster/i)).toBeInTheDocument();
    expect(await screen.findByTestId("frame-time")).toHaveTextContent("2022-09-28T00:00:00Z");
  });

  it("opens source keys for a county and moves the scrubber", async () => {
    const user = userEvent.setup();
    render(<App initial={bundle} />);
    await user.click(await screen.findByRole("button", { name: /^Lee/ }));
    expect(screen.getByTestId("declaration-key")).toHaveTextContent("DR-4673-FL|99071");
    expect(screen.getByText(/4673\|FL\|Lee \(County\)\|CAPE CORAL\|33904/)).toBeInTheDocument();
    expect(screen.getByText(/80% interval/)).toBeInTheDocument();
    const slider = screen.getByRole("slider", { name: "Best-track time" });
    fireEvent.change(slider, { target: { value: "1" } });
    expect(screen.getByTestId("frame-time")).toHaveTextContent("2022-09-28T19:05:00Z");
    expect(screen.getByTestId("live-estimate")).toHaveTextContent("9,400");
  });

  it("shows the backtest table on the ledger", async () => {
    const user = userEvent.setup();
    render(<App initial={bundle} />);
    await user.click(screen.getByRole("button", { name: "Ledger and backtest" }));
    expect(screen.getByRole("table")).toHaveTextContent("8,181.8");
    expect(screen.getByText(/56.5%/)).toBeInTheDocument();
    expect(screen.getByText("Tampa Reservation")).toBeInTheDocument();
  });
});
