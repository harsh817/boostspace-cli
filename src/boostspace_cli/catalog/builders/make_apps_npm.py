"""Build module registry from extracted @make-org/apps package files."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9_-]*$")


def _is_module_id(value: Any) -> bool:
    return isinstance(value, str) and bool(MODULE_ID_RE.match(value.strip()))


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
            continue
        files.append(path)
    return files


def _load_structured(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.casefold() == ".json":
        return json.loads(raw)
    return yaml.safe_load(raw)


def _extract_mapper_fields(node: dict[str, Any]) -> list[str]:
    fields: set[str] = set()
    mapper = node.get("mapper")
    if isinstance(mapper, dict):
        fields.update(str(key) for key in mapper.keys())

    expect = node.get("expect")
    if isinstance(expect, list):
        for item in expect:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                fields.add(item["name"])

    return sorted(fields)


def _record_module(
    modules: dict[str, dict[str, Any]],
    module_id: str,
    node: dict[str, Any] | None,
    file_hint: str,
) -> None:
    app, _, action = module_id.partition(":")
    title = action
    versions: set[int] = set()
    mapper_fields: set[str] = set()

    if node:
        if isinstance(node.get("title"), str):
            title = str(node["title"])
        elif isinstance(node.get("label"), str):
            title = str(node["label"])
        elif isinstance(node.get("name"), str) and not _is_module_id(node["name"]):
            title = str(node["name"])

        version = node.get("version")
        if isinstance(version, int):
            versions.add(version)
        elif isinstance(version, str) and version.isdigit():
            versions.add(int(version))

        mapper_fields.update(_extract_mapper_fields(node))

    existing = modules.get(module_id)
    if existing is None:
        modules[module_id] = {
            "id": module_id,
            "app": app,
            "name": action,
            "title": title,
            "latestVersion": max(versions) if versions else 1,
            "versions": sorted(versions) if versions else [1],
            "mapperFields": sorted(mapper_fields),
            "sources": [file_hint],
        }
        return

    merged_versions = set(existing.get("versions", [])) | versions
    merged_fields = set(existing.get("mapperFields", [])) | mapper_fields
    existing["versions"] = sorted(merged_versions) if merged_versions else [1]
    existing["latestVersion"] = max(existing["versions"])
    existing["mapperFields"] = sorted(merged_fields)
    existing_sources = existing.get("sources", [])
    if isinstance(existing_sources, list) and file_hint not in existing_sources:
        existing_sources.append(file_hint)
        existing["sources"] = existing_sources


def _scan_node(node: Any, modules: dict[str, dict[str, Any]], file_hint: str) -> None:
    if isinstance(node, dict):
        module_value = node.get("module")
        if _is_module_id(module_value):
            _record_module(modules, str(module_value), node, file_hint)

        for key, value in node.items():
            if key in {"id", "name", "type", "moduleId", "module"} and _is_module_id(value):
                _record_module(modules, str(value), node, file_hint)

            if isinstance(value, str) and _is_module_id(value):
                _record_module(modules, value, node, file_hint)
            else:
                _scan_node(value, modules, file_hint)
        return

    if isinstance(node, list):
        for item in node:
            _scan_node(item, modules, file_hint)


def build_registry_from_extracted_package(root: Path) -> dict[str, Any]:
    package_root = root / "package"
    if not package_root.exists():
        package_root = root

    package_version = "unknown"
    package_json = package_root / "package.json"
    if package_json.exists():
        try:
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            package_version = str(package_data.get("version", "unknown"))
        except Exception:
            package_version = "unknown"

    modules: dict[str, dict[str, Any]] = {}
    candidates = _candidate_files(package_root)
    for file_path in candidates:
        file_hint = str(file_path.relative_to(package_root))
        try:
            data = _load_structured(file_path)
        except Exception:
            continue
        _scan_node(data, modules, file_hint)

    apps: dict[str, dict[str, Any]] = {}
    for module_id, entry in modules.items():
        app = str(entry.get("app", ""))
        if not app:
            continue
        app_entry = apps.setdefault(app, {"id": app, "title": app, "moduleIds": []})
        app_entry["moduleIds"].append(module_id)

    for app_entry in apps.values():
        app_entry["moduleIds"] = sorted(set(app_entry["moduleIds"]), key=str.casefold)

    for entry in modules.values():
        entry.pop("sources", None)

    return {
        "meta": {
            "source": "@make-org/apps",
            "generatedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "packageVersion": package_version,
            "moduleCount": len(modules),
            "appCount": len(apps),
        },
        "modules": dict(sorted(modules.items(), key=lambda item: item[0].casefold())),
        "apps": dict(sorted(apps.items(), key=lambda item: item[0].casefold())),
    }
