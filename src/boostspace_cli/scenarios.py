"""Scenario management commands."""

import json

import click
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .console import console
from .jsonio import emit_json
from .scenario_lookup import resolve_scenario_id


@click.group()
def scenarios():
    """Manage scenarios (workflows)."""
    pass


def _normalize_schedule_type(value: str) -> str:
    normalized = value.strip().casefold()
    allowed = {"on-demand", "indefinitely", "once", "immediately"}
    if normalized not in allowed:
        raise click.ClickException(
            f"Invalid schedule type '{value}'. Use one of: on-demand, indefinitely, once, immediately."
        )
    return normalized


@scenarios.command("list")
@click.option("--team-id", type=int, help="Team ID (overrides config)")
@click.option("--limit", type=int, default=50, help="Max results")
@click.option("--with-ids", is_flag=True, help="Include IDs with names (legacy; default output already includes IDs)")
@click.option("--table", is_flag=True, help="Show rich table output")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.option("--plain", is_flag=True, hidden=True, help="Legacy alias for --with-ids")
@click.pass_context
def list_scenarios(ctx, team_id, limit, with_ids, table, json_output, plain):
    """List all scenarios."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    oid = config.organization_id
    with APIClient(config) as client:
        try:
            result = client.list_scenarios(team_id=tid, organization_id=oid, limit=limit)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios list", "limit": limit})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    scenarios_list = result.get("scenarios", [])
    if not scenarios_list:
        if json_output:
            emit_json(data=[], meta={"command": "scenarios list", "limit": limit})
            return
        console.print("[yellow]No scenarios found[/yellow]")
        return

    if plain:
        with_ids = True

    scenarios_list = sorted(
        scenarios_list,
        key=lambda s: (s.get("name") or "").casefold(),
    )

    if json_output:
        payload = [
            {
                "id": s.get("id"),
                "name": s.get("name", ""),
                "active": bool(s.get("isActive")),
                "dlq": int(s.get("dlqCount", 0) or 0),
                "nextRun": s.get("nextExec"),
            }
            for s in scenarios_list
        ]
        emit_json(data=payload, meta={"command": "scenarios list", "limit": limit})
        return

    if not table:
        for s in scenarios_list:
            name = s.get("name", "")
            sid = s.get("id")
            if with_ids:
                console.print(f"{sid}	{name}")
            else:
                console.print(f"{name} ({sid})")
        return

    table = Table(title=f"Scenarios ({len(scenarios_list)})")
    table.add_column("Name", style="white")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")
    table.add_column("DLQ", style="red", no_wrap=True)
    table.add_column("Next Run", style="dim")

    for s in scenarios_list:
        status = "[green]active[/green]" if s.get("isActive") else "[yellow]inactive[/yellow]"
        dlq = f"[red]{s.get('dlqCount', 0)}[/red]" if s.get("dlqCount", 0) > 0 else "0"
        next_exec = s.get("nextExec", "—")
        table.add_row(s.get("name", ""), str(s["id"]), status, dlq, str(next_exec)[:19])

    console.print(table)


@scenarios.command("get")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--blueprint", is_flag=True, help="Show blueprint JSON")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def get_scenario(ctx, scenario_id, scenario_name, blueprint, json_output):
    """Get scenario details."""
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id,
                scenario_name,
            )
            scenario = client.get_scenario(scenario_id)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios get"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios get"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    s = scenario.get("scenario", scenario)

    if json_output:
        out = {
            "id": s.get("id"),
            "name": s.get("name"),
            "active": s.get("isActive", s.get("active")),
            "teamId": s.get("teamId"),
            "created": s.get("dateCreated", s.get("created")),
            "updated": s.get("lastEdit", s.get("updated")),
        }
        if blueprint:
            try:
                bp = client.get_blueprint(scenario_id)
                out["blueprint"] = bp
            except APIError as e:
                out["blueprintError"] = str(e)
        emit_json(data=out, meta={"command": "scenarios get"})
        return

    console.print(f"[bold]ID:[/bold] {s.get('id')}")
    console.print(f"[bold]Name:[/bold] {s.get('name')}")
    console.print(f"[bold]Active:[/bold] {s.get('isActive', s.get('active'))}")
    console.print(f"[bold]Team:[/bold] {s.get('teamId')}")
    console.print(f"[bold]Created:[/bold] {s.get('dateCreated', s.get('created', '—'))}")
    console.print(f"[bold]Updated:[/bold] {s.get('lastEdit', s.get('updated', '—'))}")

    if s.get("scheduling"):
        sched = s["scheduling"]
        if isinstance(sched, str):
            sched = json.loads(sched)
        console.print(f"[bold]Schedule:[/bold] {sched.get('type', '—')} (interval: {sched.get('interval', '—')}s)")

    if blueprint:
        try:
            bp = client.get_blueprint(scenario_id)
            console.print("\n[bold]Blueprint:[/bold]")
            console.print_json(json.dumps(bp, indent=2))
        except APIError as e:
            console.print(f"[red]Error fetching blueprint: {e}[/red]")


@scenarios.command("create")
@click.option("--name", required=True, help="Scenario name")
@click.option("--blueprint-file", type=click.Path(exists=True), help="Path to blueprint JSON file")
@click.option("--team-id", type=int, help="Team ID (overrides config)")
@click.option("--schedule-type", type=click.Choice(["on-demand", "indefinitely", "once", "immediately"], case_sensitive=False), default="on-demand")
@click.option("--interval", type=int, default=3600, help="Schedule interval in seconds (for 'indefinitely')")
@click.option("--inactive", is_flag=True, help="Create in inactive state")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def create_scenario(ctx, name, blueprint_file, team_id, schedule_type, interval, inactive, json_output):
    """Create a new scenario."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    if not tid:
        if json_output:
            emit_json(ok=False, error="--team-id required (or set via 'boost configure --team-id')", meta={"command": "scenarios create"})
            raise SystemExit(1)
        console.print("[red]Error: --team-id required (or set via 'boost configure --team-id')[/red]")
        raise SystemExit(1)

    blueprint = {}
    if blueprint_file:
        with open(blueprint_file) as f:
            blueprint = json.load(f)
    else:
        blueprint = {"name": name, "flow": [], "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}}}

    schedule_type = _normalize_schedule_type(schedule_type)
    if schedule_type == "indefinitely" and interval <= 0:
        message = "--interval must be a positive integer when --schedule-type indefinitely"
        if json_output:
            emit_json(ok=False, error=message, meta={"command": "scenarios create"})
            raise SystemExit(1)
        raise click.ClickException(message)

    scheduling = {"type": schedule_type}
    if schedule_type == "indefinitely":
        scheduling["interval"] = interval

    with APIClient(config) as client:
        try:
            result = client.create_scenario(team_id=tid, blueprint=blueprint, scheduling=scheduling, name=name)
            scenario = result.get("scenario", result)
            if inactive:
                client.stop_scenario(scenario["id"])

            if json_output:
                payload = {
                    "id": scenario.get("id"),
                    "name": name,
                    "teamId": tid,
                    "scheduleType": schedule_type,
                    "interval": scheduling.get("interval"),
                    "active": not inactive,
                }
                emit_json(data=payload, meta={"command": "scenarios create"})
                return

            console.print(f"[green]Scenario created: ID {scenario.get('id')} — {name}[/green]")
            if inactive:
                console.print("[yellow]Scenario set to inactive[/yellow]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios create"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("update")
@click.argument("scenario_id", type=int)
@click.option("--name", help="New name")
@click.option("--active/--inactive", default=None, help="Activate or deactivate")
@click.option("--schedule-type", type=click.Choice(["on-demand", "indefinitely", "once", "immediately"], case_sensitive=False))
@click.option("--interval", type=int, help="Schedule interval in seconds")
@click.option("--max-errors", type=int, help="Max errors before stopping")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def update_scenario(ctx, scenario_id, name, active, schedule_type, interval, max_errors, json_output):
    """Update scenario settings."""
    import json as _json

    config: Config = ctx.obj["config"]
    updates = {}
    if name:
        updates["name"] = name
    if active is not None:
        updates["active"] = active
    if schedule_type or interval is not None:
        normalized = _normalize_schedule_type(schedule_type or "on-demand")
        if normalized == "indefinitely" and interval is None:
            msg = "--interval is required when --schedule-type indefinitely"
            if json_output:
                emit_json(ok=False, error=msg, meta={"command": "scenarios update"})
                raise SystemExit(1)
            raise click.ClickException(msg)
        if interval is not None and interval <= 0:
            msg = "--interval must be a positive integer"
            if json_output:
                emit_json(ok=False, error=msg, meta={"command": "scenarios update"})
                raise SystemExit(1)
            raise click.ClickException(msg)

        sched = {"type": normalized}
        if interval is not None:
            sched["interval"] = interval
        updates["scheduling"] = _json.dumps(sched)
    if max_errors is not None:
        updates["maxErrors"] = max_errors

    if not updates:
        if json_output:
            emit_json(data={"id": scenario_id, "updated": False, "updates": {}}, meta={"command": "scenarios update"})
            return
        console.print("[yellow]No updates provided[/yellow]")
        return

    with APIClient(config) as client:
        try:
            client.update_scenario(scenario_id, updates)
            if json_output:
                emit_json(data={"id": scenario_id, "updated": True, "updates": updates}, meta={"command": "scenarios update"})
                return
            console.print(f"[green]Scenario {scenario_id} updated[/green]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios update"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("delete")
@click.argument("scenario_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def delete_scenario(ctx, scenario_id, yes, json_output):
    """Delete a scenario."""
    if not yes:
        if not click.confirm(f"Delete scenario {scenario_id}?"):
            return

    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            client.delete_scenario(scenario_id)
            if json_output:
                emit_json(data={"id": scenario_id, "deleted": True}, meta={"command": "scenarios delete"})
                return
            console.print(f"[green]Scenario {scenario_id} deleted[/green]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios delete"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("clone")
@click.argument("scenario_id", type=int)
@click.option("--name", required=True, help="Name for the clone")
@click.option("--team-id", type=int, help="Target team ID")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def clone_scenario(ctx, scenario_id, name, team_id, json_output):
    """Clone a scenario."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    if not tid:
        if json_output:
            emit_json(ok=False, error="--team-id required", meta={"command": "scenarios clone"})
            raise SystemExit(1)
        console.print("[red]Error: --team-id required[/red]")
        raise SystemExit(1)

    with APIClient(config) as client:
        try:
            result = client.clone_scenario(scenario_id, tid, name)
            cloned = result.get("scenario", result)
            if json_output:
                emit_json(
                    data={
                        "sourceId": scenario_id,
                        "id": cloned.get("id"),
                        "name": name,
                        "teamId": tid,
                    },
                    meta={"command": "scenarios clone"},
                )
                return
            console.print(f"[green]Cloned scenario {scenario_id} -> {cloned.get('id')} ({name})[/green]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios clone"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("start")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def start_scenario(ctx, scenario_id, scenario_name, json_output):
    """Activate a scenario."""
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id,
                scenario_name,
            )
            client.start_scenario(scenario_id)
            if json_output:
                emit_json(data={"id": scenario_id, "active": True}, meta={"command": "scenarios start"})
                return
            console.print(f"[green]Scenario {scenario_id} activated[/green]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios start"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios start"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("stop")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def stop_scenario(ctx, scenario_id, scenario_name, json_output):
    """Deactivate a scenario."""
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id,
                scenario_name,
            )
            client.stop_scenario(scenario_id)
            if json_output:
                emit_json(data={"id": scenario_id, "active": False}, meta={"command": "scenarios stop"})
                return
            console.print(f"[yellow]Scenario {scenario_id} deactivated[/yellow]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios stop"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios stop"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@scenarios.command("health")
@click.option("--team-id", type=int, help="Team ID")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def health_report(ctx, team_id, json_output):
    """Show health report for all scenarios."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    oid = config.organization_id
    with APIClient(config) as client:
        try:
            result = client.list_scenarios(team_id=tid, organization_id=oid, limit=100)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios health"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

        scenarios_list = result.get("scenarios", [])

        if json_output:
            health_rows = []
            for scenario in scenarios_list:
                try:
                    logs = client.get_logs(scenario["id"], limit=1)
                    last_status = None
                    if logs.get("scenarioLogs"):
                        last_status = logs["scenarioLogs"][0].get("status")
                except APIError:
                    last_status = None

                health_rows.append(
                    {
                        "id": scenario.get("id"),
                        "name": scenario.get("name", ""),
                        "active": bool(scenario.get("isActive")),
                        "lastStatus": last_status,
                        "dlq": int(scenario.get("dlqCount", 0) or 0),
                    }
                )

            emit_json(data=health_rows, meta={"command": "scenarios health"})
            return

        table = Table(title="Scenario Health Report")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Active", style="green")
        table.add_column("Last Status", style="white")
        table.add_column("DLQ", style="red")

        for s in scenarios_list:
            try:
                logs = client.get_logs(s["id"], limit=1)
                last_status = "—"
                if logs.get("scenarioLogs"):
                    code = logs["scenarioLogs"][0]["status"]
                    status_map = {1: "[green]success[/green]", 2: "[yellow]warning[/yellow]", 3: "[red]error[/red]"}
                    last_status = status_map.get(code, str(code))
            except APIError:
                last_status = "—"

            active = "[green]yes[/green]" if s.get("isActive") else "[yellow]no[/yellow]"
            dlq = s.get("dlqCount", 0)
            dlq_display = f"[red]{dlq}[/red]" if dlq > 0 else "0"
            table.add_row(str(s["id"]), s.get("name", "")[:35], active, last_status, dlq_display)

        console.print(table)


@scenarios.command("top-issues")
@click.option("--team-id", type=int, help="Team ID")
@click.option("--limit", type=int, default=10, help="Max scenarios to show")
@click.option("--include-inactive", is_flag=True, help="Include inactive scenarios")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def top_issues(ctx, team_id, limit, include_inactive, json_output):
    """Show scenarios sorted by operational risk (DLQ/errors first)."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id
    oid = config.organization_id

    with APIClient(config) as client:
        try:
            result = client.list_scenarios(team_id=tid, organization_id=oid, limit=200)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "scenarios top-issues", "limit": limit})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

        scenarios_list = result.get("scenarios", [])
        ranked = []

        for scenario in scenarios_list:
            is_active = bool(scenario.get("isActive"))
            if not is_active and not include_inactive:
                continue

            scenario_id = scenario.get("id")
            dlq = int(scenario.get("dlqCount", 0) or 0)
            last_status_code = None

            try:
                logs = client.get_logs(scenario_id, limit=1)
                if logs.get("scenarioLogs"):
                    last_status_code = logs["scenarioLogs"][0].get("status")
            except APIError:
                last_status_code = None

            has_issue = dlq > 0 or last_status_code in (2, 3) or not is_active
            if not has_issue:
                continue

            issue_parts = []
            if dlq > 0:
                issue_parts.append(f"DLQ {dlq}")
            if last_status_code == 3:
                issue_parts.append("last run error")
            elif last_status_code == 2:
                issue_parts.append("last run warning")
            if not is_active:
                issue_parts.append("inactive")

            score = dlq * 100
            if last_status_code == 3:
                score += 50
            elif last_status_code == 2:
                score += 20
            if not is_active:
                score += 5

            if dlq > 0 or last_status_code == 3:
                action = "inspect logs"
            elif last_status_code == 2:
                action = "review warning"
            else:
                action = "check schedule"

            ranked.append(
                {
                    "id": scenario_id,
                    "name": scenario.get("name", ""),
                    "dlq": dlq,
                    "last_status": last_status_code,
                    "issue": ", ".join(issue_parts) if issue_parts else "none",
                    "action": action,
                    "score": score,
                }
            )

    if not ranked:
        if json_output:
            emit_json(data=[], meta={"command": "scenarios top-issues", "limit": limit})
            return
        console.print("[green]No issues detected in the scanned scenarios.[/green]")
        return

    ranked.sort(key=lambda item: (-item["score"], item["name"].casefold()))
    top = ranked[:limit]

    if json_output:
        payload = [
            {
                "rank": idx,
                "id": item["id"],
                "name": item["name"],
                "dlq": item["dlq"],
                "lastStatus": item["last_status"],
                "issue": item["issue"],
                "action": item["action"],
                "score": item["score"],
            }
            for idx, item in enumerate(top, start=1)
        ]
        emit_json(data=payload, meta={"command": "scenarios top-issues", "limit": limit})
        return

    status_map = {
        None: "—",
        1: "[green]success[/green]",
        2: "[yellow]warning[/yellow]",
        3: "[red]error[/red]",
    }

    table = Table(title=f"Top Issues ({len(top)})")
    table.add_column("Rank", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("DLQ", style="red", no_wrap=True)
    table.add_column("Last", style="white", no_wrap=True)
    table.add_column("Issue", style="yellow")
    table.add_column("Action", style="green")

    for idx, item in enumerate(top, start=1):
        table.add_row(
            str(idx),
            item["name"],
            str(item["id"]),
            str(item["dlq"]),
            status_map.get(item["last_status"], str(item["last_status"])),
            item["issue"],
            item["action"],
        )

    console.print(table)
