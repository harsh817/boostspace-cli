"""Helper utilities for scenario builder commands."""

from __future__ import annotations

from typing import Any

import click

from .client import APIClient, APIError
from .config import Config


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
    flow = blueprint.get("flow") or blueprint.get("modules") or []
    names: set[str] = set()
    if isinstance(flow, list):
        for module in flow:
            if isinstance(module, dict):
                mod = module.get("module")
                if isinstance(mod, str):
                    names.add(mod)
    return names


def tenant_known_modules(
    client: APIClient,
    team_id: int | None,
    organization_id: int | None,
    scan_limit: int,
) -> set[str]:
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

    return known


def parse_connection_pairs(connection_pairs: tuple[str, ...]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for pair in connection_pairs:
        if ":" not in pair:
            raise click.ClickException(f"--connection must be APP:ID (got '{pair}')")
        app, _, cid = pair.partition(":")
        app_name = app.strip().casefold()
        if not app_name:
            raise click.ClickException(f"Connection app cannot be empty (got '{pair}')")
        try:
            parsed[app_name] = int(cid.strip())
        except ValueError:
            raise click.ClickException(f"Connection ID must be an integer (got '{cid}')")
    return parsed


def team_connection_map(client: APIClient, team_id: int | None) -> dict[str, int]:
    result = client.list_connections(team_id=team_id)
    conns = result.get("connections", result if isinstance(result, list) else [])
    conn_map: dict[str, int] = {}
    if not isinstance(conns, list):
        return conn_map

    for conn in conns:
        if not isinstance(conn, dict):
            continue
        raw_app = conn.get("accountType") or conn.get("type") or ""
        conn_id = conn.get("id")
        if not raw_app or not isinstance(conn_id, int):
            continue
        app = str(raw_app).strip().casefold()
        conn_map.setdefault(app, conn_id)
    return conn_map


def normalize_schedule_type(value: str) -> str:
    normalized = value.strip().casefold()
    allowed = {"on-demand", "indefinitely", "once", "immediately"}
    if normalized not in allowed:
        raise click.ClickException(
            f"Invalid schedule type '{value}'. Use one of: on-demand, indefinitely, once, immediately."
        )
    return normalized
