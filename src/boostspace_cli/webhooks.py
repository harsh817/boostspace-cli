"""Webhook management commands."""

import click
from rich.table import Table

from .client import APIClient, APIError
from .console import console
from .jsonio import emit_json


@click.group()
def webhooks():
    """Manage webhooks."""
    pass


@webhooks.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def list_webhooks(ctx, json_output):
    """List all webhooks."""
    from .config import Config
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            result = client.list_webhooks()
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "webhooks list"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    hooks = result.get("hooks", [])
    if not hooks:
        if json_output:
            emit_json(data=[], meta={"command": "webhooks list"})
            return
        console.print("[yellow]No webhooks found[/yellow]")
        return

    if json_output:
        payload = [
            {
                "id": hook.get("id"),
                "name": hook.get("name"),
                "scenarioId": hook.get("scenarioId"),
                "type": hook.get("type"),
                "url": hook.get("url"),
            }
            for hook in hooks
        ]
        emit_json(data=payload, meta={"command": "webhooks list"})
        return

    table = Table(title=f"Webhooks ({len(hooks)})")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Scenario", style="dim")
    table.add_column("Type", style="white")
    table.add_column("URL", style="blue")

    for h in hooks:
        table.add_row(
            str(h.get("id", "")),
            h.get("name", ""),
            str(h.get("scenarioId", "")),
            h.get("type", ""),
            h.get("url", "")[:50],
        )

    console.print(table)


@webhooks.command("create")
@click.option("--name", required=True, help="Webhook name")
@click.option("--scenario-id", type=int, required=True, help="Target scenario ID")
@click.option("--type", "hook_type", type=click.Choice(["custom", "raw"]), default="custom")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def create_webhook(ctx, name, scenario_id, hook_type, json_output):
    """Create a new webhook."""
    from .config import Config
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            result = client.create_webhook(name, scenario_id, hook_type)
            hook = result.get("hook", result)
            if json_output:
                emit_json(data=hook, meta={"command": "webhooks create"})
                return
            console.print(f"[green]Webhook created: {name}[/green]")
            console.print(f"[bold]URL:[/bold] [blue]{hook.get('url', '—')}[/blue]")
            console.print(f"[bold]ID:[/bold] {hook.get('id')}")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "webhooks create"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)


@webhooks.command("delete")
@click.argument("webhook_id", type=int)
@click.option("--yes", is_flag=True, help="Skip confirmation")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def delete_webhook(ctx, webhook_id, yes, json_output):
    """Delete a webhook."""
    from .config import Config
    if not yes:
        if not click.confirm(f"Delete webhook {webhook_id}?"):
            return

    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            client.delete_webhook(webhook_id)
            if json_output:
                emit_json(data={"deleted": True, "id": webhook_id}, meta={"command": "webhooks delete"})
                return
            console.print(f"[green]Webhook {webhook_id} deleted[/green]")
        except APIError as e:
            if json_output:
                emit_json(ok=False, error=str(e), meta={"command": "webhooks delete"})
                raise SystemExit(1)
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)
