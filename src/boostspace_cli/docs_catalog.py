"""Boost docs app catalog fetch + matching helpers."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DOCS_MODULES_URL = "https://docs.boost.space/knowledge-base/bse-database/modules-boost-space/boost-space-modules/"
DOCS_INTEGRATIONS_URL = "https://docs.boost.space/knowledge-base/system/bs-integrations/"
DOCS_SOURCE_URLS = (DOCS_MODULES_URL, DOCS_INTEGRATIONS_URL)
APP_LINK_RE = re.compile(
    r"https://docs\.boost\.space/knowledge-base/applications/[a-z0-9-]+/([a-z0-9][a-z0-9-]{1,100})/",
    re.IGNORECASE,
)
FEATURE_LINK_RE = re.compile(
    r"https://docs\.boost\.space/knowledge-base/(?:system/features|system/connections|integrations|system/business-cases-addon)/[^\s)]+"
)
CATALOG_CACHE_PATH = Path.home() / ".boostspace-cli" / "docs-app-catalog.json"

_GENERIC_SUFFIXES = ("crm", "api", "app", "ai", "io", "com")


def extract_app_slugs(markdown_or_html: str) -> set[str]:
    slugs = {slug.strip().casefold() for slug in APP_LINK_RE.findall(markdown_or_html) if slug.strip()}
    return {slug for slug in slugs if slug not in {"ai", "built-in-apps"}}


def extract_feature_slugs(markdown_or_html: str) -> set[str]:
    slugs: set[str] = set()
    for link in FEATURE_LINK_RE.findall(markdown_or_html):
        cleaned = link.rstrip("/")
        if not cleaned:
            continue
        leaf = cleaned.rsplit("/", 1)[-1].strip().casefold()
        if leaf:
            slugs.add(leaf)
    return slugs


def _fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "boostspace-cli/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed trusted domain)
        return response.read().decode("utf-8", errors="replace")


def fetch_documented_catalog(timeout: int = 30) -> dict[str, Any]:
    apps: set[str] = set()
    features: set[str] = set()
    source_counts: dict[str, dict[str, int]] = {}

    for source in DOCS_SOURCE_URLS:
        text = _fetch_text(source, timeout=timeout)
        source_apps = extract_app_slugs(text)
        source_features = extract_feature_slugs(text)
        apps |= source_apps
        features |= source_features
        source_counts[source] = {
            "apps": len(source_apps),
            "features": len(source_features),
        }

    return {
        "apps": apps,
        "features": features,
        "sourceCounts": source_counts,
    }


def load_documented_app_slugs(refresh: bool = False, max_age_seconds: int = 86400) -> set[str]:
    if not refresh and CATALOG_CACHE_PATH.exists():
        try:
            cached = json.loads(CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
            fetched_at = int(cached.get("fetchedAt", 0))
            if int(time.time()) - fetched_at <= max_age_seconds:
                apps = cached.get("apps", [])
                if isinstance(apps, list):
                    return {str(app).casefold() for app in apps if str(app).strip()}
        except Exception:
            pass

    try:
        catalog = fetch_documented_catalog()
    except (HTTPError, URLError, TimeoutError):
        if CATALOG_CACHE_PATH.exists():
            try:
                cached = json.loads(CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
                apps = cached.get("apps", [])
                if isinstance(apps, list):
                    return {str(app).casefold() for app in apps if str(app).strip()}
            except Exception:
                return set()
        return set()

    apps = catalog.get("apps", set())
    features = catalog.get("features", set())
    source_counts = catalog.get("sourceCounts", {})

    CATALOG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "sources": list(DOCS_SOURCE_URLS),
        "sourceCounts": source_counts,
        "fetchedAt": int(time.time()),
        "apps": sorted(apps),
        "features": sorted(features),
    }
    CATALOG_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {str(app).casefold() for app in apps if str(app).strip()}


def load_documented_features(refresh: bool = False, max_age_seconds: int = 86400) -> set[str]:
    _ = load_documented_app_slugs(refresh=refresh, max_age_seconds=max_age_seconds)
    if not CATALOG_CACHE_PATH.exists():
        return set()
    try:
        cached = json.loads(CATALOG_CACHE_PATH.read_text(encoding="utf-8"))
        features = cached.get("features", [])
        if isinstance(features, list):
            return {str(item).casefold() for item in features if str(item).strip()}
    except Exception:
        return set()
    return set()


def match_goal_apps(goal: str, app_slugs: set[str]) -> set[str]:
    goal_lc = goal.casefold()
    matched: set[str] = set()

    def aliases(slug: str) -> set[str]:
        base = slug.casefold().strip()
        if not base:
            return set()
        parts = [part for part in base.split("-") if part]
        variants = {base, base.replace("-", " ")}
        stripped_parts: list[str] = []
        for part in parts:
            stripped = part
            for suffix in _GENERIC_SUFFIXES:
                if stripped.endswith(suffix) and len(stripped) > len(suffix) + 2:
                    stripped = stripped[: -len(suffix)]
                    break
            stripped_parts.append(stripped)
        if stripped_parts:
            variants.add(" ".join(stripped_parts))
        return {variant.strip() for variant in variants if len(variant.strip()) >= 4}

    for slug in app_slugs:
        for phrase in aliases(slug):
            if re.search(rf"\b{re.escape(phrase)}\b", goal_lc):
                matched.add(slug)
                break

    # Prefer specific slugs over generic root matches (e.g., google-sheets over google)
    reduced = set(matched)
    for slug in matched:
        if any(other != slug and other.startswith(slug + "-") for other in matched):
            reduced.discard(slug)
    return reduced
