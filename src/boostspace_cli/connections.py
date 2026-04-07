"""Connection management commands."""

import click
from rich.table import Table

from .client import APIClient, APIError
from .config import Config
from .console import console
from .jsonio import emit_json


@click.group()
def connections():
    """List and inspect app connections."""
    pass


@connections.command("list")
@click.option("--team-id", type=int, help="Team ID (overrides config)")
@click.option("--app", help="Filter by app name (e.g. openai-gpt-3, google-sheets)")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def list_connections(ctx, team_id, app, json_output):
    """List all connections available in your team."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id

    with APIClient(config) as client:
        try:
            result = client.list_connections(team_id=tid)
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "connections list"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    conns = result.get("connections", result if isinstance(result, list) else [])

    if app:
        conns = [c for c in conns if app.lower() in (c.get("accountName") or c.get("name") or "").lower()
                 or app.lower() in (c.get("accountType") or "").lower()]

    if not conns:
        if json_output:
            emit_json(data=[], meta={"command": "connections list"})
            return
        console.print("[yellow]No connections found[/yellow]")
        return

    if json_output:
        payload = [
            {
                "id": c.get("id"),
                "name": c.get("accountName") or c.get("name"),
                "app": c.get("accountType") or c.get("type"),
                "scoped": c.get("scoped"),
            }
            for c in conns
        ]
        emit_json(data=payload, meta={"command": "connections list"})
        return

    table = Table(title=f"Connections ({len(conns)})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("App", style="green")

    for c in conns:
        table.add_row(
            str(c.get("id", "—")),
            c.get("accountName") or c.get("name") or "—",
            c.get("accountType") or c.get("type") or "—",
        )

    console.print(table)
