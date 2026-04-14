"""Top-level offline catalog commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import click
from rich.table import Table

from .catalog.doctor import catalog_doctor
from .catalog.refresh import refresh_catalog
from .catalog.search import module_detail, search_modules
from .catalog.store import load_registry_with_source
from .catalog.templates import (
    DEFAULT_TEMPLATES_URL,
    build_template_registry,
    load_template_registry,
    save_template_registry,
    search_templates,
)
from .console import console
from .executables import resolve_executable
from .jsonio import emit_json


@click.group("catalog")
def catalog_cli() -> None:
    """Inspect and refresh offline module catalog."""


@catalog_cli.command("info")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_info(json_output: bool) -> None:
    """Show active catalog source and counts."""
    registry, source, path = load_registry_with_source()
    meta = registry.get("meta", {}) if isinstance(registry, dict) else {}
    payload = {
        "source": source,
        "path": str(path) if path else None,
        "moduleCount": meta.get("moduleCount", 0),
        "appCount": meta.get("appCount", 0),
        "packageVersion": meta.get("packageVersion", "unknown"),
        "generatedAt": meta.get("generatedAt"),
    }

    if json_output:
        emit_json(data=payload, meta={"command": "catalog info"})
        return

    for key, value in payload.items():
        console.print(f"[bold]{key}:[/bold] {value}")


@catalog_cli.command("search")
@click.argument("query", type=str)
@click.option("--app", help="Filter by app id")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_search(query: str, app: str | None, limit: int, json_output: bool) -> None:
    """Search modules in offline catalog."""
    registry, _, _ = load_registry_with_source()
    rows = search_modules(registry, query=query, app=app, limit=limit)

    if json_output:
        emit_json(data=rows, meta={"command": "catalog search", "query": query, "limit": limit})
        return

    if not rows:
        console.print("[yellow]No matching modules found.[/yellow]")
        return

    table = Table(title=f"Catalog Search ({len(rows)})")
    table.add_column("Module", style="cyan")
    table.add_column("App", style="green")
    table.add_column("Latest", style="white")
    table.add_column("Title", style="white")
    for row in rows:
        table.add_row(str(row.get("id", "")), str(row.get("app", "")), str(row.get("latestVersion", "")), str(row.get("title", "")))
    console.print(table)


@catalog_cli.command("module")
@click.argument("module_id", type=str)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_module(module_id: str, json_output: bool) -> None:
    """Show details for one module id."""
    registry, _, _ = load_registry_with_source()
    details = module_detail(registry, module_id)
    if details is None:
        if json_output:
            emit_json(ok=False, error=f"Module not found: {module_id}", meta={"command": "catalog module"})
            raise SystemExit(1)
        console.print(f"[red]Module not found: {module_id}[/red]")
        raise SystemExit(1)

    details = {
        **details,
        "catalogKnown": True,
        "tenantSeen": None,
        "tenantDeployable": None,
    }

    if json_output:
        emit_json(data=details, meta={"command": "catalog module"})
        return

    console.print_json(json.dumps(details, indent=2))


@catalog_cli.command("refresh")
@click.option("--force", is_flag=True, help="Force refresh even if cache exists")
@click.option("--package", "package_name", default=lambda: os.getenv("BOOST_CATALOG_PACKAGE", "@make-org/apps"), show_default=True, help="NPM package providing app/module metadata")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_refresh(force: bool, package_name: str, json_output: bool) -> None:
    """Refresh cached catalog from @make-org/apps."""
    try:
        result = refresh_catalog(force=force, package_name=package_name)
    except RuntimeError as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "catalog refresh"})
            raise SystemExit(1)
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    if json_output:
        emit_json(data=result, meta={"command": "catalog refresh"})
        return

    console.print(f"[green]Catalog refreshed[/green] {result['moduleCount']} modules, {result['appCount']} apps")
    console.print(f"[dim]Cache:[/dim] {result['cachePath']}")


@catalog_cli.command("auth")
@click.option("--scope", default="@make-org", show_default=True, help="NPM scope to authenticate")
@click.option("--registry", default="https://registry.npmjs.org/", show_default=True, help="Registry URL for the scope")
@click.option("--token", help="NPM auth token (falls back to MAKE_NPM_TOKEN env var)")
@click.option("--package", "package_name", default="@make-org/apps", show_default=True, help="Package to test after auth")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_auth(scope: str, registry: str, token: str | None, package_name: str, json_output: bool) -> None:
    """Configure npm auth for private catalog package access."""
    appdata = os.getenv("APPDATA", "").strip()
    windows_candidates: list[str] = []
    if appdata:
        windows_candidates.append(str(Path(appdata) / "npm" / "npm.cmd"))
    npm_bin = resolve_executable("npm", windows_candidates=windows_candidates)
    if npm_bin is None:
        message = "npm not found. Install Node.js/npm first."
        if json_output:
            emit_json(ok=False, error=message, meta={"command": "catalog auth"})
            raise SystemExit(1)
        console.print(f"[red]{message}[/red]")
        raise SystemExit(1)

    resolved_token = token or os.getenv("MAKE_NPM_TOKEN")
    if not resolved_token:
        resolved_token = click.prompt("NPM token", hide_input=True)

    parsed = urlparse(registry)
    host = parsed.netloc or parsed.path
    if not host:
        message = f"Invalid registry URL: {registry}"
        if json_output:
            emit_json(ok=False, error=message, meta={"command": "catalog auth"})
            raise SystemExit(1)
        console.print(f"[red]{message}[/red]")
        raise SystemExit(1)

    commands = [
        [npm_bin, "config", "set", f"{scope}:registry", registry],
        [npm_bin, "config", "set", f"//{host}/:_authToken", resolved_token],
    ]
    for command in commands:
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            message = process.stderr.strip() or process.stdout.strip() or "npm config failed"
            if json_output:
                emit_json(ok=False, error=message, meta={"command": "catalog auth"})
                raise SystemExit(1)
            console.print(f"[red]{message}[/red]")
            raise SystemExit(1)

    verify = subprocess.run([npm_bin, "view", package_name, "version"], capture_output=True, text=True, check=False)
    if verify.returncode != 0:
        message = verify.stderr.strip() or verify.stdout.strip() or "Package verification failed"
        if json_output:
            emit_json(ok=False, error=message, meta={"command": "catalog auth"})
            raise SystemExit(1)
        console.print(f"[red]{message}[/red]")
        raise SystemExit(1)

    payload = {
        "scope": scope,
        "registry": registry,
        "package": package_name,
        "packageVersion": verify.stdout.strip(),
    }
    if json_output:
        emit_json(data=payload, meta={"command": "catalog auth"})
        return

    console.print(f"[green]Catalog auth configured for {scope}[/green]")
    console.print(f"[dim]{package_name} version:[/dim] {payload['packageVersion']}")


@catalog_cli.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_doctor_cmd(json_output: bool) -> None:
    """Validate catalog integrity and report status."""
    result = catalog_doctor()
    if json_output:
        emit_json(ok=bool(result.get("ok")), error=(result.get("errors") or [None])[0], data=result, meta={"command": "catalog doctor"})
        if not result.get("ok"):
            raise SystemExit(1)
        return

    if result.get("ok"):
        console.print("[green]Catalog OK[/green]")
    else:
        console.print("[red]Catalog has errors[/red]")
    console.print(f"[bold]Source:[/bold] {result.get('source')}")
    console.print(f"[bold]Modules:[/bold] {result.get('moduleCount')}")
    console.print(f"[bold]Apps:[/bold] {result.get('appCount')}")
    if result.get("errors"):
        for error in result["errors"]:
            console.print(f"[red]- {error}[/red]")
    if not result.get("ok"):
        raise SystemExit(1)


@catalog_cli.command("templates")
@click.option("--refresh", is_flag=True, help="Fetch latest template catalog from make.com")
@click.option("--url", "templates_url", default=DEFAULT_TEMPLATES_URL, show_default=True, help="Templates page URL")
@click.option("--query", type=str, help="Filter templates by title, slug, URL, or app")
@click.option("--app", type=str, help="Filter templates by app name")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def catalog_templates(refresh: bool, templates_url: str, query: str | None, app: str | None, limit: int, json_output: bool) -> None:
    """Inspect cached template patterns from make.com templates pages."""
    registry, source, path = load_template_registry()

    if refresh or registry is None:
        try:
            registry = build_template_registry(templates_url=templates_url)
        except Exception as exc:
            if json_output:
                emit_json(ok=False, error=str(exc), meta={"command": "catalog templates"})
                raise SystemExit(1)
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1)
        path = save_template_registry(registry)
        source = "fresh"

    rows = search_templates(registry, query=query, app=app, limit=limit)
    meta = registry.get("meta", {}) if isinstance(registry, dict) else {}
    payload = {
        "source": source,
        "path": str(path) if path else None,
        "templateCount": meta.get("templateCount", 0),
        "url": meta.get("url", templates_url),
        "generatedAt": meta.get("generatedAt"),
        "items": rows,
    }

    if json_output:
        emit_json(data=payload, meta={"command": "catalog templates", "query": query, "app": app, "limit": limit})
        return

    if not rows:
        console.print("[yellow]No templates matched your filters.[/yellow]")
        console.print(f"[dim]Source:[/dim] {payload['source']}  [dim]Total catalog:[/dim] {payload['templateCount']}")
        return

    table = Table(title=f"Template Patterns ({len(rows)}/{payload['templateCount']})")
    table.add_column("Title", style="white")
    table.add_column("Apps", style="green")
    table.add_column("URL", style="cyan")
    for row in rows:
        apps = row.get("apps", [])
        app_text = ", ".join(str(item) for item in apps[:4])
        if isinstance(apps, list) and len(apps) > 4:
            app_text += ", ..."
        table.add_row(str(row.get("title", "")), app_text, str(row.get("url", "")))
    console.print(table)
    console.print(f"[dim]Source:[/dim] {payload['source']}  [dim]Cache:[/dim] {payload['path']}")
