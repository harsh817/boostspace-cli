"""Load shipped formula registry."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_formula_registry() -> dict[str, Any]:
    with resources.as_file(resources.files("boostspace_cli.data").joinpath("formula_registry.json")) as path:
        return _load_json(path)


def known_formula_functions() -> set[str]:
    registry = load_formula_registry()
    functions = registry.get("functions", {})
    if not isinstance(functions, dict):
        return set()
    return {str(name) for name in functions.keys()}
