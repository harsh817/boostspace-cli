"""Search helpers for module catalog."""

from __future__ import annotations

from typing import Any


def _score(query: str, module_id: str, title: str) -> int:
    q = query.casefold()
    module_cf = module_id.casefold()
    title_cf = title.casefold()

    if module_cf == q:
        return 1000
    if module_cf.startswith(q):
        return 700
    if q in module_cf:
        return 500
    if title_cf.startswith(q):
        return 450
    if q in title_cf:
        return 350

    overlap = sum(1 for token in q.split() if token and token in module_cf)
    return overlap * 100


def search_modules(
    registry: dict[str, Any],
    query: str,
    app: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    modules = registry.get("modules", {})
    if not isinstance(modules, dict):
        return []

    app_filter = app.casefold() if app else None
    scored: list[tuple[int, dict[str, Any]]] = []

    for module_id, entry in modules.items():
        if not isinstance(entry, dict):
            continue
        module_app = str(entry.get("app", "")).casefold()
        if app_filter and app_filter != module_app:
            continue

        title = str(entry.get("title", entry.get("name", module_id)))
        rank = _score(query, module_id, title)
        if rank <= 0:
            continue

        payload = {
            "id": module_id,
            "app": entry.get("app"),
            "title": title,
            "latestVersion": entry.get("latestVersion"),
            "versions": entry.get("versions", []),
            "mapperFields": entry.get("mapperFields", []),
        }
        scored.append((rank, payload))

    scored.sort(key=lambda item: (-item[0], str(item[1].get("id", "")).casefold()))
    return [item[1] for item in scored[: max(1, int(limit))]]


def module_detail(registry: dict[str, Any], module_id: str) -> dict[str, Any] | None:
    modules = registry.get("modules", {})
    if not isinstance(modules, dict):
        return None
    entry = modules.get(module_id)
    if not isinstance(entry, dict):
        return None
    payload = dict(entry)
    payload.setdefault("id", module_id)
    return payload
