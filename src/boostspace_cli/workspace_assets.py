"""Workspace template and folder parsing helpers."""

from __future__ import annotations

from typing import Any


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _first_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    nested = payload.get("response")
    if nested is not None:
        return _first_list(nested, keys)
    return []


def extract_templates(payload: Any) -> list[dict[str, Any]]:
    rows = _first_list(payload, ("templates", "scenarioTemplates", "items", "data", "results"))
    templates: list[dict[str, Any]] = []
    for row in rows:
        template_id = row.get("id")
        name = _normalize_text(row.get("name") or row.get("title") or row.get("label") or f"template:{template_id}")
        if not name:
            continue

        is_public = row.get("isPublic")
        if isinstance(is_public, str):
            is_public = is_public.strip().casefold() in {"1", "true", "yes", "public"}
        elif not isinstance(is_public, bool):
            visibility = _normalize_text(row.get("visibility")).casefold()
            if visibility:
                is_public = visibility in {"public", "workspace_public"}
            else:
                is_public = None

        templates.append(
            {
                "id": template_id,
                "name": name,
                "description": _normalize_text(row.get("description")),
                "public": is_public,
                "teamId": _coerce_int(row.get("teamId")),
                "organizationId": _coerce_int(row.get("organizationId") or row.get("orgId")),
                "folderId": _coerce_int(row.get("folderId")),
                "url": _normalize_text(row.get("url")),
            }
        )

    templates.sort(key=lambda item: item["name"].casefold())
    return templates


def search_templates(
    templates: list[dict[str, Any]],
    query: str | None = None,
    public_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    q = _normalize_text(query).casefold()
    scored: list[tuple[int, dict[str, Any]]] = []

    for row in templates:
        if public_only and row.get("public") is False:
            continue

        name = _normalize_text(row.get("name"))
        description = _normalize_text(row.get("description"))
        haystack = f"{name} {description}".casefold()

        if not q:
            score = 1
        elif haystack == q:
            score = 100
        elif haystack.startswith(q):
            score = 80
        elif q in haystack:
            score = 60
        else:
            score = 0

        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: (-item[0], _normalize_text(item[1].get("name")).casefold()))
    max_items = max(1, int(limit))
    return [item[1] for item in scored[:max_items]]


def extract_folders(payload: Any) -> list[dict[str, Any]]:
    rows = _first_list(payload, ("folders", "scenarioFolders", "items", "data", "results"))
    folders: list[dict[str, Any]] = []
    for row in rows:
        folder_id = row.get("id")
        name = _normalize_text(row.get("name") or row.get("title") or row.get("label"))
        if not name:
            continue

        parent_id = row.get("parentId") or row.get("parentFolderId")
        if parent_id is None and isinstance(row.get("parent"), dict):
            parent_id = row["parent"].get("id")

        folders.append(
            {
                "id": _coerce_int(folder_id) or folder_id,
                "name": name,
                "parentId": _coerce_int(parent_id) or parent_id,
                "teamId": _coerce_int(row.get("teamId")),
                "organizationId": _coerce_int(row.get("organizationId") or row.get("orgId")),
            }
        )

    folders.sort(key=lambda item: _normalize_text(item.get("name")).casefold())
    return folders


def find_folder_by_name(folders: list[dict[str, Any]], name: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    target = _normalize_text(name).casefold()
    if not target:
        return None, []

    exact = [row for row in folders if _normalize_text(row.get("name")).casefold() == target]
    if exact:
        return exact[0], exact

    contains = [row for row in folders if target in _normalize_text(row.get("name")).casefold()]
    if len(contains) == 1:
        return contains[0], contains
    return None, contains
