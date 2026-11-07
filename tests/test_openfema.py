"""Pagination and immutable snapshots, with a fake HTTP opener."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from stormledger.ingest.openfema import build_page_url, fetch_all_pages, load_snapshot_records, write_snapshot


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_pagination_follows_skip_until_count(tmp_path):
    seen: list[str] = []

    def opener(request):
        seen.append(request.full_url)
        query = request.full_url.split("?", 1)[1]
        skip = int(dict(part.split("=") for part in query.split("&"))["%24skip"])
        if skip == 0:
            rows = [{"disasterNumber": 1, "placeCode": "99001"}, {"disasterNumber": 1, "placeCode": "99003"}]
        elif skip == 2:
            rows = [{"disasterNumber": 2, "placeCode": "99005"}]
        else:
            raise AssertionError(f"unexpected skip {skip}")
        payload = {
            "metadata": {"count": 3, "skip": skip, "top": 2},
            "DisasterDeclarationsSummaries": rows,
        }
        return _Response(json.dumps(payload).encode())

    pages = fetch_all_pages(
        "DisasterDeclarationsSummaries",
        "state eq 'FL'",
        page_size=2,
        opener=opener,
    )
    assert len(pages) == 2
    assert len(seen) == 2
    records = []
    for page in pages:
        records.extend(json.loads(page)["DisasterDeclarationsSummaries"])
    assert [row["placeCode"] for row in records] == ["99001", "99003", "99005"]
    dest = write_snapshot(
        tmp_path / "snap",
        entity="DisasterDeclarationsSummaries",
        filter_expr="state eq 'FL'",
        pages=pages,
        retrieved_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
    )
    loaded, meta = load_snapshot_records(dest, "DisasterDeclarationsSummaries")
    assert len(loaded) == 3
    assert meta["record_count"] == 3
    with pytest.raises(FileExistsError):
        write_snapshot(
            dest,
            entity="DisasterDeclarationsSummaries",
            filter_expr="state eq 'FL'",
            pages=pages,
        )


def test_page_url_encodes_filter():
    url = build_page_url("HousingAssistanceOwners", "state eq 'FL'", 1000, 2000)
    assert "HousingAssistanceOwners" in url
    assert "%24skip=2000" in url or "$skip=2000" in url
