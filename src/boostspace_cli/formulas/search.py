"""Formula registry search helpers."""

from __future__ import annotations

from typing import Any


def search_functions(registry: dict[str, Any], query: str, limit: int = 20) -> list[dict[str, Any]]:
    functions = registry.get("functions", {})
    if not isinstance(functions, dict):
        return []

    q = query.casefold()
    rows: list[tuple[int, dict[str, Any]]] = []
    for name, data in functions.items():
        if not isinstance(data, dict):
            continue
        score = 0
        name_cf = str(name).casefold()
        desc_cf = str(data.get("description", "")).casefold()
        if name_cf == q:
            score = 100
        elif name_cf.startswith(q):
            score = 80
        elif q in name_cf:
            score = 60
        elif q in desc_cf:
            score = 40
        if score == 0:
            continue
        payload = {
            "name": str(name),
            "signature": data.get("signature"),
            "description": data.get("description"),
        }
        rows.append((score, payload))

    rows.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
    return [item[1] for item in rows[: max(1, int(limit))]]


def function_detail(registry: dict[str, Any], name: str) -> dict[str, Any] | None:
    functions = registry.get("functions", {})
    if not isinstance(functions, dict):
        return None
    details = functions.get(name)
    if not isinstance(details, dict):
        return None
    payload = dict(details)
    payload.setdefault("name", name)
    return payload
