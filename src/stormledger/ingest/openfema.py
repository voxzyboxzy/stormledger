"""OpenFEMA pagination and immutable raw page snapshots.

Pages are stored as the exact response bytes. Build reads those bytes and does
not call the network.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from stormledger.constants import OPENFEMA_PAGE_SIZE, USER_AGENT
from stormledger.hashutil import sha256_bytes

OPENFEMA_BASE = "https://www.fema.gov/api/open/v2"
Opener = Callable[[urllib.request.Request], object]


def build_page_url(entity: str, filter_expr: str, top: int, skip: int) -> str:
    query = urllib.parse.urlencode(
        {
            "$filter": filter_expr,
            "$top": str(top),
            "$skip": str(skip),
            "$inlinecount": "allpages",
        }
    )
    return f"{OPENFEMA_BASE}/{entity}?{query}"


def _read_response(response: object) -> bytes:
    data = response.read()  # type: ignore[attr-defined]
    if isinstance(data, str):
        return data.encode()
    return data


def fetch_all_pages(
    entity: str,
    filter_expr: str,
    *,
    page_size: int = OPENFEMA_PAGE_SIZE,
    opener: Opener | None = None,
    max_pages: int = 1000,
) -> list[bytes]:
    """Download every page. `opener` is injectable so tests never touch the network."""
    open_fn = opener or urllib.request.urlopen
    pages: list[bytes] = []
    skip = 0
    reported: int | None = None
    while True:
        if len(pages) >= max_pages:
            raise RuntimeError(f"OpenFEMA pagination exceeded {max_pages} pages for {entity}")
        url = build_page_url(entity, filter_expr, page_size, skip)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with open_fn(request) as response:  # type: ignore[operator]
            raw = _read_response(response)
        payload = json.loads(raw)
        if entity not in payload or "metadata" not in payload:
            raise RuntimeError(f"OpenFEMA response for {entity} is missing metadata or records")
        rows = payload[entity]
        if not isinstance(rows, list):
            raise RuntimeError(f"OpenFEMA entity {entity} was not a list")
        count = int(payload["metadata"]["count"])
        if reported is None:
            reported = count
        elif reported != count:
            raise RuntimeError(f"OpenFEMA reported count changed from {reported} to {count} while paging {entity}")
        pages.append(raw)
        skip += len(rows)
        if not rows or skip >= count:
            break
    if reported is not None and _record_count(pages, entity) != reported:
        raise RuntimeError(
            f"OpenFEMA {entity} returned {_record_count(pages, entity)} records but metadata count is {reported}"
        )
    return pages


def _record_count(pages: list[bytes], entity: str) -> int:
    total = 0
    for raw in pages:
        total += len(json.loads(raw)[entity])
    return total


def write_snapshot(
    dest_dir: Path,
    *,
    entity: str,
    filter_expr: str,
    pages: list[bytes],
    retrieved_at: datetime | None = None,
    source_url: str | None = None,
) -> Path:
    """Write a new immutable snapshot. Refuses to overwrite an existing directory."""
    if dest_dir.exists():
        raise FileExistsError(f"Snapshot already exists and will not be overwritten: {dest_dir}")
    dest_dir.mkdir(parents=True)
    when = retrieved_at or datetime.now(timezone.utc)
    page_meta = []
    record_count = 0
    reported_count = None
    for index, raw in enumerate(pages):
        name = f"page-{index:05d}.json"
        (dest_dir / name).write_bytes(raw)
        payload = json.loads(raw)
        rows = payload[entity]
        record_count += len(rows)
        reported_count = int(payload["metadata"]["count"])
        page_meta.append(
            {
                "file": name,
                "sha256": sha256_bytes(raw),
                "records": len(rows),
                "skip": payload["metadata"].get("skip"),
                "top": payload["metadata"].get("top"),
            }
        )
    meta = {
        "source": "OpenFEMA",
        "entity": entity,
        "source_url": source_url or f"{OPENFEMA_BASE}/{entity}",
        "filter": filter_expr,
        "retrieved_at": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_size": OPENFEMA_PAGE_SIZE,
        "record_count": record_count,
        "reported_count": reported_count,
        "pages": page_meta,
        "natural_key_note": (
            "OpenFEMA id is an API-assigned GUID and is not a StormLedger key. "
            "See stormledger.constants for the documented source-key fields."
        ),
    }
    (dest_dir / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest_dir


def load_snapshot_records(snapshot_dir: Path, entity: str) -> tuple[list[dict], dict]:
    """Load raw records from an immutable snapshot and verify page hashes."""
    meta_path = snapshot_dir / "snapshot.json"
    meta = json.loads(meta_path.read_text())
    if meta["entity"] != entity:
        raise RuntimeError(f"Snapshot entity {meta['entity']} does not match {entity}")
    records: list[dict] = []
    for page in meta["pages"]:
        path = snapshot_dir / page["file"]
        raw = path.read_bytes()
        digest = sha256_bytes(raw)
        if digest != page["sha256"]:
            raise RuntimeError(f"Snapshot page hash mismatch for {path}")
        payload = json.loads(raw)
        rows = payload[entity]
        if len(rows) != page["records"]:
            raise RuntimeError(f"Snapshot page record count mismatch for {path}")
        records.extend(rows)
    if len(records) != meta["record_count"]:
        raise RuntimeError("Snapshot record_count does not match concatenated pages")
    return records, meta
