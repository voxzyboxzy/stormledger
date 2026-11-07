#!/usr/bin/env bash
# One command: install if needed, build the ledger from bundled snapshots, serve the map.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import stormledger, fastapi, duckdb, pandera, sklearn" >/dev/null 2>&1; then
  python -m pip install -e ".[dev]"
fi

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm ci)
fi
if [[ ! -f frontend/dist/index.html ]]; then
  (cd frontend && npm run build)
fi

python -m stormledger.cli build
exec python -m stormledger.cli serve --host 127.0.0.1 --port "${PORT:-8000}"
