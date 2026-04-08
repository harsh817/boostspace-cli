"""Template catalog helpers sourced from make.com templates pages."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from .store import CACHE_DIR

TEMPLATE_REGISTRY_PATH = CACHE_DIR / "template_registry.json"
DEFAULT_TEMPLATES_URL = "https://www.make.com/en/templates"

_ANCHOR_RE = re.compile(
    r"<a[^>]+href=[\"'](?P<href>/en/templates/[^\"'#?]+)[\"'][^>]*>(?P<body>.*?)</a>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>", flags=re.DOTALL)
_SPACE_RE = re.compile(r"\s+")
_APP_ALT_RE = re.compile(r"alt=[\"'](?P<alt>[^\"']+)[\"']", flags=re.IGNORECASE)


def _strip_html(value: str) -> str:
    without_tags = _TAG_RE.sub(" ", value)
    return _SPACE_RE.sub(" ", without_tags).strip()


def _extract_apps(snippet: str) -> list[str]:
    apps: list[str] = []
    seen: set[str] = set()
    for match in _APP_ALT_RE.finditer(snippet):
        alt = _SPACE_RE.sub(" ", match.group("alt")).strip()
        if not alt:
            continue
        alt_cf = alt.casefold()
        if "logo" in alt_cf or alt_cf in {"make", "make.com"}:
            continue
        if alt_cf in seen:
            continue
        seen.add(alt_cf)
        apps.append(alt)
    return apps


def parse_templates_html(html: str, base_url: str = DEFAULT_TEMPLATES_URL) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for match in _ANCHOR_RE.finditer(html):
        href = match.group("href").strip()
        # Keep concrete template pages only; skip category and top-level listing links.
        parts = [segment for segment in href.split("/") if segment]
        if len(parts) < 3:
            continue
        slug = parts[-1]
        if slug in {"templates", "all", "categories"}:
            continue

        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue

        body = match.group("body")
        title = _strip_html(body)
        if len(title) < 4:
            title = slug.replace("-", " ").strip()

        start = max(0, match.start() - 1000)
        end = min(len(html), match.end() + 1000)
        context = html[start:end]
        apps = _extract_apps(context)

        templates.append(
            {
                "slug": slug,
                "url": full_url,
                "title": title,
                "apps": apps,
            }
        )
        seen_urls.add(full_url)

    templates.sort(key=lambda item: str(item.get("title", "")).casefold())
    return templates


def build_template_registry(templates_url: str = DEFAULT_TEMPLATES_URL, timeout: float = 20.0) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(templates_url)
        response.raise_for_status()

    templates = parse_templates_html(response.text, base_url=templates_url)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "meta": {
            "source": "make-templates-web",
            "generatedAt": now,
            "templateCount": len(templates),
            "url": templates_url,
        },
        "templates": templates,
    }


def save_template_registry(registry: dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return TEMPLATE_REGISTRY_PATH


def load_template_registry() -> tuple[dict[str, Any] | None, str, Path | None]:
    if not TEMPLATE_REGISTRY_PATH.exists():
        return None, "missing", None
    try:
        payload = json.loads(TEMPLATE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid", TEMPLATE_REGISTRY_PATH

    if not isinstance(payload, dict) or not isinstance(payload.get("templates"), list):
        return None, "invalid", TEMPLATE_REGISTRY_PATH
    return payload, "cache", TEMPLATE_REGISTRY_PATH


def search_templates(
    registry: dict[str, Any],
    query: str | None = None,
    app: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = registry.get("templates", [])
    if not isinstance(rows, list):
        return []

    q = query.casefold().strip() if query else ""
    app_cf = app.casefold().strip() if app else ""

    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        apps = row.get("apps", [])
        app_values = [str(item) for item in apps] if isinstance(apps, list) else []
        if app_cf and not any(app_cf in value.casefold() for value in app_values):
            continue

        if q:
            haystack = " ".join(
                [
                    str(row.get("title", "")),
                    str(row.get("slug", "")),
                    str(row.get("url", "")),
                    " ".join(app_values),
                ]
            ).casefold()
            if q not in haystack:
                continue

        matches.append(row)

    return matches[: max(1, int(limit))]
