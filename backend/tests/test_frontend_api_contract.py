"""Static integration guard: every Web API call must map to a registered backend route."""
from __future__ import annotations

import re
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
WEB_FILES = (
    ROOT / "apps" / "web" / "app.js",
    ROOT / "apps" / "web" / "signal-tool.js",
    ROOT / "apps" / "web" / "workspace-pages.js",
    ROOT / "apps" / "web" / "prop-challenge.js",
)
CALL = re.compile(r"""\b(?:apiRequest|api)\s*\(\s*["'`]([^"'`]+)["'`]""")
DIRECT_FETCH = re.compile(r"""\bfetch\s*\(\s*["'`]http://127\.0\.0\.1:8000([^"'`]+)["'`]""")


def _route_covers(request_path: str, route_path: str) -> bool:
    path = request_path.split("?", 1)[0]
    if path == route_path or route_path.startswith(path):
        return True
    route_prefix = route_path.split("{", 1)[0]
    return bool(route_prefix and path.startswith(route_prefix))


def test_every_web_backend_api_call_has_a_registered_route() -> None:
    registered = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/")
    }
    calls: list[tuple[str, str]] = []
    for source in WEB_FILES:
        text = source.read_text(encoding="utf-8")
        for match in CALL.finditer(text):
            path = match.group(1)
            if path.startswith("/api/v1/"):
                calls.append((str(source.relative_to(ROOT)), path))
        for match in DIRECT_FETCH.finditer(text):
            path = match.group(1)
            if path.startswith("/api/v1/"):
                calls.append((str(source.relative_to(ROOT)), path))

    assert calls, "Expected to discover Web-to-backend API calls."
    missing = [
        f"{source}: {path}"
        for source, path in calls
        if not any(_route_covers(path, route) for route in registered)
    ]
    assert not missing, "Web calls without a registered FastAPI route:\n" + "\n".join(missing)
