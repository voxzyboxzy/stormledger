import { formatNumber } from "../color";
import type { Metrics, Quality, Summary } from "../types";

type Props = { summary: Summary; metrics: Metrics; quality: Quality };

export function Ledger({ summary, metrics, quality }: Props) {
  const test = metrics.test;
  return (
    <section className="ledger">
      <p className="kicker">Declaration ledger</p>
      <h2>
        {formatNumber(summary.declaration_area_rows)} area rows, {formatNumber(summary.distinct_disasters)} disasters
      </h2>
      <p>{summary.counting_note}</p>
      <div className="stat-row">
        <article>
          <span>Schema quarantine</span>
          <strong>
            {quality.quarantine.declarations + quality.quarantine.housing}
          </strong>
          <em>declaration and housing rows</em>
        </article>
        <article>
          <span>Unmatched geographies</span>
          <strong>{quality.housing_unmatched_labels.length}</strong>
          <em>{formatNumber(quality.housing_unmatched_registrations)} owner registrations held out</em>
        </article>
        <article>
          <span>Non-county designations</span>
          <strong>{formatNumber(quality.non_county_designation_rows)}</strong>
          <em>rows that are not a Florida county FIPS</em>
        </article>
      </div>
      <h3>Time-separated backtest</h3>
      <p className="muted">{metrics.selection_rule}</p>
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Test MAE</th>
            <th>Test median AE</th>
            <th>Log1p MAE</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Linear baseline {metrics.published_model === "linear" ? "(published)" : ""}</td>
            <td>{formatNumber(test.mae_linear, 1)}</td>
            <td>{formatNumber(test.medae_linear, 1)}</td>
            <td>{test.mae_log1p_linear.toFixed(3)}</td>
          </tr>
          <tr>
            <td>Boosted tree {metrics.published_model === "boosted" ? "(published)" : ""}</td>
            <td>{formatNumber(test.mae_boosted, 1)}</td>
            <td>{formatNumber(test.medae_boosted, 1)}</td>
            <td>{test.mae_log1p_boosted.toFixed(3)}</td>
          </tr>
        </tbody>
      </table>
      <p>
        Train {metrics.n_rows.train} county rows, calibration {metrics.n_rows.calibration}, test {metrics.n_rows.test}{" "}
        across {test.n_storms} later storms. Calibration MAE was {formatNumber(metrics.calibration_mae.linear, 1)}{" "}
        linear and {formatNumber(metrics.calibration_mae.boosted, 1)} boosted.
      </p>
      <p>
        Nominal 80% interval coverage on the test storms was{" "}
        <strong>{(test.interval.empirical_coverage * 100).toFixed(1)}%</strong> (mean width{" "}
        {formatNumber(test.interval.mean_width, 0)} registrations). The calibration window has{" "}
        {test.interval.calibration_n} rows.
      </p>
      <h3>Leakage checks</h3>
      <ul className="checks">
        {metrics.leakage_checks.map((check) => (
          <li key={check.name}>
            <span>{check.passed ? "Passed" : "Failed"}</span>
            {check.name}
          </li>
        ))}
      </ul>
      <h3>Geographies held out of the county total</h3>
      <ul className="unmatched">
        {quality.housing_unmatched_labels.map((row) => (
          <li key={row.county_label}>
            {row.county_label}
            <span>
              {formatNumber(row.owner_valid_registrations)} registrations / {formatNumber(row.source_rows)} rows
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
