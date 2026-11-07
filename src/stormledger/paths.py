"""Repository paths. Snapshots and curated outputs stay inside the repo."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("STORMLEDGER_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "stormledger").is_dir():
            return parent
    return here.parents[2]


def data_dir() -> Path:
    return repo_root() / "data"


def manifest_path() -> Path:
    return data_dir() / "manifest.json"


def default_curated_dir() -> Path:
    return data_dir() / "curated"
