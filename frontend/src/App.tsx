import { useEffect, useMemo, useState } from "react";
import { choropleth, formatNumber, landfallIndex } from "./color";
import { DetailPanel } from "./components/DetailPanel";
import { Ledger } from "./components/Ledger";
import { MapView } from "./components/MapView";
import type { Bundle, FramesFile, ProvenanceFile, StormSummary } from "./types";

type Props = { initial?: Bundle | null };

async function loadBundle(): Promise<Bundle> {
  const [summary, metrics, quality, geojson] = await Promise.all([
    fetch("/api/summary").then((response) => response.json()),
    fetch("/api/metrics").then((response) => response.json()),
    fetch("/api/quality").then((response) => response.json()),
    fetch("/api/counties.geojson").then((response) => response.json()),
  ]);
  return { summary, metrics, quality, geojson };
}

export function App({ initial = null }: Props) {
  const [bundle, setBundle] = useState<Bundle | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"map" | "ledger">("map");
  const [stormId, setStormId] = useState("AL092022");
  const [framesFile, setFramesFile] = useState<FramesFile | null>(null);
  const [provenance, setProvenance] = useState<ProvenanceFile | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>("12071");
  const [colorBy, setColorBy] = useState<"estimate" | "observed">("estimate");

  useEffect(() => {
    if (initial) return;
    loadBundle().then(setBundle).catch(() => setError("The curated ledger is not available. Run stormledger build."));
  }, [initial]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(`/api/storms/${stormId}/frames`).then((response) => response.json()),
      fetch(`/api/storms/${stormId}/provenance`).then((response) => response.json()),
    ])
      .then(([frames, prov]) => {
        if (cancelled) return;
        setFramesFile(frames);
        setProvenance(prov);
        setIndex(0);
        setPlaying(false);
      })
      .catch(() => {
        if (!cancelled) setError("This storm has no replay frames.");
      });
    return () => {
      cancelled = true;
    };
  }, [stormId, initial]);

  const frames = framesFile?.frames ?? [];
  const frame = frames[index] ?? null;
  const maxIndex = Math.max(frames.length - 1, 0);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current >= maxIndex ? current : current + 1));
    }, 450);
    return () => window.clearInterval(timer);
  }, [playing, maxIndex]);

  useEffect(() => {
    if (playing && index >= maxIndex) setPlaying(false);
  }, [playing, index, maxIndex]);

  const colors = useMemo(() => {
    if (!frame) return {};
    const values = Object.values(frame.counties).map((county) =>
      colorBy === "estimate" ? county.estimate : county.observed,
    );
    const max = Math.max(...values, 0);
    return Object.fromEntries(
      Object.entries(frame.counties).map(([fips, county]) => [
        fips,
        choropleth(colorBy === "estimate" ? county.estimate : county.observed, max),
      ]),
    );
  }, [frame, colorBy]);

  if (error) return <p className="error">{error}</p>;
  if (!bundle) return <p className="error">Loading the ledger…</p>;

  const storms = [...bundle.summary.storms].sort((a, b) => Number(b.featured) - Number(a.featured) || a.incident_begin.localeCompare(b.incident_begin));
  const active = storms.find((storm) => storm.storm_id === stormId) ?? storms[0];
  const county = selected && provenance ? provenance.counties[selected] : null;
  const live = selected && frame ? frame.counties[selected] : null;
  const countyNames = provenance
    ? Object.values(provenance.counties).sort((a, b) => a.county_name.localeCompare(b.county_name))
    : [];

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <strong>StormLedger</strong>
          <span>Florida hurricane-impact ledger</span>
        </div>
        <p className="banner" role="note">
          {bundle.summary.banner}
        </p>
      </header>
      <div className="modes">
        <button type="button" aria-pressed={mode === "map"} onClick={() => setMode("map")}>
          Replay map
        </button>
        <button type="button" aria-pressed={mode === "ledger"} onClick={() => setMode("ledger")}>
          Ledger and backtest
        </button>
      </div>
      {mode === "ledger" ? (
        <Ledger summary={bundle.summary} metrics={bundle.metrics} quality={bundle.quality} />
      ) : (
        <div className="workspace">
          <aside className="rail">
            <p className="kicker">Replay</p>
            <div className="storm-list">
              {storms
                .filter((storm) => storm.featured)
                .map((storm) => (
                  <StormButton key={storm.storm_id} storm={storm} pressed={storm.storm_id === active.storm_id} onSelect={setStormId} />
                ))}
            </div>
            {frame ? (
              <>
                <label className="scrubber">
                  <span className="time" data-testid="frame-time">
                    {frame.valid_time} · {frame.status_label}
                    {frame.wind_kt != null ? ` · ${frame.wind_kt} kt` : ""}
                    {frame.provisional ? " · provisional" : " · final"}
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={maxIndex}
                    value={index}
                    aria-label="Best-track time"
                    aria-valuetext={frame.valid_time}
                    onChange={(event) => {
                      setPlaying(false);
                      setIndex(Number(event.target.value));
                    }}
                  />
                </label>
                <div className="row-actions">
                  <button type="button" className="play" onClick={() => setPlaying((value) => !value)}>
                    {playing ? "Pause" : "Play"}
                  </button>
                  <button
                    type="button"
                    className="play"
                    onClick={() => {
                      setPlaying(false);
                      setIndex(landfallIndex(frames));
                    }}
                  >
                    Landfall frame
                  </button>
                  <button
                    type="button"
                    className="play"
                    aria-pressed={colorBy === "observed"}
                    onClick={() => setColorBy((value) => (value === "estimate" ? "observed" : "estimate"))}
                  >
                    {colorBy === "estimate" ? "Color: estimate" : "Color: observed"}
                  </button>
                </div>
                <div className="legend">
                  <span>Low</span>
                  <div className="ramp" />
                  <span>High</span>
                </div>
                <p className="muted">
                  {active.fema_declaration_string} · {active.universe_counties} IA/IH counties · observed{" "}
                  {formatNumber(active.observed_owner_registrations)} owner registrations. Colors use a square-root
                  scale of the {colorBy === "estimate" ? "track-to-date estimate" : "final observed registrations"}.
                </p>
              </>
            ) : null}
            <h3>Other storms</h3>
            <div className="storm-scroll">
              {storms
                .filter((storm) => !storm.featured)
                .map((storm) => (
                  <StormButton key={storm.storm_id} storm={storm} pressed={storm.storm_id === active.storm_id} onSelect={setStormId} />
                ))}
            </div>
            <p className="muted">{bundle.summary.counting_note}</p>
            <h3>Counties</h3>
            <ul className="county-list">
              {countyNames.map((item) => (
                <li key={item.county_fips}>
                  <button type="button" aria-pressed={item.county_fips === selected} onClick={() => setSelected(item.county_fips)}>
                    <span>{item.county_name}</span>
                    <span>{frame ? formatNumber(frame.counties[item.county_fips]?.estimate ?? 0, 0) : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
          {frame ? (
            <MapView
              geojson={bundle.geojson}
              colors={colors}
              selected={selected}
              track={frame.track}
              position={frame.position}
              onSelect={setSelected}
            />
          ) : (
            <p className="error">Loading replay…</p>
          )}
          <DetailPanel county={county} live={live} frame={frame} />
        </div>
      )}
    </div>
  );
}

function StormButton({
  storm,
  pressed,
  onSelect,
}: {
  storm: StormSummary;
  pressed: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button type="button" className="storm" aria-pressed={pressed} onClick={() => onSelect(storm.storm_id)}>
      {storm.name} {storm.season_year}
      <small>
        {storm.fema_declaration_string} · {storm.split}
        {storm.featured ? " · replay" : ""}
      </small>
    </button>
  );
}
