"""Blueprint import/export commands."""

import json

import click

from .client import APIClient, APIError
from .console import console
from .jsonio import emit_json


@click.group()
def blueprints():
    """Export, import, and validate scenario blueprints."""
    pass


@blueprints.command("export")
@click.argument("scenario_id", type=int)
@click.option("--output", "-o", type=click.Path(), help="Output file path (default: stdout)")
@click.option("--json", "json_output", is_flag=True, help="Output JSON metadata")
@click.pass_context
def export_blueprint(ctx, scenario_id, output, json_output):
    """Export a scenario blueprint to JSON."""
    from .config import Config
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            blueprint = client.get_blueprint(scenario_id)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "blueprints export"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    blueprint_json = json.dumps(blueprint, indent=2)

    if output:
        with open(output, "w") as f:
            f.write(blueprint_json)
        if json_output:
            emit_json(
                data={"exported": True, "scenarioId": scenario_id, "output": output},
                meta={"command": "blueprints export"},
            )
            return
        console.print(f"[green]Blueprint exported to {output}[/green]")
    else:
        if json_output:
            emit_json(
                data={"scenarioId": scenario_id, "blueprint": blueprint},
                meta={"command": "blueprints export"},
            )
            return
        console.print_json(blueprint_json)


@blueprints.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--name", help="Scenario name (overrides blueprint name)")
@click.option("--team-id", type=int, help="Team ID (overrides config)")
@click.option("--schedule-type", type=click.Choice(["on-demand", "indefinitely", "once", "immediately"], case_sensitive=False), default="on-demand")
@click.option("--inactive", is_flag=True, help="Create in inactive state")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def import_blueprint(ctx, file, name, team_id, schedule_type, inactive, json_output):
    """Import a scenario from a blueprint JSON file."""
    from .config import Config
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    if not tid:
        if json_output:
            emit_json(ok=False, error="--team-id required (or set via 'boost configure --team-id')", meta={"command": "blueprints import"})
            raise SystemExit(1)
        console.print("[red]Error: --team-id required (or set via 'boost configure --team-id')[/red]")
        raise SystemExit(1)

    with open(file) as f:
        blueprint = json.load(f)

    schedule_type = str(schedule_type).casefold()
    scenario_name = name or blueprint.get("name", "Imported Scenario")
    scheduling = {"type": schedule_type}
    if schedule_type == "indefinitely":
        scheduling["interval"] = 3600

    with APIClient(config) as client:
        try:
            result = client.create_scenario(
                team_id=tid,
                blueprint=blueprint,
                scheduling=scheduling,
                name=scenario_name,
            )
            scenario = result.get("scenario", result)
            if inactive:
                client.stop_scenario(scenario["id"])

            if json_output:
                payload = {
                    "id": scenario.get("id"),
                    "name": scenario_name,
                    "teamId": tid,
                    "inactive": bool(inactive),
                    "scheduleType": schedule_type,
                }
                emit_json(data=payload, meta={"command": "blueprints import"})
                return
            console.print(f"[green]Scenario imported: ID {scenario.get('id')} — {scenario_name}[/green]")
            if inactive:
                console.print("[yellow]Scenario set to inactive[/yellow]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "blueprints import"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@blueprints.command("validate")
@click.argument("file", type=click.Path(exists=True))
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def validate_blueprint(ctx, file, json_output):
    """Validate a blueprint JSON file."""
    with open(file) as f:
        try:
            blueprint = json.load(f)
        except json.JSONDecodeError as e:
            if json_output:
                emit_json(ok=False, error=f"Invalid JSON: {e}", meta={"command": "blueprints validate"})
                raise SystemExit(1)
            console.print(f"[red]Invalid JSON: {e}[/red]")
            raise SystemExit(1)

    errors = []
    warnings = []

    if "flow" not in blueprint and "modules" not in blueprint:
        errors.append("Missing 'flow' or 'modules' key — blueprint has no module definitions")

    modules = blueprint.get("flow", blueprint.get("modules", []))
    if not isinstance(modules, list):
        errors.append("'flow'/'modules' must be an array")
    elif len(modules) == 0:
        warnings.append("Blueprint has no modules (empty flow)")
    else:
        module_ids = set()
        for i, module in enumerate(modules):
            if not isinstance(module, dict):
                errors.append(f"Module at index {i} is not an object")
                continue
            mid = module.get("id")
            if mid is None:
                errors.append(f"Module at index {i} missing 'id' field")
            elif mid in module_ids:
                errors.append(f"Duplicate module ID: {mid}")
            else:
                module_ids.add(mid)

            if "app" not in module and "action" not in module:
                warnings.append(f"Module {mid} (index {i}) missing 'app' or 'action'")

    metadata = blueprint.get("metadata", {})
    if not metadata:
        warnings.append("Missing 'metadata' section")
    elif "scenario" not in metadata:
        warnings.append("Missing 'metadata.scenario' section")

    payload = {
        "file": file,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "moduleCount": len(modules) if isinstance(modules, list) else 0,
    }

    if json_output:
        emit_json(
            ok=not errors,
            error=errors[0] if errors else None,
            data=payload,
            meta={"command": "blueprints validate"},
        )
        if errors:
            raise SystemExit(1)
        return

    if errors:
        console.print(f"[red]Validation FAILED ({len(errors)} errors, {len(warnings)} warnings)[/red]")
        for e in errors:
            console.print(f"  [red]✗[/red] {e}")
        for w in warnings:
            console.print(f"  [yellow]![/yellow] {w}")
        raise SystemExit(1)

    if warnings:
        console.print(f"[yellow]Validation passed with warnings ({len(warnings)})[/yellow]")
        for w in warnings:
            console.print(f"  [yellow]![/yellow] {w}")
    else:
        console.print(f"[green]Validation passed — {len(modules)} modules, no issues[/green]")

    console.print(f"[dim]File: {file}[/dim]")
