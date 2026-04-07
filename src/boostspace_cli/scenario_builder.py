"""Internet-first scenario builder commands."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .console import console
from .jsonio import emit_json
from .scenario_builder_core import (
    MODULE_COMPATIBILITY_RULES,
    build_draft,
    extract_blueprint,
    fetch_summary,
    repair_blueprint_data,
    research_goal,
    slugify,
    validate_blueprint_data,
)


@click.group("scenario")
def scenario_builder() -> None:
    """Research, draft, validate, and repair scenarios."""


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_team_id(client: APIClient, config: Config, requested_team_id: int | None) -> int:
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


def _module_names_from_blueprint(blueprint: dict[str, object]) -> set[str]:
    flow = blueprint.get("flow") or blueprint.get("modules") or []
    names: set[str] = set()
    if isinstance(flow, list):
        for module in flow:
            if isinstance(module, dict):
                mod = module.get("module")
                if isinstance(mod, str):
                    names.add(mod)
    return names


def _tenant_known_modules(
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
            bp_resp = client.get_blueprint(int(sid))
        except APIError:
            continue

        blueprint = bp_resp.get("response", {}).get("blueprint") if isinstance(bp_resp, dict) else None
        if not isinstance(blueprint, dict):
            continue

        known |= _module_names_from_blueprint(blueprint)

    return known


@scenario_builder.command("modules")
@click.option("--limit", type=int, default=60, show_default=True, help="Scenarios to scan")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_modules(ctx: click.Context, limit: int, json_output: bool) -> None:
    """List modules proven in your tenant from existing scenarios."""
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        modules = sorted(
            _tenant_known_modules(client, config.team_id, config.organization_id, scan_limit=limit),
            key=str.casefold,
        )

    if json_output:
        emit_json(data=modules, meta={"command": "scenario modules", "limit": limit})
        return

    if not modules:
        console.print("[yellow]No modules discovered from current scenario set.[/yellow]")
        return

    for module in modules:
        console.print(module)


@scenario_builder.command("research")
@click.option("--goal", required=True, help="What workflow are you building?")
@click.option("--max-results", type=int, default=8, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), help="Optional file path for JSON output")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def scenario_research(goal: str, max_results: int, output: Path | None, json_output: bool) -> None:
    """Research latest web patterns for a workflow goal."""
    results = research_goal(goal, max_results=max_results)
    if not results:
        if json_output:
            emit_json(ok=False, error="No web results found for this goal.", meta={"command": "scenario research"})
            raise SystemExit(1)
        console.print("[yellow]No web results found for this goal.[/yellow]")
        raise SystemExit(1)

    enriched: list[dict[str, str]] = []
    for idx, item in enumerate(results, start=1):
        summary = fetch_summary(item["url"], max_chars=500)
        enriched.append({"title": item["title"], "url": item["url"], "summary": summary})

    if not json_output:
        table = Table(title=f"Research Results ({len(results)})")
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("URL", style="blue")
        for idx, item in enumerate(results, start=1):
            table.add_row(str(idx), item["title"], item["url"])
        console.print(table)

    payload = {"goal": goal, "results": enriched, "createdAt": int(time.time())}

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not json_output:
            console.print(f"[green]Saved research to {output}[/green]")

    if json_output:
        if output:
            payload["output"] = str(output)
        emit_json(data=payload, meta={"command": "scenario research", "maxResults": max_results})


@scenario_builder.command("draft")
@click.option("--goal", help="Workflow goal")
@click.option("--spec", "spec_file", type=click.Path(exists=True, path_type=Path), help="Optional brainstorm spec JSON")
@click.option("--max-results", type=int, default=6, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), help="Output path for draft JSON")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def scenario_draft(goal: str | None, spec_file: Path | None, max_results: int, output: Path | None, json_output: bool) -> None:
    """Draft a blueprint from internet research and heuristics."""
    if spec_file:
        spec_payload = json.loads(spec_file.read_text(encoding="utf-8"))
        goal = spec_payload.get("draftGoal") or spec_payload.get("goal")

    if not goal:
        raise click.ClickException("Provide --goal or --spec")

    sources = research_goal(goal, max_results=max_results)
    draft = build_draft(goal, sources)
    if output is None:
        output = Path.cwd() / f"draft-{slugify(goal)}.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    if json_output:
        emit_json(
            data={
                "goal": goal,
                "output": str(output),
                "moduleCount": len(extract_blueprint(draft).get("flow", [])),
            },
            meta={"command": "scenario draft"},
        )
        return

    console.print(f"[green]Draft created:[/green] {output}")
    console.print(f"[dim]Next: boost scenario validate --file {output}[/dim]")


@scenario_builder.command("validate")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--check-auth", is_flag=True, help="Also verify account access and defaults")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_validate(ctx: click.Context, file_path: Path, check_auth: bool, json_output: bool) -> None:
    """Validate a scenario blueprint or draft file."""
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    blueprint = extract_blueprint(payload)
    errors, warnings = validate_blueprint_data(blueprint)

    if check_auth:
        config: Config = ctx.obj["config"]
        with APIClient(config) as client:
            try:
                client.get_user()
            except APIError as exc:
                errors.append(f"Auth check failed: {exc}")
            if not config.team_id and not config.organization_id:
                warnings.append("No team_id/organization_id configured; create may fail.")

    if json_output:
        emit_json(
            ok=not errors,
            error=errors[0] if errors else None,
            data={
                "file": str(file_path),
                "valid": not errors,
                "errors": errors,
                "warnings": warnings,
                "checkAuth": bool(check_auth),
            },
            meta={"command": "scenario validate"},
        )
        if errors:
            raise SystemExit(1)
        return

    if errors:
        console.print(f"[red]Validation failed: {len(errors)} error(s)[/red]")
        for err in errors:
            console.print(f"  [red]-[/red] {err}")
    else:
        console.print("[green]Validation passed.[/green]")

    if warnings:
        console.print(f"[yellow]Warnings: {len(warnings)}[/yellow]")
        for warn in warnings:
            console.print(f"  [yellow]-[/yellow] {warn}")

    if errors:
        raise SystemExit(1)


@scenario_builder.command("repair")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--goal", default="Repaired workflow", show_default=True)
@click.option("--in-place", is_flag=True, help="Update input file directly")
@click.option("--output", type=click.Path(path_type=Path), help="Output file when not --in-place")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def scenario_repair(file_path: Path, goal: str, in_place: bool, output: Path | None, json_output: bool) -> None:
    """Auto-repair common blueprint issues."""
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    blueprint = extract_blueprint(payload)
    repaired, fixes = repair_blueprint_data(blueprint, goal)

    final_payload: dict[str, object]
    if "blueprint" in payload and isinstance(payload["blueprint"], dict):
        payload["blueprint"] = repaired
        final_payload = payload
    else:
        final_payload = repaired

    target = file_path if in_place else output
    if target is None:
        target = file_path.with_name(file_path.stem + "-repaired.json")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(final_payload, indent=2), encoding="utf-8")

    if json_output:
        emit_json(
            data={
                "file": str(file_path),
                "output": str(target),
                "inPlace": bool(in_place),
                "fixes": fixes,
            },
            meta={"command": "scenario repair"},
        )
        return

    if fixes:
        console.print(f"[green]Applied {len(fixes)} fix(es):[/green]")
        for fix in fixes:
            console.print(f"  [green]-[/green] {fix}")
    else:
        console.print("[yellow]No structural fixes were needed.[/yellow]")

    console.print(f"[green]Saved repaired file:[/green] {target}")
    console.print(f"[dim]Next: boost scenario validate --file {target} --check-auth[/dim]")


@scenario_builder.command("brainstorm")
@click.option("--goal", required=True, help="Primary workflow objective")
@click.option("--trigger", help="Trigger source (webhook, form, crm-update, schedule)")
@click.option("--destinations", help="Comma-separated destinations (sheet, crm, slack, api)")
@click.option("--required-fields", help="Comma-separated required fields")
@click.option("--optional-fields", help="Comma-separated optional fields")
@click.option("--connections", help="Comma-separated known connection names")
@click.option("--run-mode", type=click.Choice(["on-demand", "immediately", "indefinitely", "once"]), default="on-demand", show_default=True)
@click.option("--activate", is_flag=True, help="Mark workflow as active target")
@click.option("--output", type=click.Path(path_type=Path), help="Output spec path")
@click.option("--non-interactive", is_flag=True, help="Skip prompts and use provided/default values")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def scenario_brainstorm(
    goal: str,
    trigger: str | None,
    destinations: str | None,
    required_fields: str | None,
    optional_fields: str | None,
    connections: str | None,
    run_mode: str,
    activate: bool,
    output: Path | None,
    non_interactive: bool,
    json_output: bool,
) -> None:
    """Create a brainstorming spec that is ready to feed into draft."""
    if not non_interactive:
        if not trigger:
            trigger = click.prompt("Trigger source", default="webhook")
        if not destinations:
            destinations = click.prompt("Destinations (comma-separated)", default="sheet")
        if not required_fields:
            required_fields = click.prompt("Required fields (comma-separated)", default="name,email")
        if not optional_fields:
            optional_fields = click.prompt("Optional fields (comma-separated)", default="phone,source")
        if not connections:
            connections = click.prompt("Known connections (comma-separated)", default="")

    trigger = trigger or "webhook"
    destinations = destinations or "sheet"
    required_fields = required_fields or "name,email"
    optional_fields = optional_fields or "phone,source"
    connections = connections or ""

    destination_list = _parse_csv(destinations)
    required_list = _parse_csv(required_fields)
    optional_list = _parse_csv(optional_fields)
    connection_list = _parse_csv(connections)

    draft_goal_parts = [goal, f"trigger {trigger}"]
    if destination_list:
        draft_goal_parts.append("to " + ", ".join(destination_list))
    if required_list:
        draft_goal_parts.append("required " + ", ".join(required_list))
    draft_goal = " | ".join(draft_goal_parts)

    spec: dict[str, object] = {
        "goal": goal,
        "draftGoal": draft_goal,
        "trigger": trigger,
        "destinations": destination_list,
        "requiredFields": required_list,
        "optionalFields": optional_list,
        "connections": connection_list,
        "runMode": run_mode,
        "activateTarget": activate,
        "createdAt": int(time.time()),
    }

    if output is None:
        output = Path.cwd() / f"spec-{slugify(goal)}.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(spec, indent=2), encoding="utf-8")

    if json_output:
        emit_json(data={"output": str(output), "spec": spec}, meta={"command": "scenario brainstorm"})
        return

    table = Table(title="Brainstorm Spec")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Goal", goal)
    table.add_row("Trigger", trigger)
    table.add_row("Destinations", ", ".join(destination_list) or "-")
    table.add_row("Required", ", ".join(required_list) or "-")
    table.add_row("Run mode", run_mode)
    table.add_row("Activate", "yes" if activate else "no")
    console.print(table)

    console.print(f"[green]Spec saved:[/green] {output}")
    console.print(f"[dim]Next: boost scenario draft --spec {output}[/dim]")


@scenario_builder.command("deploy")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--name", "override_name", help="Override scenario name")
@click.option("--team-id", type=int, help="Target team ID")
@click.option(
    "--schedule-type",
    type=click.Choice(["on-demand", "indefinitely", "once", "immediately"]),
    default="on-demand",
    show_default=True,
)
@click.option("--interval", type=int, default=3600, show_default=True, help="Interval in seconds for indefinitely")
@click.option("--inactive", is_flag=True, help="Deactivate right after creation")
@click.option("--dry-run", is_flag=True, help="Validate and resolve target context without creating")
@click.option("--repair", is_flag=True, help="Auto-repair draft in-memory before deploy")
@click.option("--guard-compat/--no-guard-compat", default=True, show_default=True, help="Block deploy when modules are not proven in tenant")
@click.option("--scan-limit", type=int, default=60, show_default=True, help="How many scenarios to scan for known modules")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_deploy(
    ctx: click.Context,
    file_path: Path,
    override_name: str | None,
    team_id: int | None,
    schedule_type: str,
    interval: int,
    inactive: bool,
    dry_run: bool,
    repair: bool,
    guard_compat: bool,
    scan_limit: int,
    json_output: bool,
) -> None:
    """Deploy a draft/blueprint to Boost.space with preflight checks."""
    config: Config = ctx.obj["config"]
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    blueprint = extract_blueprint(payload)
    goal = str(payload.get("goal", "Workflow"))

    if repair:
        blueprint, fixes = repair_blueprint_data(blueprint, goal)
        if fixes and not json_output:
            console.print(f"[green]Applied {len(fixes)} repair fix(es) before deploy.[/green]")

    errors, warnings = validate_blueprint_data(blueprint)
    if errors:
        if json_output:
            emit_json(
                ok=False,
                error=errors[0],
                data={"file": str(file_path), "errors": errors, "warnings": warnings},
                meta={"command": "scenario deploy", "dryRun": bool(dry_run)},
            )
            raise SystemExit(1)
        console.print(f"[red]Deploy blocked: {len(errors)} validation error(s).[/red]")
        for err in errors:
            console.print(f"  [red]-[/red] {err}")
        raise SystemExit(1)

    if warnings and not json_output:
        console.print(f"[yellow]Validation warnings: {len(warnings)}[/yellow]")
        for warn in warnings:
            console.print(f"  [yellow]-[/yellow] {warn}")

    with APIClient(config) as client:
        try:
            me = client.get_user()
            user = me.get("authUser") or me.get("user") or me
            resolved_team_id = _resolve_team_id(client, config, team_id)
        except APIError as exc:
            if json_output:
                emit_json(ok=False, error=f"Preflight API error: {exc}", meta={"command": "scenario deploy"})
                raise SystemExit(1)
            console.print(f"[red]Preflight API error: {exc}[/red]")
            raise SystemExit(1)
        except click.ClickException as exc:
            if json_output:
                emit_json(ok=False, error=str(exc), meta={"command": "scenario deploy"})
                raise SystemExit(1)
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1)

        scenario_name = override_name or blueprint.get("name") or f"Draft - {goal[:50]}"
        scheduling = {"type": schedule_type}
        if schedule_type == "indefinitely":
            scheduling["interval"] = str(interval)

        if guard_compat:
            known_modules = _tenant_known_modules(
                client,
                config.team_id,
                config.organization_id,
                scan_limit=scan_limit,
            )
            blueprint_modules = _module_names_from_blueprint(blueprint)
            unknown_modules = sorted(module for module in blueprint_modules if module not in known_modules)

            blocked_modules = []
            for module in blueprint_modules:
                rule = MODULE_COMPATIBILITY_RULES.get(module)
                if rule and rule.get("severity") == "error":
                    blocked_modules.append(module)

            if blocked_modules:
                if json_output:
                    emit_json(
                        ok=False,
                        error="Deploy blocked by compatibility rules.",
                        data={"modules": sorted(set(blocked_modules))},
                        meta={"command": "scenario deploy"},
                    )
                    raise SystemExit(1)
                console.print("[red]Deploy blocked by compatibility rules:[/red]")
                for module in sorted(set(blocked_modules)):
                    msg = MODULE_COMPATIBILITY_RULES[module]["message"]
                    console.print(f"  [red]-[/red] {module}: {msg}")
                raise SystemExit(1)

            if unknown_modules:
                if json_output:
                    emit_json(
                        ok=False,
                        error="Deploy blocked: unproven modules in this tenant.",
                        data={"modules": unknown_modules},
                        meta={"command": "scenario deploy"},
                    )
                    raise SystemExit(1)
                console.print("[red]Deploy blocked: unproven modules in this tenant.[/red]")
                for module in unknown_modules:
                    console.print(f"  [red]-[/red] {module}")
                console.print("[dim]Run `boost scenario modules` to inspect known-good module names.[/dim]")
                console.print("[dim]Or bypass once with --no-guard-compat.[/dim]")
                raise SystemExit(1)

        if dry_run:
            if json_output:
                emit_json(
                    data={
                        "dryRun": True,
                        "user": user.get("email", "unknown"),
                        "teamId": resolved_team_id,
                        "scenarioName": scenario_name,
                        "scheduleType": schedule_type,
                        "warnings": warnings,
                    },
                    meta={"command": "scenario deploy", "dryRun": True},
                )
                return
            console.print("[green]Dry-run passed.[/green]")
            console.print(f"[dim]User: {user.get('email', 'unknown')}[/dim]")
            console.print(f"[dim]Team ID: {resolved_team_id}[/dim]")
            console.print(f"[dim]Scenario name: {scenario_name}[/dim]")
            console.print(f"[dim]Schedule: {schedule_type}[/dim]")
            return

        try:
            result = client.create_scenario(
                team_id=resolved_team_id,
                blueprint=blueprint,
                scheduling=scheduling,
                name=scenario_name,
            )
            created = result.get("scenario", result)
            created_id = int(created.get("id"))
            if inactive:
                client.stop_scenario(created_id)

            if json_output:
                emit_json(
                    data={
                        "dryRun": False,
                        "id": created_id,
                        "name": scenario_name,
                        "teamId": resolved_team_id,
                        "active": not inactive,
                        "scheduleType": schedule_type,
                        "warnings": warnings,
                    },
                    meta={"command": "scenario deploy", "dryRun": False},
                )
                return

            console.print(f"[green]Scenario deployed: {scenario_name} ({created_id})[/green]")

            if inactive:
                console.print(f"[yellow]Scenario {created_id} set to inactive.[/yellow]")
        except APIError as exc:
            if json_output:
                emit_json(ok=False, error=f"Deploy failed: {exc}", meta={"command": "scenario deploy"})
                raise SystemExit(1)
            console.print(f"[red]Deploy failed: {exc}[/red]")
            raise SystemExit(1)
