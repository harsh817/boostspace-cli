"""Lint helpers for formula usage in blueprint mappings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
FUNC_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _extract_blueprint(payload: dict[str, Any]) -> dict[str, Any]:
    blueprint = payload.get("blueprint")
    if isinstance(blueprint, dict):
        return blueprint
    return payload


def _iter_string_nodes(node: Any) -> list[str]:
    values: list[str] = []
    if isinstance(node, dict):
        for value in node.values():
            values.extend(_iter_string_nodes(value))
    elif isinstance(node, list):
        for item in node:
            values.extend(_iter_string_nodes(item))
    elif isinstance(node, str):
        values.append(node)
    return values


def lint_formula_usage(payload: dict[str, Any], known_functions: set[str]) -> dict[str, Any]:
    blueprint = _extract_blueprint(payload)
    strings = _iter_string_nodes(blueprint)

    seen_calls: dict[str, int] = {}
    unknown_calls: dict[str, int] = {}
    for text in strings:
        for placeholder in PLACEHOLDER_RE.findall(text):
            for func in FUNC_CALL_RE.findall(placeholder):
                func_name = str(func)
                seen_calls[func_name] = seen_calls.get(func_name, 0) + 1
                if func_name not in known_functions:
                    unknown_calls[func_name] = unknown_calls.get(func_name, 0) + 1

    return {
        "ok": len(unknown_calls) == 0,
        "calls": [{"name": name, "count": count} for name, count in sorted(seen_calls.items(), key=lambda item: item[0].casefold())],
        "unknown": [{"name": name, "count": count} for name, count in sorted(unknown_calls.items(), key=lambda item: item[0].casefold())],
    }


def lint_formula_file(file_path: Path, known_functions: set[str]) -> dict[str, Any]:
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Blueprint file must contain a JSON object")
    result = lint_formula_usage(payload, known_functions)
    result["file"] = str(file_path)
    return result
