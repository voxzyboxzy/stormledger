"""Content hashes for immutable snapshots and deterministic estimate ids."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_dumps(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def estimate_id(storm_id: str, county_fips: str, model_version: str, methodology_id: str) -> str:
    """Derived id. Source records keep their own natural keys; this only names the estimate."""
    raw = f"{model_version}|{methodology_id}|{storm_id}|{county_fips}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
