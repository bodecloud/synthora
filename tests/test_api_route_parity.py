"""CI guard: REST /api/v1 routes must appear in SDK + web client sources."""

from __future__ import annotations

import re
from pathlib import Path

import synthora.api.main as api_main

ROOT = Path(__file__).resolve().parents[1]
SDK_SYNC = ROOT / "packages/sdk/src/synthora/sdk/client.py"
SDK_ASYNC = ROOT / "packages/sdk/src/synthora/sdk/async_client.py"
WEB_API = ROOT / "apps/web/src/api.ts"


def _api_v1_paths() -> set[str]:
    """REST paths from OpenAPI (includes routes mounted via include_router)."""
    paths = {
        path
        for path in api_main.app.openapi()["paths"]
        if path.startswith("/api/v1")
    }
    return paths


def _normalize_for_source_match(path: str) -> str:
    """Turn ``/api/v1/research/{run_id}/report`` into a regex fragment."""
    escaped = re.escape(path)
    escaped = re.sub(r"\\{[^}]+\\}", r"[^/\"'`]+", escaped)
    return escaped


def _source_covers(path: str, source: str) -> bool:
    pattern = _normalize_for_source_match(path)
    return re.search(pattern, source) is not None


def test_api_routes_exist_in_fastapi():
    paths = _api_v1_paths()
    assert len(paths) >= 30
    assert "/api/v1/research" in paths
    assert "/api/v1/mcp/tools/list" in paths


def test_sync_sdk_covers_all_api_v1_routes():
    source = SDK_SYNC.read_text(encoding="utf-8")
    missing = [p for p in sorted(_api_v1_paths()) if not _source_covers(p, source)]
    assert missing == [], f"sync SDK missing routes: {missing}"


def test_async_sdk_covers_all_api_v1_routes():
    source = SDK_ASYNC.read_text(encoding="utf-8")
    missing = [p for p in sorted(_api_v1_paths()) if not _source_covers(p, source)]
    assert missing == [], f"async SDK missing routes: {missing}"


def test_web_api_ts_covers_all_api_v1_routes():
    source = WEB_API.read_text(encoding="utf-8")
    missing = [p for p in sorted(_api_v1_paths()) if not _source_covers(p, source)]
    assert missing == [], f"web api.ts missing routes: {missing}"


def test_sync_and_async_sdk_public_surface_parity():
    """Async client should expose the same REST helpers as sync (except lifecycle)."""
    sync_src = SDK_SYNC.read_text(encoding="utf-8")
    async_src = SDK_ASYNC.read_text(encoding="utf-8")

    sync_methods = set(re.findall(r"^\s+def (\w+)\(", sync_src, re.MULTILINE))
    async_methods = set(re.findall(r"^\s+async def (\w+)\(", async_src, re.MULTILINE))

    non_rest_helpers = {
        "__init__",
        "_headers",
        "close",
        "aclose",
        "__aenter__",
        "__aexit__",
        "events_ws_url",
        "export_url",
    }
    sync_only = sync_methods - async_methods - non_rest_helpers
    async_only = async_methods - sync_methods - non_rest_helpers

    assert sync_only == set(), f"sync-only methods: {sync_only}"
    assert async_only == set(), f"async-only methods: {async_only}"
