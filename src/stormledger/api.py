"""Read-only API over curated artifacts. It does not call OpenFEMA or refit the model."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from stormledger.constants import RESEARCH_BANNER
from stormledger.paths import default_curated_dir, repo_root


def _read(path: Path):
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Missing curated artifact {path.name}")
    return json.loads(path.read_text())


def create_app(curated_dir: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    curated = curated_dir or default_curated_dir()
    static = static_dir if static_dir is not None else repo_root() / "frontend" / "dist"
    app = FastAPI(title="StormLedger", version="0.1.0", description=RESEARCH_BANNER)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/api/health")
    def health():
        return {
            "ok": curated.joinpath("metrics.json").is_file(),
            "research_demonstration": True,
            "not_emergency_guidance": True,
            "banner": RESEARCH_BANNER,
        }

    @app.get("/api/summary")
    def summary():
        return _read(curated / "summary.json")

    @app.get("/api/metrics")
    def metrics():
        return _read(curated / "metrics.json")

    @app.get("/api/quality")
    def quality():
        return _read(curated / "quality.json")

    @app.get("/api/model-card")
    def model_card():
        path = curated / "model_card.md"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Model card has not been built")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(path.read_text())

    @app.get("/api/counties.geojson")
    def counties():
        return _read(curated / "counties.geojson")

    @app.get("/api/storms/{storm_id}/frames")
    def frames(storm_id: str):
        return _read(curated / "frames" / f"{storm_id}.json")

    @app.get("/api/storms/{storm_id}/provenance")
    def provenance(storm_id: str):
        return _read(curated / "provenance" / f"{storm_id}.json")

    @app.get("/api/storms/{storm_id}/counties/{county_fips}")
    def county(storm_id: str, county_fips: str):
        payload = _read(curated / "provenance" / f"{storm_id}.json")
        row = payload["counties"].get(county_fips)
        if row is None:
            raise HTTPException(status_code=404, detail="County is not in this storm ledger")
        return row

    if static.is_dir() and (static / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app
