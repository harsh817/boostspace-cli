"""Scenario lookup helpers for ID/name resolution."""

from difflib import get_close_matches
from typing import Any, Optional

import click


def resolve_scenario_id(
    client: Any,
    team_id: Optional[int],
    organization_id: Optional[int],
    scenario_id: Optional[int],
    scenario_name: Optional[str],
) -> int:
    """Resolve a scenario ID from explicit ID or scenario name."""
    if scenario_id is not None:
        return scenario_id

    if not scenario_name:
        raise click.ClickException("Provide scenario ID or --name")

    scenarios = client.list_scenarios(
        team_id=team_id,
        organization_id=organization_id,
        limit=500,
    ).get("scenarios", [])

    query = scenario_name.strip().casefold()
    exact = [s for s in scenarios if (s.get("name") or "").casefold() == query]
    if len(exact) == 1:
        return int(exact[0]["id"])

    if len(exact) > 1:
        active_exact = [s for s in exact if s.get("isActive")]
        if len(active_exact) == 1:
            return int(active_exact[0]["id"])

    partial = [s for s in scenarios if query in (s.get("name") or "").casefold()]
    if len(partial) == 1:
        return int(partial[0]["id"])

    if len(partial) > 1:
        active_partial = [s for s in partial if s.get("isActive")]
        if len(active_partial) == 1:
            return int(active_partial[0]["id"])

    if len(exact) > 1 or len(partial) > 1:
        matches = exact if len(exact) > 1 else partial
        lines = "\n".join(f"  {m.get('name', '')} ({m.get('id')})" for m in matches[:10])
        raise click.ClickException(
            "Multiple scenarios match that name. Use an ID or a more specific name:\n"
            + lines
        )

    names = [(s.get("name") or "") for s in scenarios]
    fuzzy = get_close_matches(scenario_name, names, n=5, cutoff=0.6)
    if fuzzy:
        lines = []
        for name in fuzzy:
            match = next((s for s in scenarios if (s.get("name") or "") == name), None)
            if match:
                lines.append(f"  {name} ({match.get('id')})")
        raise click.ClickException(
            "No exact scenario match found. Did you mean:\n" + "\n".join(lines)
        )

    raise click.ClickException(f"Scenario not found: {scenario_name}")
