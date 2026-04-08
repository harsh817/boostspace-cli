"""MCP helper commands for local knowledge snapshots."""

from __future__ import annotations

import click

from .config import Config
from .console import console
from .jsonio import emit_json
from .mcp_knowledge import (
    MCP_KNOWLEDGE_PATH,
    build_knowledge_store,
    load_knowledge_store,
    save_knowledge_store,
)


@click.group("mcp")
def mcp_cli() -> None:
    """Manage local MCP knowledge and readiness."""


@mcp_cli.command("sync")
@click.option("--refresh-templates", is_flag=True, help="Refresh public template cache before snapshot")
@click.option("--workspace-assets/--no-workspace-assets", default=True, show_default=True, help="Include workspace templates/folders/connections")
@click.option("--include-public-blueprints/--no-include-public-blueprints", default=True, show_default=True, help="Probe template pages for public blueprint candidates")
@click.option("--blueprint-limit", type=int, default=30, show_default=True, help="How many public templates to probe for blueprint candidates")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def mcp_sync(
    ctx: click.Context,
    refresh_templates: bool,
    workspace_assets: bool,
    include_public_blueprints: bool,
    blueprint_limit: int,
    json_output: bool,
) -> None:
    """Build local knowledge snapshot used by MCP server tools."""
    config: Config = ctx.obj["config"]
    try:
        payload = build_knowledge_store(
            config,
            refresh_templates=refresh_templates,
            include_workspace_assets=workspace_assets,
            include_public_blueprints=include_public_blueprints,
            blueprint_limit=blueprint_limit,
        )
    except Exception as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "mcp sync"})
            raise SystemExit(1)
        raise click.ClickException(str(exc))

    path = save_knowledge_store(payload)
    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    result = {
        "path": str(path),
        "generatedAt": meta.get("generatedAt"),
        "moduleCount": meta.get("moduleCount"),
        "formulaCount": meta.get("formulaCount"),
        "publicTemplateCount": meta.get("publicTemplateCount"),
        "publicBlueprintProbeCount": meta.get("publicBlueprintProbeCount"),
        "workspaceCollected": meta.get("workspaceCollected"),
        "workspaceError": meta.get("workspaceError"),
    }

    if json_output:
        emit_json(data=result, meta={"command": "mcp sync"})
        return

    console.print(f"[green]MCP knowledge snapshot saved:[/green] {path}")
    console.print(
        f"[dim]modules={result['moduleCount']} formulas={result['formulaCount']} "
        f"templates={result['publicTemplateCount']} blueprint-probes={result['publicBlueprintProbeCount']}[/dim]"
    )
    if result.get("workspaceError"):
        console.print(f"[yellow]Workspace collection warning:[/yellow] {result['workspaceError']}")


@mcp_cli.command("info")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def mcp_info(json_output: bool) -> None:
    """Show local MCP knowledge snapshot metadata."""
    payload = load_knowledge_store()
    if payload is None:
        msg = f"Knowledge snapshot not found. Run `boost mcp sync` first. Expected: {MCP_KNOWLEDGE_PATH}"
        if json_output:
            emit_json(ok=False, error=msg, meta={"command": "mcp info"})
            raise SystemExit(1)
        raise click.ClickException(msg)

    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    workspace = payload.get("workspace") if isinstance(payload, dict) else None
    result = {
        "path": str(MCP_KNOWLEDGE_PATH),
        "generatedAt": meta.get("generatedAt"),
        "registrySource": meta.get("registrySource"),
        "templateSource": meta.get("templateSource"),
        "moduleCount": meta.get("moduleCount"),
        "formulaCount": meta.get("formulaCount"),
        "publicTemplateCount": meta.get("publicTemplateCount"),
        "publicBlueprintProbeCount": meta.get("publicBlueprintProbeCount"),
        "workspaceCollected": meta.get("workspaceCollected"),
        "workspaceTemplateCount": len(workspace.get("templates", [])) if isinstance(workspace, dict) else 0,
        "workspaceFolderCount": len(workspace.get("folders", [])) if isinstance(workspace, dict) else 0,
    }

    if json_output:
        emit_json(data=result, meta={"command": "mcp info"})
        return

    console.print(f"[green]Knowledge file:[/green] {result['path']}")
    console.print(f"[dim]generatedAt={result['generatedAt']} registry={result['registrySource']} templates={result['templateSource']}[/dim]")
    console.print(
        f"[dim]modules={result['moduleCount']} formulas={result['formulaCount']} "
        f"publicTemplates={result['publicTemplateCount']} blueprint-probes={result['publicBlueprintProbeCount']}[/dim]"
    )
    console.print(
        f"[dim]workspaceTemplates={result['workspaceTemplateCount']} workspaceFolders={result['workspaceFolderCount']}[/dim]"
    )
