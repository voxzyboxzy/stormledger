import { useState } from "react";
import { formatNumber } from "../color";
import type { CountyProvenance, Frame, FrameCounty } from "../types";

const FEATURE_LABELS: Record<string, string> = {
  min_distance_km: "Distance to track",
  closest_wind_kt: "Wind at closest approach",
  peak_wind_within_250km: "Peak wind within 250 km",
  min_pressure_hpa: "Pressure at closest approach",
  pressure_missing: "Pressure missing",
  hours_within_150km: "Hours within 150 km",
  inside_34kt: "Inside 34 kt wind radius",
  inside_50kt: "Inside 50 kt wind radius",
  inside_64kt: "Inside 64 kt wind radius",
  radii_missing: "Wind radii missing",
  log_population: "Log population",
};

type Props = {
  county: CountyProvenance | null;
  live: FrameCounty | null;
  frame: Frame | null;
};

export function DetailPanel({ county, live, frame }: Props) {
  const [showKeys, setShowKeys] = useState(false);
  if (!county || !live || !frame) {
    return (
      <aside className="detail">
        <p className="muted">Select a county on the map or in the list. Every estimate opens its source records.</p>
      </aside>
    );
  }
  const keys = county.sources.housing_rows.natural_keys;
  const visible = showKeys ? keys : keys.slice(0, 6);
  return (
    <aside className="detail">
      <p className="kicker">{county.county_fips}</p>
      <h2>{county.county_name} County</h2>
      <p className="chips">
        <span className={county.in_modeling_universe ? "chip good" : "chip warn"}>
          {county.in_modeling_universe ? "IA/IH designated" : "Extrapolated"}
        </span>
        <span className="chip">{frame.provisional ? "Track to date" : "Full best track"}</span>
      </p>
      <p className="estimate" data-testid="live-estimate">
        {formatNumber(live.estimate, 0)}
      </p>
      <p className="estimate-unit">owner valid registrations, model estimate</p>
      <p className="interval">
        80% interval {formatNumber(live.lower, 0)} – {formatNumber(live.upper, 0)}
      </p>
      <dl className="facts">
        <div>
          <dt>Observed FEMA rows</dt>
          <dd>{formatNumber(live.observed)}</dd>
        </div>
        <div>
          <dt>Distance now</dt>
          <dd>{formatNumber(live.distance_km, 0)} km</dd>
        </div>
        <div>
          <dt>Linear baseline</dt>
          <dd>{formatNumber(county.baseline_estimate, 0)}</dd>
        </div>
        <div>
          <dt>Boosted tree</dt>
          <dd>{formatNumber(county.boosted_estimate, 0)}</dd>
        </div>
      </dl>
      {frame.provisional ? (
        <p className="note">
          This number uses only best-track fixes at or before {frame.valid_time}. Source records below belong to the
          final best-track estimate ({formatNumber(county.estimate, 0)}), which is what the backtest scores.
        </p>
      ) : (
        <p className="note">Final best-track estimate. The backtest scores this number, not the earlier frames.</p>
      )}
      <h3>Why this estimate moved</h3>
      <p className="muted">
        Each row is the change in the published {county.published_model} estimate when that feature is replaced by its
        training median. It is not a causal effect.
      </p>
      <ul className="explain">
        {county.explanation.slice(0, 5).map((item) => (
          <li key={item.feature}>
            <span>{FEATURE_LABELS[item.feature] ?? item.feature}</span>
            <strong>{item.ablation_delta > 0 ? "+" : ""}{formatNumber(item.ablation_delta, 0)}</strong>
          </li>
        ))}
      </ul>
      <h3>Source records</h3>
      <p className="mono" data-testid="declaration-key">
        {county.sources.declaration
          ? county.sources.declaration.natural_key
          : "No county declaration row"}
      </p>
      <p className="muted">
        Declaration key fields: femaDeclarationString and placeCode. OpenFEMA id is not used.
      </p>
      <p className="mono">
        Track {county.sources.track_points.closest_segment_keys.join(" · ")}
      </p>
      <p className="muted">
        Population {formatNumber(county.sources.population.population)} on {county.sources.population.reference_date} (
        {county.sources.population.vintage_id}).
      </p>
      <p className="muted">
        {county.sources.housing_rows.row_count} housing rows. Key: disasterNumber, state, county, city, zipCode.
      </p>
      <ul className="keys">
        {visible.map((key) => (
          <li key={key}>{key}</li>
        ))}
      </ul>
      {keys.length > 6 ? (
        <button type="button" className="text-button" onClick={() => setShowKeys((open) => !open)}>
          {showKeys ? "Show fewer source rows" : `Show all ${keys.length} source rows`}
        </button>
      ) : null}
      <p className="target">{county.target.definition}</p>
    </aside>
  );
}
