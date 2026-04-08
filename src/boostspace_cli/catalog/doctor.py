"""Catalog diagnostic helpers."""

from __future__ import annotations

from typing import Any

from .store import load_cached_registry, load_registry_with_source, validate_registry


def catalog_doctor() -> dict[str, Any]:
    registry, source, path = load_registry_with_source()
    valid, errors = validate_registry(registry)

    modules = registry.get("modules", {}) if isinstance(registry, dict) else {}
    apps = registry.get("apps", {}) if isinstance(registry, dict) else {}
    meta = registry.get("meta", {}) if isinstance(registry, dict) else {}

    return {
        "ok": valid,
        "source": source,
        "cacheAvailable": load_cached_registry() is not None,
        "path": str(path) if path else None,
        "moduleCount": len(modules) if isinstance(modules, dict) else 0,
        "appCount": len(apps) if isinstance(apps, dict) else 0,
        "packageVersion": meta.get("packageVersion", "unknown") if isinstance(meta, dict) else "unknown",
        "errors": errors,
    }
