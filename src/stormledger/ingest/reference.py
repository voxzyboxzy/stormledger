"""Census population extracts and Florida county geometry snapshots."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from stormledger.constants import USER_AGENT
from stormledger.hashutil import sha256_bytes, sha256_file

CENSUS_SOURCES = (
    {
        "vintage_id": "census_2000",
        "reference_date": "2000-04-01",
        "url": "https://www2.census.gov/programs-surveys/popest/datasets/2000-2009/counties/totals/co-est2009-alldata.csv",
        "column": "CENSUS2000POP",
        "file": "census_2000_fl.csv",
    },
    {
        "vintage_id": "census_2010",
        "reference_date": "2010-04-01",
        "url": "https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/counties/totals/co-est2020-alldata.csv",
        "column": "CENSUS2010POP",
        "file": "census_2010_fl.csv",
    },
    {
        "vintage_id": "census_2020_estimates_base",
        "reference_date": "2020-04-01",
        "url": "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv",
        "column": "ESTIMATESBASE2020",
        "file": "census_2020_fl.csv",
    },
)

COUNTY_GEOJSON_URL = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"


def _get(url: str, opener=None) -> bytes:
    open_fn = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_fn(request) as response:
        return response.read()


def florida_population_rows(raw: bytes, column: str) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        if row.get("SUMLEV") != "050":
            continue
        if str(row.get("STATE", "")).zfill(2) != "12":
            continue
        rows.append(
            {
                "county_fips": str(row["STATE"]).zfill(2) + str(row["COUNTY"]).zfill(3),
                "county_name": row["CTYNAME"].removesuffix(" County"),
                "population": row[column],
            }
        )
    if len(rows) != 67:
        raise RuntimeError(f"Expected 67 Florida counties in Census extract, found {len(rows)}")
    return rows


def write_population_snapshot(dest_dir: Path, retrieved_at: datetime, opener=None) -> Path:
    if dest_dir.exists():
        raise FileExistsError(f"Snapshot already exists and will not be overwritten: {dest_dir}")
    dest_dir.mkdir(parents=True)
    sources = []
    for spec in CENSUS_SOURCES:
        raw = _get(spec["url"], opener=opener)
        rows = florida_population_rows(raw, spec["column"])
        fieldnames = ["county_fips", "county_name", "population"]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: item["county_fips"]):
            writer.writerow(row)
        payload = buffer.getvalue().encode()
        (dest_dir / spec["file"]).write_bytes(payload)
        sources.append(
            {
                "vintage_id": spec["vintage_id"],
                "reference_date": spec["reference_date"],
                "source_url": spec["url"],
                "source_column": spec["column"],
                "source_sha256": sha256_bytes(raw),
                "source_bytes": len(raw),
                "extract_file": spec["file"],
                "extract_sha256": sha256_bytes(payload),
                "extract_filter": "SUMLEV == 050 and STATE == 12",
                "rows": len(rows),
            }
        )
    meta = {
        "source": "US Census Bureau population estimates program, Florida county extract",
        "retrieved_at": retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "The snapshot stores the Florida county extract. The full national file is not "
            "committed; source_sha256 is the SHA-256 of the bytes downloaded from source_url."
        ),
        "vintages": sources,
    }
    (dest_dir / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest_dir


def load_population_snapshot(snapshot_dir: Path) -> tuple[list[dict], dict]:
    meta = json.loads((snapshot_dir / "snapshot.json").read_text())
    rows: list[dict] = []
    for vintage in meta["vintages"]:
        path = snapshot_dir / vintage["extract_file"]
        if sha256_file(path) != vintage["extract_sha256"]:
            raise RuntimeError(f"Population extract hash mismatch for {path}")
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(
                    {
                        "county_fips": row["county_fips"],
                        "county_name": row["county_name"],
                        "population": int(row["population"]),
                        "reference_date": vintage["reference_date"],
                        "vintage_id": vintage["vintage_id"],
                        "source_column": vintage["source_column"],
                        "source_url": vintage["source_url"],
                    }
                )
    return rows, meta


def florida_counties_from_national(raw: bytes) -> dict:
    payload = json.loads(raw)
    features = []
    for feature in payload["features"]:
        fips = str(feature.get("id") or "")
        if not fips.startswith("12"):
            continue
        features.append(feature)
    if len(features) != 67:
        raise RuntimeError(f"Expected 67 Florida county features, found {len(features)}")
    return {"type": "FeatureCollection", "features": features}


def write_county_snapshot(dest_dir: Path, retrieved_at: datetime, opener=None) -> Path:
    if dest_dir.exists():
        raise FileExistsError(f"Snapshot already exists and will not be overwritten: {dest_dir}")
    dest_dir.mkdir(parents=True)
    raw = _get(COUNTY_GEOJSON_URL, opener=opener)
    collection = florida_counties_from_national(raw)
    encoded = json.dumps(collection, separators=(",", ":")).encode()
    (dest_dir / "fl_counties.geojson").write_bytes(encoded)
    meta = {
        "source": "plotly datasets geojson-counties-fips (Census GEOID county polygons)",
        "source_url": COUNTY_GEOJSON_URL,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_sha256": sha256_bytes(raw),
        "source_bytes": len(raw),
        "extract_file": "fl_counties.geojson",
        "extract_sha256": sha256_bytes(encoded),
        "extract_filter": "feature id startswith 12",
        "features": 67,
    }
    (dest_dir / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest_dir


def load_county_geojson(snapshot_dir: Path) -> tuple[dict, dict]:
    meta = json.loads((snapshot_dir / "snapshot.json").read_text())
    path = snapshot_dir / meta["extract_file"]
    if sha256_file(path) != meta["extract_sha256"]:
        raise RuntimeError(f"County geometry hash mismatch for {path}")
    return json.loads(path.read_text()), meta
