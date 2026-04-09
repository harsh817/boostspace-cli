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
@click.option("--folder-id", type=int, help="Folder ID to place the scenario in")
@click.option("--folder-name", help="Folder name to place the scenario in")
@click.option("--schedule-type", type=click.Choice(["on-demand", "indefinitely", "once", "immediately"], case_sensitive=False), default="on-demand")
@click.option("--inactive", is_flag=True, help="Create in inactive state")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def import_blueprint(ctx, file, name, team_id, folder_id, folder_name, schedule_type, inactive, json_output):
    """Import a scenario from a blueprint JSON file."""
    from .config import Config
    from .scenarios import _resolve_folder_id
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
            resolved_folder_id = _resolve_folder_id(
                client,
                tid,
                config.organization_id,
                folder_id=folder_id,
                folder_name=folder_name,
                create_folder=False,
                parent_folder_id=None,
            ) if (folder_id or folder_name) else None

            result = client.create_scenario(
                team_id=tid,
                blueprint=blueprint,
                scheduling=scheduling,
                name=scenario_name,
                folder_id=resolved_folder_id,
            )
            scenario = result.get("scenario", result)
            if inactive:
                client.stop_scenario(scenario["id"])

            if json_output:
                payload = {
                    "id": scenario.get("id"),
                    "name": scenario_name,
                    "teamId": tid,
                    "folderId": resolved_folder_id,
                    "inactive": bool(inactive),
                    "scheduleType": schedule_type,
                }
                emit_json(data=payload, meta={"command": "blueprints import"})
                return
            console.print(f"[green]Scenario imported: ID {scenario.get('id')} — {scenario_name}[/green]")
            if resolved_folder_id:
                console.print(f"[dim]Placed in folder: {resolved_folder_id}[/dim]")
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


@blueprints.command("update")
@click.argument("scenario_id", type=int)
@click.argument("file", type=click.Path(exists=True))
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def update_blueprint(ctx, scenario_id, file, json_output):
    """Push a blueprint JSON file onto an existing scenario (preserves webhook/folder)."""
    from .config import Config
    config: Config = ctx.obj["config"]

    with open(file) as f:
        blueprint = json.load(f)

    with APIClient(config) as client:
        try:
            resp = client.patch(
                f"/scenarios/{scenario_id}",
                json={"blueprint": json.dumps(blueprint)},
            )
            scenario = resp.get("scenario", resp)
            if json_output:
                emit_json(
                    data={
                        "id": scenario.get("id", scenario_id),
                        "name": scenario.get("name"),
                        "hookId": scenario.get("hookId"),
                        "folderId": scenario.get("folderId"),
                        "isInvalid": scenario.get("isinvalid"),
                    },
                    meta={"command": "blueprints update"},
                )
                return
            console.print(f"[green]Blueprint updated on scenario {scenario_id} — {scenario.get('name', '')}[/green]")
            if scenario.get("isinvalid"):
                console.print("[yellow]Warning: scenario marked invalid — check connections/UDTs[/yellow]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "blueprints update"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@blueprints.command("remap")
@click.argument("file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output file (default: overwrite input)")
@click.option("--team-id", type=int, help="Team ID to resolve connections/UDTs from")
@click.option("--dry-run", is_flag=True, help="Print remapping plan without writing")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def remap_blueprint(ctx, file, output, team_id, dry_run, json_output):
    """Remap connection IDs and data-structure IDs in a blueprint to match the current team.

    Reads all __IMTCONN__ values and UDT type IDs from the blueprint, fetches
    available connections and data structures from the API, and prompts you to
    map each unknown ID to a valid one in the current team.
    """
    import re
    from .config import Config
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id

    with open(file) as f:
        raw = f.read()

    blueprint = json.loads(raw)

    with APIClient(config) as client:
        # --- connections ---
        conn_result = client.list_connections(team_id=tid)
        available_conns: list[dict] = conn_result.get("connections", [])

        # --- data structures ---
        try:
            udt_result = client.get("/data-structures", params={"teamId": tid})
            available_udts: list[dict] = udt_result.get("dataStructures", [])
        except APIError:
            available_udts = []

    # Find all __IMTCONN__ IDs used in blueprint
    conn_ids_used = sorted({int(x) for x in re.findall(r'"__IMTCONN__"\s*:\s*(\d+)', raw)})
    # Find all UDT IDs used in json:CreateJSON "type" parameters
    udt_ids_used = sorted({int(x) for x in re.findall(r'"type"\s*:\s*(\d+)', raw)})

    available_conn_ids = {c["id"] for c in available_conns}
    available_udt_ids = {u["id"] for u in available_udts}

    conn_remaps: dict[str, str] = {}
    udt_remaps: dict[str, str] = {}

    unknown_conns = [cid for cid in conn_ids_used if cid not in available_conn_ids]
    unknown_udts = [uid for uid in udt_ids_used if uid not in available_udt_ids]

    if not unknown_conns and not unknown_udts:
        msg = "All connection and UDT IDs are already valid in this team — no remapping needed."
        if json_output:
            emit_json(data={"remapped": False, "reason": msg}, meta={"command": "blueprints remap"})
        else:
            console.print(f"[green]{msg}[/green]")
        return

    if not json_output:
        if unknown_conns:
            console.print(f"\n[bold]Unknown connection IDs:[/bold] {unknown_conns}")
            console.print("[dim]Available connections:[/dim]")
            for c in available_conns:
                console.print(f"  {c['id']}\t{c.get('name','?')}")
            for old_id in unknown_conns:
                new_id = click.prompt(f"  Map connection {old_id} to", type=int)
                conn_remaps[str(old_id)] = str(new_id)

        if unknown_udts:
            console.print(f"\n[bold]Unknown UDT IDs:[/bold] {unknown_udts}")
            console.print("[dim]Available data structures:[/dim]")
            for u in available_udts:
                console.print(f"  {u['id']}\t{u.get('name','?')}")
            for old_id in unknown_udts:
                new_id = click.prompt(f"  Map data structure {old_id} to", type=int)
                udt_remaps[str(old_id)] = str(new_id)
    else:
        emit_json(
            ok=False,
            error="Interactive remapping required — run without --json to remap.",
            data={
                "unknownConnections": unknown_conns,
                "unknownUdts": unknown_udts,
                "availableConnections": [{"id": c["id"], "name": c.get("name")} for c in available_conns],
                "availableUdts": [{"id": u["id"], "name": u.get("name")} for u in available_udts],
            },
            meta={"command": "blueprints remap"},
        )
        raise SystemExit(1)

    # Apply remaps
    new_raw = raw
    for old, new in conn_remaps.items():
        new_raw = new_raw.replace(f'"__IMTCONN__": {old}', f'"__IMTCONN__": {new}')
        new_raw = new_raw.replace(f'"__IMTCONN__":{old}', f'"__IMTCONN__":{new}')
    for old, new in udt_remaps.items():
        new_raw = new_raw.replace(f'"type": {old}', f'"type": {new}')
        new_raw = new_raw.replace(f'"type":{old}', f'"type":{new}')

    all_remaps = {**{f"conn:{k}": f"conn:{v}" for k, v in conn_remaps.items()},
                  **{f"udt:{k}": f"udt:{v}" for k, v in udt_remaps.items()}}

    if dry_run:
        console.print("[yellow]Dry run — no file written.[/yellow]")
        console.print(f"[bold]Would apply:[/bold] {all_remaps}")
        return

    out_path = output or file
    with open(out_path, "w") as f:
        f.write(new_raw)

    console.print(f"[green]Remapped blueprint written to {out_path}[/green]")
    for k, v in all_remaps.items():
        console.print(f"  {k} → {v}")
