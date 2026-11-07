"""Download a new immutable snapshot bundle. Existing snapshot directories are never replaced."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from stormledger.constants import (
    DECLARATION_ENTITY,
    DECLARATION_FILTER,
    HOUSING_ENTITY,
    HOUSING_FILTER,
)
from stormledger.ingest.hurdat2 import download_hurdat, write_hurdat_snapshot
from stormledger.ingest.openfema import fetch_all_pages, write_snapshot
from stormledger.ingest.reference import write_county_snapshot, write_population_snapshot
from stormledger.paths import repo_root


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def refresh_snapshots(root: Path | None = None) -> dict:
    root = root or repo_root()
    retrieved_at = datetime.now(timezone.utc)
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    data = root / "data" / "snapshots"

    declaration_pages = fetch_all_pages(DECLARATION_ENTITY, DECLARATION_FILTER)
    declaration_dir = write_snapshot(
        data / "openfema" / "disaster_declarations_summaries" / stamp,
        entity=DECLARATION_ENTITY,
        filter_expr=DECLARATION_FILTER,
        pages=declaration_pages,
        retrieved_at=retrieved_at,
    )

    housing_pages = fetch_all_pages(HOUSING_ENTITY, HOUSING_FILTER)
    housing_dir = write_snapshot(
        data / "openfema" / "housing_assistance_owners" / stamp,
        entity=HOUSING_ENTITY,
        filter_expr=HOUSING_FILTER,
        pages=housing_pages,
        retrieved_at=retrieved_at,
    )

    hurdat_dir = data / "hurdat2" / "atlantic" / stamp
    hurdat_file = hurdat_dir / "hurdat2.txt"
    # download_hurdat creates the file; the snapshot writer also creates the directory.
    # Download to a sibling temp name first so a failed download cannot look like a snapshot.
    temp_hurdat = root / "data" / f".hurdat2-{stamp}.tmp"
    temp_hurdat.parent.mkdir(parents=True, exist_ok=True)
    source_url = download_hurdat(temp_hurdat)
    raw = temp_hurdat.read_bytes()
    temp_hurdat.unlink()
    write_hurdat_snapshot(hurdat_dir, raw, source_url, retrieved_at)

    population_dir = write_population_snapshot(data / "census" / "county_population" / stamp, retrieved_at)
    county_dir = write_county_snapshot(data / "geography" / "florida_counties" / stamp, retrieved_at)

    manifest = {
        "bundle_id": stamp,
        "updated_at": retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshots": {
            "disaster_declarations_summaries": _rel(root, declaration_dir),
            "housing_assistance_owners": _rel(root, housing_dir),
            "hurdat2_atlantic": _rel(root, hurdat_dir),
            "census_county_population": _rel(root, population_dir),
            "florida_counties": _rel(root, county_dir),
        },
    }
    manifest_path = root / "data" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
