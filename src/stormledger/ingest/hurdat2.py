"""NHC HURDAT2 Atlantic best-track parser.

The natural key of a fix is storm id + YYYYMMDD + HHMM + record identifier.
That is the published best-track identity, not a regenerated row id.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from stormledger.constants import USER_AGENT
from stormledger.hashutil import sha256_bytes, sha256_file

HURDAT_INDEX = "https://www.nhc.noaa.gov/data/hurdat/"
HEADER_RE = re.compile(r"^(AL\d{6}),\s+([^,]*?)\s*,\s*(\d+)\s*,\s*$")
INDEX_ROW_RE = re.compile(
    r'href="(hurdat2-1851-[^"]+\.txt)"[^<]*</a></td><td align="right">([^<]+)</td>',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TrackPoint:
    storm_id: str
    yyyymmdd: str
    hhmm: str
    record_identifier: str
    status: str
    lat: float
    lon: float
    max_wind_kt: int | None
    min_pressure_hpa: int | None
    radii_34_nm: tuple[int | None, int | None, int | None, int | None]
    radii_50_nm: tuple[int | None, int | None, int | None, int | None]
    radii_64_nm: tuple[int | None, int | None, int | None, int | None]
    valid_time: datetime

    @property
    def natural_key(self) -> str:
        return f"{self.storm_id}|{self.yyyymmdd}|{self.hhmm}|{self.record_identifier}"


@dataclass(frozen=True)
class StormTrack:
    storm_id: str
    name: str
    season_year: int
    points: tuple[TrackPoint, ...] = field(default_factory=tuple)

    @property
    def natural_key(self) -> str:
        return self.storm_id


def _missing_int(token: str) -> int | None:
    if token in {"", "-999"}:
        return None
    return int(token)


def _lat(token: str) -> float:
    hemisphere = token[-1].upper()
    value = float(token[:-1])
    if hemisphere == "S":
        return -value
    if hemisphere != "N":
        raise ValueError(f"Bad latitude {token}")
    return value


def _lon(token: str) -> float:
    hemisphere = token[-1].upper()
    value = float(token[:-1])
    if hemisphere == "W":
        return -value
    if hemisphere != "E":
        raise ValueError(f"Bad longitude {token}")
    return value


def _radii(cols: list[str], start: int) -> tuple[int | None, int | None, int | None, int | None]:
    # NE, SE, SW, NW as published by NHC.
    return tuple(_missing_int(cols[start + offset]) for offset in range(4))  # type: ignore[return-value]


def parse_hurdat2(text: str) -> list[StormTrack]:
    lines = text.splitlines()
    storms: list[StormTrack] = []
    index = 0
    while index < len(lines):
        raw = lines[index].rstrip()
        if not raw.strip():
            index += 1
            continue
        header = HEADER_RE.match(raw.strip())
        if header is None:
            raise ValueError(f"Unexpected HURDAT2 line {index + 1}: {raw[:80]}")
        storm_id, name, count_token = header.group(1), header.group(2).strip(), int(header.group(3))
        points: list[TrackPoint] = []
        for offset in range(1, count_token + 1):
            cols = [part.strip() for part in lines[index + offset].split(",")]
            if len(cols) < 21:
                raise ValueError(f"{storm_id} track row has {len(cols)} columns, expected 21")
            yyyymmdd, hhmm = cols[0], cols[1]
            valid_time = datetime.strptime(yyyymmdd + hhmm, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            points.append(
                TrackPoint(
                    storm_id=storm_id,
                    yyyymmdd=yyyymmdd,
                    hhmm=hhmm,
                    record_identifier=cols[2],
                    status=cols[3],
                    lat=_lat(cols[4]),
                    lon=_lon(cols[5]),
                    max_wind_kt=_missing_int(cols[6]),
                    min_pressure_hpa=_missing_int(cols[7]),
                    radii_34_nm=_radii(cols, 8),
                    radii_50_nm=_radii(cols, 12),
                    radii_64_nm=_radii(cols, 16),
                    valid_time=valid_time,
                )
            )
        storms.append(
            StormTrack(
                storm_id=storm_id,
                name=name,
                season_year=int(storm_id[-4:]),
                points=tuple(points),
            )
        )
        index += count_token + 1
    return storms


def duplicate_track_keys(storms: list[StormTrack]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for storm in storms:
        for point in storm.points:
            key = point.natural_key
            if key in seen:
                duplicates.append(key)
            seen.add(key)
    return duplicates


def latest_atlantic_hurdat_url(index_html: str, index_url: str = HURDAT_INDEX) -> str:
    """Choose the Atlantic HURDAT2 file with the newest directory timestamp."""
    matches = INDEX_ROW_RE.findall(index_html)
    if not matches:
        raise RuntimeError("Could not find hurdat2-1851 files in the NHC index")
    parsed: list[tuple[datetime, str]] = []
    for name, modified in matches:
        cleaned = re.sub(r"\s+", " ", modified.strip())
        stamp = datetime.strptime(cleaned, "%Y-%m-%d %H:%M")
        parsed.append((stamp, name))
    parsed.sort()
    newest = parsed[-1][1]
    return urllib_join(index_url, newest)


def urllib_join(base: str, name: str) -> str:
    if base.endswith("/"):
        return base + name
    return base + "/" + name


def download_hurdat(dest_file: Path, opener=None) -> str:
    open_fn = opener or urllib.request.urlopen
    index_request = urllib.request.Request(HURDAT_INDEX, headers={"User-Agent": USER_AGENT})
    with open_fn(index_request) as response:
        index_html = response.read().decode("latin-1", errors="replace")
    url = latest_atlantic_hurdat_url(index_html)
    file_request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_fn(file_request) as response:
        raw = response.read()
    dest_file.write_bytes(raw)
    return url


def write_hurdat_snapshot(dest_dir: Path, raw: bytes, source_url: str, retrieved_at: datetime) -> Path:
    if dest_dir.exists():
        raise FileExistsError(f"Snapshot already exists and will not be overwritten: {dest_dir}")
    dest_dir.mkdir(parents=True)
    (dest_dir / "hurdat2.txt").write_bytes(raw)
    meta = {
        "source": "NOAA NHC HURDAT2 Atlantic",
        "source_url": source_url,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": "hurdat2.txt",
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
        "natural_key": "storm_id|YYYYMMDD|HHMM|record_identifier",
    }
    (dest_dir / "snapshot.json").write_text(json.dumps(meta, indent=2) + "\n")
    return dest_dir


def load_hurdat_snapshot(snapshot_dir: Path) -> tuple[list[StormTrack], dict]:
    meta = json.loads((snapshot_dir / "snapshot.json").read_text())
    path = snapshot_dir / meta["file"]
    digest = sha256_file(path)
    if digest != meta["sha256"]:
        raise RuntimeError(f"HURDAT2 snapshot hash mismatch for {path}")
    storms = parse_hurdat2(path.read_text())
    return storms, meta
