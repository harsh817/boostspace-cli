"""Helper utilities for scenario builder commands."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import click

from .client import APIClient, APIError
from .config import Config

TENANT_MODULE_CACHE_PATH = Path.home() / ".boostspace-cli" / "cache" / "tenant_modules.json"


APP_ALIASES: dict[str, tuple[str, ...]] = {
    "hubspot": ("hubspot", "hubspotcrm", "hubspot-marketing-hub"),
    "google-sheets": ("google-sheets", "googlesheets", "gsheets", "google-sheet"),
    "openai-gpt-3": ("openai-gpt-3", "openai-gpt", "openai", "chatgpt"),
    "slack": ("slack",),
    "notion": ("notion",),
    "airtable": ("airtable",),
}

MODULE_CONNECTION_PREFERENCES: dict[str, tuple[str, ...]] = {
    "google-sheets:addRow": ("google", "google-sheets"),
    "google-sheets:addMultipleRows": ("google", "google-sheets"),
    "google-sheets:updateRow": ("google", "google-sheets"),
    "google-sheets:getSheetContent": ("google", "google-sheets"),
    "google-sheets:filterRows": ("google", "google-sheets"),
    "google-sheets:filterRowsAdvanced": ("google", "google-sheets"),
    "google-sheets:watchRows": ("google", "google-sheets"),
    "google-sheets:createSpreadsheet": ("google", "google-sheets"),
    "google-sheets:createASpreadsheetFromATemplate": ("google", "google-sheets"),
    "google-drive:getAFile": ("google-restricted", "google-drive", "google"),
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in APP_ALIASES.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in aliases:
        _ALIAS_TO_CANONICAL[alias] = canonical


def normalize_app_key(value: str) -> str:
    key = value.strip().casefold().replace("_", "-")
    if not key:
        return key
    key = key.replace(" ", "-")
    return _ALIAS_TO_CANONICAL.get(key, key)


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_team_id(client: APIClient, config: Config, requested_team_id: int | None) -> int:
    if requested_team_id:
        return requested_team_id
    if config.team_id:
        return config.team_id

    org_id = config.organization_id
    if not org_id:
        orgs = client.get("/organizations").get("organizations", [])
        if not orgs:
            raise click.ClickException("No organizations found for this account.")
        org_id = int(orgs[0]["id"])
        config.organization_id = org_id

    teams = client.list_teams(organization_id=org_id).get("teams", [])
    if not teams:
        raise click.ClickException(f"No teams found in organization {org_id}.")

    team_id = int(teams[0]["id"])
    config.team_id = team_id
    return team_id


def module_names_from_blueprint(blueprint: dict[str, object]) -> set[str]:
    names: set[str] = set()

    def walk(flow: object) -> None:
        if not isinstance(flow, list):
            return
        for module in flow:
            if not isinstance(module, dict):
                continue
            mod = module.get("module")
            if isinstance(mod, str):
                names.add(mod)

            routes = module.get("routes")
            if isinstance(routes, list):
                for route in routes:
                    if isinstance(route, dict):
                        walk(route.get("flow"))

    flow = blueprint.get("flow") or blueprint.get("modules") or []
    walk(flow)
    return names


def tenant_known_modules(
    client: APIClient,
    team_id: int | None,
    organization_id: int | None,
    scan_limit: int,
    use_cache: bool = True,
    refresh_cache: bool = False,
    cache_ttl_seconds: int = 1800,
    cache_path: Path | None = None,
) -> set[str]:
    resolved_cache_path = cache_path or TENANT_MODULE_CACHE_PATH
    cache_key = f"team:{team_id or 0}|org:{organization_id or 0}|limit:{int(scan_limit)}"

    if use_cache and not refresh_cache:
        cached = _load_cached_tenant_modules(
            cache_key,
            ttl_seconds=cache_ttl_seconds,
            cache_path=resolved_cache_path,
        )
        if cached is not None:
            return cached

    if scan_limit <= 0:
        return set()

    scenario_page = client.list_scenarios(team_id=team_id, organization_id=organization_id, limit=scan_limit)
    scenarios = scenario_page.get("scenarios", [])
    known: set[str] = set()

    for scenario in scenarios:
        sid = scenario.get("id")
        if not sid:
            continue
        try:
            blueprint = client.get_blueprint(int(sid))
        except APIError:
            continue

        if not isinstance(blueprint, dict):
            continue

        known |= module_names_from_blueprint(blueprint)

    if use_cache:
        _save_cached_tenant_modules(
            cache_key,
            modules=known,
            cache_path=resolved_cache_path,
            team_id=team_id,
            organization_id=organization_id,
            scan_limit=scan_limit,
        )

    return known


def _load_cached_tenant_modules(cache_key: str, ttl_seconds: int, cache_path: Path) -> set[str] | None:
    if ttl_seconds <= 0 or not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None

    entries = payload.get("entries", {})
    if not isinstance(entries, dict):
        return None
    entry = entries.get(cache_key)
    if not isinstance(entry, dict):
        return None

    scanned_at = entry.get("scannedAt")
    if not isinstance(scanned_at, int):
        return None

    age_seconds = int(time.time()) - scanned_at
    if age_seconds > ttl_seconds:
        return None

    modules = entry.get("modules", [])
    if not isinstance(modules, list):
        return None
    return {str(module) for module in modules if str(module).strip()}


def _save_cached_tenant_modules(
    cache_key: str,
    modules: set[str],
    cache_path: Path,
    team_id: int | None,
    organization_id: int | None,
    scan_limit: int,
) -> None:
    payload: dict[str, Any] = {"entries": {}}
    if cache_path.exists():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {"entries": {}}

    entries = payload.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        payload["entries"] = entries

    entries[cache_key] = {
        "teamId": team_id,
        "organizationId": organization_id,
        "scanLimit": int(scan_limit),
        "scannedAt": int(time.time()),
        "modules": sorted(modules, key=str.casefold),
    }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_connection_pairs(connection_pairs: tuple[str, ...]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for pair in connection_pairs:
        if ":" not in pair:
            raise click.ClickException(f"--connection must be APP:ID (got '{pair}')")
        app, _, cid = pair.partition(":")
        app_name = normalize_app_key(app)
        if not app_name:
            raise click.ClickException(f"Connection app cannot be empty (got '{pair}')")
        try:
            parsed[app_name] = int(cid.strip())
        except ValueError:
            raise click.ClickException(f"Connection ID must be an integer (got '{cid}')")
    return parsed


def _expanded_connection_keys(conn: dict[str, Any]) -> tuple[int | None, str, str, set[str], set[str]]:
    raw_app = conn.get("accountType") or conn.get("type") or ""
    raw_name = conn.get("accountName") or conn.get("name") or ""
    conn_id = conn.get("id")

    candidates: list[str] = []
    if raw_app:
        candidates.append(str(raw_app))
    if raw_name:
        candidates.append(str(raw_name))

    direct_keys: set[str] = set()
    expanded_keys: set[str] = set()
    for candidate in candidates:
        normalized = normalize_app_key(candidate)
        if not normalized:
            continue
        direct_keys.add(normalized)
        expanded_keys.add(normalized)

        # Some providers expose generic OAuth names in accountName/accountType
        # (for example: "google", "google-restricted", "slack2").
        # Expand those to native module app ids expected by blueprints.
        if normalized in {"google", "google-restricted"}:
            expanded_keys.update({"google-sheets", "google-drive", "google-docs", "google-calendar"})
        if normalized.startswith("slack"):
            expanded_keys.add("slack")

    return (conn_id if isinstance(conn_id, int) else None, str(raw_name), str(raw_app), direct_keys, expanded_keys)


def connection_compatibility_rows(client: APIClient, team_id: int | None, module_name: str) -> list[dict[str, Any]]:
    result = client.list_connections(team_id=team_id)
    conns = result.get("connections", result if isinstance(result, list) else [])
    if not isinstance(conns, list):
        return []

    app = module_name.split(":", 1)[0].strip().casefold() if ":" in module_name else module_name.strip().casefold()
    preferred_aliases = tuple(normalize_app_key(item) for item in MODULE_CONNECTION_PREFERENCES.get(module_name, ()))

    rows: list[dict[str, Any]] = []
    for conn in conns:
        if not isinstance(conn, dict):
            continue
        conn_id, raw_name, raw_app, direct_keys, expanded_keys = _expanded_connection_keys(conn)
        if conn_id is None:
            continue

        reason = "app_mismatch"
        compatible = False
        score = 999
        matched_key = ""

        has_module_preferences = module_name in MODULE_CONNECTION_PREFERENCES
        if has_module_preferences:
            for priority, alias in enumerate(preferred_aliases):
                if alias in direct_keys:
                    compatible = True
                    score = priority
                    matched_key = alias
                    reason = "module_preference"
                    break

        if not compatible and not has_module_preferences and app in expanded_keys:
            compatible = True
            score = 100
            matched_key = app
            reason = "app_family"

        rows.append(
            {
                "id": conn_id,
                "name": raw_name or conn.get("name") or "",
                "app": raw_app or conn.get("type") or "",
                "compatible": compatible,
                "reason": reason,
                "matchedKey": matched_key or None,
                "score": score,
            }
        )

    rows.sort(key=lambda row: (not bool(row["compatible"]), int(row["score"]), str(row["name"]).casefold(), int(row["id"])))
    return rows


def team_connection_map(client: APIClient, team_id: int | None) -> dict[str, int]:
    result = client.list_connections(team_id=team_id)
    conns = result.get("connections", result if isinstance(result, list) else [])
    conn_map: dict[str, int] = {}
    module_best: dict[str, tuple[int, int]] = {}
    if not isinstance(conns, list):
        return conn_map

    for conn in conns:
        if not isinstance(conn, dict):
            continue
        conn_id, _raw_name, _raw_app, _direct_keys, expanded_keys = _expanded_connection_keys(conn)
        if conn_id is None:
            continue

        for normalized in expanded_keys:
            conn_map.setdefault(normalized, conn_id)

            # Add alias keys for ergonomic lookups
            for alias, canonical in _ALIAS_TO_CANONICAL.items():
                if canonical == normalized:
                    conn_map.setdefault(alias, conn_id)

        for module_name, preferred_aliases in MODULE_CONNECTION_PREFERENCES.items():
            for priority, preferred_alias in enumerate(preferred_aliases):
                normalized_alias = normalize_app_key(preferred_alias)
                if normalized_alias in expanded_keys:
                    current = module_best.get(module_name)
                    if current is None or priority < current[0]:
                        module_best[module_name] = (priority, conn_id)
                    break

    for module_name, (_priority, conn_id) in module_best.items():
        conn_map[module_name] = conn_id
    return conn_map


def normalize_schedule_type(value: str) -> str:
    normalized = value.strip().casefold()
    allowed = {"on-demand", "indefinitely", "once", "immediately"}
    if normalized not in allowed:
        raise click.ClickException(
            f"Invalid schedule type '{value}'. Use one of: on-demand, indefinitely, once, immediately."
        )
    return normalized
