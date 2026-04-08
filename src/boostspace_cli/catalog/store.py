"""Catalog storage and loading helpers."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".boostspace-cli" / "catalog"
CACHE_REGISTRY_PATH = CACHE_DIR / "module_registry.json"


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_shipped_registry() -> dict[str, Any]:
    with resources.as_file(resources.files("boostspace_cli.data").joinpath("module_registry.json")) as path:
        return _load_json_file(path)


def load_native_modules() -> set[str]:
    with resources.as_file(resources.files("boostspace_cli.data").joinpath("native_modules.json")) as path:
        data = _load_json_file(path)
    modules = data.get("modules", [])
    return {str(item) for item in modules if str(item).strip()}


def validate_registry(registry: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    meta = registry.get("meta")
    modules = registry.get("modules")
    apps = registry.get("apps")

    if not isinstance(meta, dict):
        errors.append("Missing meta object")
    if not isinstance(modules, dict):
        errors.append("Missing modules object")
    if not isinstance(apps, dict):
        errors.append("Missing apps object")

    if isinstance(modules, dict):
        for module_id, module in modules.items():
            if not isinstance(module, dict):
                errors.append(f"Invalid module entry: {module_id}")
                continue
            if module.get("id") != module_id:
                errors.append(f"Module id mismatch: {module_id}")
            if not isinstance(module.get("app"), str):
                errors.append(f"Module missing app: {module_id}")

    return len(errors) == 0, errors


def load_cached_registry() -> dict[str, Any] | None:
    if not CACHE_REGISTRY_PATH.exists():
        return None
    try:
        data = _load_json_file(CACHE_REGISTRY_PATH)
    except Exception:
        return None
    valid, _ = validate_registry(data)
    if not valid:
        return None
    return data


def load_registry_with_source() -> tuple[dict[str, Any], str, Path | None]:
    cached = load_cached_registry()
    if cached is not None:
        return cached, "cache", CACHE_REGISTRY_PATH
    return load_shipped_registry(), "shipped", None


def save_cached_registry(registry: dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return CACHE_REGISTRY_PATH


def known_module_ids() -> set[str]:
    registry, _, _ = load_registry_with_source()
    modules = registry.get("modules", {})
    ids = set(modules.keys()) if isinstance(modules, dict) else set()
    return ids | load_native_modules()
