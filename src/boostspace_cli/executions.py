"""Execution management commands."""

import json
from typing import Any

import click
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .console import console
from .jsonio import emit_json
from .scenario_lookup import resolve_scenario_id


def _parse_execution_ref(execution_ref: str) -> tuple[int | None, str]:
    for sep in (":", "/"):
        if sep in execution_ref:
            left, right = execution_ref.split(sep, 1)
            if left.isdigit() and right:
                return int(left), right
    return None, execution_ref


def _status_text(raw_status: Any) -> str:
    if isinstance(raw_status, str) and raw_status.isdigit():
        raw_status = int(raw_status)
    if raw_status == 1:
        return "success"
    if raw_status == 2:
        return "warning"
    if raw_status == 3:
        return "error"
    return str(raw_status)


def _status_rich(raw_status: Any) -> str:
    status_text = _status_text(raw_status)
    if status_text == "success":
        return "[green]success[/green]"
    if status_text == "warning":
        return "[yellow]warning[/yellow]"
    if status_text == "error":
        return "[red]error[/red]"
    return status_text


def _find_execution_log(logs: list[dict[str, Any]], execution_ref: str) -> dict[str, Any] | None:
    needle = str(execution_ref)
    for log in logs:
        candidates = [
            log.get("imtId"),
            log.get("id"),
            log.get("executionId"),
            log.get("executionID"),
        ]
        if any(str(value) == needle for value in candidates if value is not None):
            return log
    return None


def _resolve_execution_input(execution_id: str | None, history_execution_id: str | None) -> str:
    if execution_id and history_execution_id:
        raise click.ClickException("Use either EXECUTION_ID argument or --from-history, not both.")
    if not execution_id and not history_execution_id:
        raise click.ClickException("Provide EXECUTION_ID or --from-history.")
    return history_execution_id or execution_id or ""


@click.group()
def executions():
    """Manage scenario executions."""
    pass


@executions.command("run")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--data", type=str, help="JSON input data for the scenario")
@click.option("--data-file", type=click.Path(exists=True), help="Path to JSON file with input data")
@click.option("--async", "async_mode", is_flag=True, help="Run asynchronously (don't wait for result)")
@click.option("--callback", help="Callback URL for async notification")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def run_scenario(ctx, scenario_id, scenario_name, data, data_file, async_mode, callback, json_output):
    """Trigger a scenario run."""
    config: Config = ctx.obj["config"]
    input_data = None

    if data_file:
        with open(data_file) as f:
            input_data = json.load(f)
    elif data:
        input_data = json.loads(data)

    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id,
                scenario_name,
            )
            result = client.run_scenario(
                scenario_id,
                data=input_data,
                responsive=not async_mode,
                callback_url=callback,
            )

            if json_output:
                payload = {
                    "scenarioId": scenario_id,
                    "executionId": result.get("executionId"),
                    "status": result.get("status"),
                    "statusText": _status_text(result.get("status")),
                    "async": bool(async_mode),
                    "callback": callback,
                    "raw": result,
                }
                emit_json(data=payload, meta={"command": "executions run"})
                return

            console.print(f"[green]Execution started: {result.get('executionId', 'unknown')}[/green]")
            if "status" in result:
                console.print(f"[bold]Status:[/bold] {_status_rich(result['status'])}")
            if async_mode:
                console.print("[dim]Running asynchronously. Use 'boost executions status' to check.[/dim]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions run"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions run"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@executions.command("history")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--limit", type=int, default=20, help="Max results")
@click.option("--status", type=click.Choice(["success", "warning", "error"]), help="Filter by status")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def history(ctx, scenario_id, scenario_name, limit, status, json_output):
    """Show execution history for a scenario."""
    config: Config = ctx.obj["config"]
    status_filter = {"success": 1, "warning": 2, "error": 3}.get(status)

    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id,
                scenario_name,
            )
            result = client.get_logs(scenario_id, limit=limit, status=status_filter)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions history"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions history"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    logs = result.get("scenarioLogs", [])
    if not logs:
        if json_output:
            emit_json(data=[], meta={"command": "executions history", "limit": limit})
            return
        console.print("[yellow]No executions found[/yellow]")
        return

    if json_output:
        payload = [
            {
                "executionId": log.get("imtId"),
                "timestamp": log.get("timestamp"),
                "status": log.get("status"),
                "durationMs": log.get("duration"),
                "operations": log.get("operations"),
            }
            for log in logs
        ]
        emit_json(data=payload, meta={"command": "executions history", "limit": limit})
        return

    table = Table(title=f"Execution History ({len(logs)})")
    table.add_column("Execution ID", style="cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Status", style="white")
    table.add_column("Duration (ms)", style="white")
    table.add_column("Operations", style="white")

    for log in logs:
        status_code = log.get("status")
        table.add_row(
            str(log.get("imtId", "")),
            str(log.get("timestamp", ""))[:19],
            _status_rich(status_code),
            str(log.get("duration", "")),
            str(log.get("operations", "")),
        )

    console.print(table)


@executions.command("status")
@click.argument("execution_id", type=str, required=False)
@click.option("--scenario-id", type=int, help="Scenario ID")
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--from-history", "history_execution_id", type=str, help="Execution ID from `executions history` (imtId)")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def get_execution(ctx, execution_id, scenario_id, scenario_name, history_execution_id, json_output):
    """Get details of a specific execution."""
    config: Config = ctx.obj["config"]
    execution_ref = _resolve_execution_input(execution_id, history_execution_id)
    lookup_from_history = bool(history_execution_id)
    parsed_scenario_id, parsed_execution_id = _parse_execution_ref(execution_ref)

    with APIClient(config) as client:
        try:
            scenario_id = resolve_scenario_id(
                client,
                config.team_id,
                config.organization_id,
                scenario_id if scenario_id is not None else parsed_scenario_id,
                scenario_name,
            )

            if lookup_from_history:
                logs_result = client.get_logs(scenario_id, limit=200)
                matched = _find_execution_log(logs_result.get("scenarioLogs", []), parsed_execution_id)
                if not matched:
                    raise click.ClickException(
                        f"Execution {parsed_execution_id} not found in recent scenario history."
                    )
                exec_data = matched
                source = "logs"
            else:
                result = client.get_execution(scenario_id, parsed_execution_id)
                exec_data = result.get("execution", result)
                source = "execution"
        except APIError as e:
            if lookup_from_history:
                if json_output:
                    emit_json(ok=False, error=str(e), meta={"command": "executions status"})
                    raise SystemExit(1)
                console.print(f"[red]Error: {e}[/red]")
                raise SystemExit(1)

            can_fallback_to_logs = e.code == "SC400" or e.status_code in {400, 404}
            if not can_fallback_to_logs:
                if json_output:
                    emit_json(ok=False, error=str(e), meta={"command": "executions status"})
                    raise SystemExit(1)
                console.print(f"[red]Error: {e}[/red]")
                raise SystemExit(1)

            try:
                logs_result = client.get_logs(scenario_id, limit=200)
                matched = _find_execution_log(logs_result.get("scenarioLogs", []), parsed_execution_id)
                if not matched:
                    raise e
                exec_data = matched
                source = "logs"
            except APIError:
                if json_output:
                    emit_json(ok=False, error=str(e), meta={"command": "executions status"})
                    raise SystemExit(1)
                console.print(f"[red]Error: {e}[/red]")
                raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions status"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    status_code = exec_data.get("status", exec_data.get("result", ""))

    if json_output:
        payload = {
            "executionId": parsed_execution_id,
            "scenarioId": scenario_id,
            "status": status_code,
            "statusText": _status_text(status_code),
            "durationMs": exec_data.get("duration"),
            "operations": exec_data.get("operations"),
            "error": exec_data.get("error"),
            "source": source,
            "raw": exec_data,
        }
        emit_json(data=payload, meta={"command": "executions status"})
        return

    console.print(f"[bold]Execution ID:[/bold] {parsed_execution_id}")
    console.print(f"[bold]Status:[/bold] {_status_text(status_code)}")
    console.print(f"[bold]Duration:[/bold] {exec_data.get('duration', '—')}ms")
    console.print(f"[bold]Operations:[/bold] {exec_data.get('operations', '—')}")
    if source == "logs":
        console.print("[yellow]Execution details loaded from scenario logs fallback.[/yellow]")

    if exec_data.get("error"):
        console.print(f"[red]Error:[/red] {exec_data['error']}")


@executions.command("incomplete")
@click.argument("scenario_id", type=int, required=False)
@click.option("--name", "scenario_name", help="Scenario name")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def incomplete(ctx, scenario_id, scenario_name, json_output):
    """Show incomplete (stuck) executions."""
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
            result = client.get_incomplete_executions(scenario_id)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions incomplete"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
        except click.ClickException as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "executions incomplete"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    execs = result.get("executions", [])
    if not execs:
        if json_output:
            emit_json(data=[], meta={"command": "executions incomplete"})
            return
        console.print("[green]No incomplete executions[/green]")
        return

    if json_output:
        payload = [
            {
                "executionId": execution.get("imtId"),
                "timestamp": execution.get("timestamp"),
                "operations": execution.get("operations"),
            }
            for execution in execs
        ]
        emit_json(data=payload, meta={"command": "executions incomplete"})
        return

    table = Table(title=f"Incomplete Executions ({len(execs)})")
    table.add_column("Execution ID", style="cyan")
    table.add_column("Started", style="dim")
    table.add_column("Operations", style="white")

    for e in execs:
        table.add_row(
            str(e.get("imtId", "")),
            str(e.get("timestamp", ""))[:19],
            str(e.get("operations", "")),
        )

    console.print(table)
