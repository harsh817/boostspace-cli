"""Internet-first scenario builder commands."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
from click.core import ParameterSource
from rich.table import Table

from .client import APIClient, APIError
from .catalog.store import load_registry_with_source, known_module_ids
from .config import Config
from .console import console
from .docs_catalog import load_documented_app_slugs, load_documented_features, match_goal_apps
from .jsonio import emit_json
from .scenario_builder_core import (
    align_modules_to_known,
    apply_credentials,
    apply_field_mapping_hints,
    build_sample_payload,
    MODULE_COMPATIBILITY_RULES,
    build_draft,
    collect_placeholder_tokens,
    extract_blueprint,
    fetch_summary,
    inject_connection_ids,
    repair_blueprint_data,
    required_connection_apps,
    research_goal,
    seed_known_native_modules,
    slugify,
    unresolved_credential_tokens,
    validate_blueprint_data,
)
from .scenario_builder_helpers import (
    module_names_from_blueprint,
    normalize_schedule_type,
    parse_connection_pairs,
    parse_csv,
    resolve_team_id,
    team_connection_map,
    tenant_known_modules,
)
from .scenario_swarm import run_swarm
from .workspace_assets import extract_folders, extract_templates, find_folder_by_name, search_templates

TENANT_CACHE_TTL_SECONDS = 1800


@click.group("scenario")
def scenario_builder() -> None:
    """Research, draft, validate, and repair scenarios."""


@scenario_builder.command("modules")
@click.option("--limit", type=int, default=60, show_default=True, help="Scenarios to scan")
@click.option("--refresh", is_flag=True, help="Ignore cache and rescan tenant scenarios")
@click.option("--cache-ttl", type=int, default=TENANT_CACHE_TTL_SECONDS, show_default=True, help="Tenant module cache TTL in seconds")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_modules(ctx: click.Context, limit: int, refresh: bool, cache_ttl: int, json_output: bool) -> None:
    """List modules proven in your tenant from existing scenarios."""
    config: Config = ctx.obj["config"]
    catalog_modules = known_module_ids()
    with APIClient(config) as client:
        modules = sorted(
            tenant_known_modules(
                client,
                config.team_id,
                config.organization_id,
                scan_limit=limit,
                use_cache=True,
                refresh_cache=refresh,
                cache_ttl_seconds=cache_ttl,
            ),
            key=str.casefold,
        )
    module_rows = _module_confidence_rows(set(modules), set(modules), catalog_modules)

    if json_output:
        emit_json(data=module_rows, meta={"command": "scenario modules", "limit": limit, "refresh": bool(refresh), "cacheTtl": cache_ttl})
        return

    if not modules:
        console.print("[yellow]No modules discovered from current scenario set.[/yellow]")
        return

    for row in module_rows:
        console.print(f"{row['module']} [{row['confidence']}]")


@scenario_builder.command("catalog")
@click.option("--refresh", is_flag=True, help="Refresh docs app catalog from Boost docs")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def scenario_catalog(refresh: bool, json_output: bool) -> None:
    """Show native app catalog discovered from Boost docs."""
    apps = sorted(load_documented_app_slugs(refresh=refresh), key=str.casefold)
    features = sorted(load_documented_features(refresh=False), key=str.casefold)

    if json_output:
        emit_json(
            data={
                "appCount": len(apps),
                "featureCount": len(features),
                "source": "docs.boost.space",
                "apps": apps,
                "features": features,
            },
            meta={"command": "scenario catalog", "refresh": bool(refresh)},
        )
        return

    if not apps:
        console.print("[yellow]No app catalog entries found from docs cache/source.[/yellow]")
        return

    console.print(f"[green]Documented native apps: {len(apps)}[/green]")
    for app in apps:
        console.print(app)
    if features:
        console.print(f"[green]Documented platform features: {len(features)}[/green]")


@scenario_builder.command("swarm")
@click.option("--mode", type=click.Choice(["build", "debug"], case_sensitive=False), default="build", show_default=True)
@click.option("--goal", help="Build/debug goal in plain language")
@click.option("--scenario-id", type=int, help="Scenario ID for debug mode")
@click.option("--name", "scenario_name", help="Scenario name for debug mode")
@click.option("--team-id", type=int, help="Team ID override")
@click.option("--folder-name", help="Optional target folder hint for build mode")
@click.option("--parallelism", type=int, default=5, show_default=True, help="How many agents run concurrently")
@click.option("--cache-ttl", type=int, default=TENANT_CACHE_TTL_SECONDS, show_default=True, help="Tenant module cache TTL in seconds")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_swarm_cmd(
    ctx: click.Context,
    mode: str,
    goal: str | None,
    scenario_id: int | None,
    scenario_name: str | None,
    team_id: int | None,
    folder_name: str | None,
    parallelism: int,
    cache_ttl: int,
    json_output: bool,
) -> None:
    """Split build/debug workflow into parallel specialized sub-agents."""
    config: Config = ctx.obj["config"]
    selected_team_id = team_id or config.team_id

    try:
        result = run_swarm(
            mode=str(mode).casefold(),
            config=config,
            team_id=selected_team_id,
            goal=goal,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            folder_name=folder_name,
            parallelism=parallelism,
            cache_ttl=cache_ttl,
        )
    except ValueError as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "scenario swarm"})
            raise SystemExit(1)
        raise click.ClickException(str(exc))
    except APIError as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "scenario swarm"})
            raise SystemExit(1)
        raise click.ClickException(str(exc))

    if json_output:
        emit_json(
            data=result,
            meta={"command": "scenario swarm", "mode": mode, "parallelism": parallelism},
        )
        if result.get("failedAgents"):
            raise SystemExit(1)
        return

    console.print(f"[green]Swarm complete[/green] mode={result['mode']} parallelism={result['parallelism']}")
    console.print(f"[dim]Agents ok: {result['okAgents']} | failed: {result['failedAgents']} | duration: {result['durationSeconds']}s[/dim]")

    table = Table(title="Sub-Agent Results")
    table.add_column("Agent", style="white")
    table.add_column("Status", style="green")
    table.add_column("Duration (s)", style="cyan", no_wrap=True)
    table.add_column("Details", style="dim")
    for row in result.get("agents", []):
        ok = bool(row.get("ok"))
        status = "ok" if ok else "failed"
        details = ""
        if ok:
            data = row.get("data")
            if isinstance(data, dict):
                keys = ", ".join(list(data.keys())[:4])
                details = keys
        else:
            details = str(row.get("error", ""))
        table.add_row(str(row.get("agent", "")), status, str(row.get("durationSeconds", "-")), details)
    console.print(table)

    if result.get("mode") == "build":
        console.print("[dim]Next: boost scenario draft --goal \"...\" --use-workspace-templates --fast[/dim]")
    else:
        console.print("[dim]Next: boost executions history --name \"...\" --json[/dim]")

    if result.get("failedAgents"):
        raise SystemExit(1)


@scenario_builder.command("templates")
@click.option("--team-id", type=int, help="Team ID override")
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--query", help="Filter workspace templates by keyword")
@click.option("--public-only", is_flag=True, help="Prefer templates marked as public")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_templates(ctx: click.Context, team_id: int | None, limit: int, query: str | None, public_only: bool, json_output: bool) -> None:
    """List workspace scenario templates that can guide draft generation."""
    config: Config = ctx.obj["config"]
    tid = team_id or config.team_id

    with APIClient(config) as client:
        try:
            payload = client.list_workspace_templates(
                team_id=tid,
                organization_id=config.organization_id,
                limit=limit,
                query=query,
                public_only=public_only,
            )
        except APIError as exc:
            if json_output:
                emit_json(ok=False, error=str(exc), meta={"command": "scenario templates"})
                raise SystemExit(1)
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1)

    templates = extract_templates(payload)
    rows = search_templates(templates, query=query, public_only=public_only, limit=limit)

    if json_output:
        emit_json(
            data={
                "items": rows,
                "count": len(rows),
                "sourcePath": payload.get("_sourcePath") if isinstance(payload, dict) else None,
            },
            meta={"command": "scenario templates", "query": query, "publicOnly": bool(public_only), "limit": limit},
        )
        return

    if not rows:
        console.print("[yellow]No workspace templates found for your filter.[/yellow]")
        return

    table = Table(title=f"Workspace Templates ({len(rows)})")
    table.add_column("Name", style="white")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Public", style="green", no_wrap=True)
    table.add_column("Folder", style="magenta", no_wrap=True)
    for row in rows:
        public_text = "yes" if row.get("public") is True else ("no" if row.get("public") is False else "?")
        table.add_row(str(row.get("name", "")), str(row.get("id", "")), public_text, str(row.get("folderId") or "-"))
    console.print(table)


def _infer_trigger(goal: str) -> str:
    g = goal.casefold()
    schedule_markers = ("every ", "daily", "weekly", "monthly", "schedule", "cron", "hourly")
    return "schedule" if any(marker in g for marker in schedule_markers) else "webhook"


def _parse_credentials(credential_pairs: tuple[str, ...], credential_file: Path | None) -> dict[str, str]:
    credentials: dict[str, str] = {}

    if credential_file:
        parsed = json.loads(credential_file.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise click.ClickException("--credential-file must contain a JSON object")
        for key, value in parsed.items():
            if value is None:
                continue
            credentials[str(key).strip()] = str(value)

    for pair in credential_pairs:
        if "=" not in pair:
            raise click.ClickException(f"--credential must be KEY=VALUE (got '{pair}')")
        key, value = pair.split("=", 1)
        key = key.strip()
        if not key:
            raise click.ClickException(f"Credential key cannot be empty (got '{pair}')")
        credentials[key] = value

    # Environment variables are fallback (do not override explicit values)
    for key, value in os.environ.items():
        if key not in credentials:
            credentials[key] = value

    return credentials


def _load_sample_data(sample_file: Path | None, sample_json: str | None) -> dict[str, object]:
    sample: dict[str, object] = {}
    if sample_file:
        loaded = json.loads(sample_file.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise click.ClickException("--sample-file must contain a JSON object")
        sample = {str(k): v for k, v in loaded.items()}

    if sample_json:
        loaded = json.loads(sample_json)
        if not isinstance(loaded, dict):
            raise click.ClickException("--sample-json must be a JSON object")
        sample.update({str(k): v for k, v in loaded.items()})

    return sample


def _resolve_profile(profile: str, fast: bool) -> str:
    if fast:
        return "fast"
    return str(profile).casefold()


def _param_is_default(ctx: click.Context, param_name: str) -> bool:
    source = ctx.get_parameter_source(param_name)
    return source in {ParameterSource.DEFAULT, ParameterSource.DEFAULT_MAP}


def _module_confidence_rows(
    modules: set[str],
    tenant_modules: set[str],
    catalog_modules: set[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for module in sorted(modules, key=str.casefold):
        tenant_seen = module in tenant_modules
        catalog_known = module in catalog_modules
        tenant_deployable = tenant_seen
        if tenant_seen:
            confidence = "tenant_proven"
        elif catalog_known:
            confidence = "catalog_known"
        else:
            confidence = "unknown"
        rows.append(
            {
                "module": module,
                "confidence": confidence,
                "catalogKnown": catalog_known,
                "tenantSeen": tenant_seen,
                "tenantDeployable": tenant_deployable,
            }
        )
    return rows


def _live_probe_scenario_create(
    client: APIClient,
    *,
    team_id: int,
    blueprint: dict,
    scheduling: dict[str, object],
    folder_id: int | None,
    scenario_name: str,
) -> dict[str, object]:
    probe_name = f"{scenario_name} [compat-probe {uuid.uuid4().hex[:8]}]"
    created_id: int | None = None
    try:
        result = client.create_scenario(
            team_id=team_id,
            blueprint=blueprint,
            scheduling=scheduling,
            name=probe_name,
            folder_id=folder_id,
        )
        created = result.get("scenario", result)
        created_id = int(created.get("id"))
        return {
            "checked": True,
            "ok": True,
            "probeScenarioId": created_id,
            "probeName": probe_name,
        }
    except APIError as exc:
        return {
            "checked": True,
            "ok": False,
            "error": str(exc),
            "detail": exc.detail,
            "probeName": probe_name,
        }
    finally:
        if created_id is not None:
            try:
                client.delete_scenario(created_id)
            except APIError:
                pass


def _catalog_staleness_days() -> float | None:
    registry, _, _ = load_registry_with_source()
    meta = registry.get("meta", {}) if isinstance(registry, dict) else {}
    generated_at = meta.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at.strip():
        return None

    try:
        created_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    delta = datetime.now(timezone.utc) - created_at
    return delta.total_seconds() / 86400.0


def _resolve_folder_id(
    client: APIClient,
    team_id: int | None,
    organization_id: int | None,
    folder_id: int | None,
    folder_name: str | None,
    create_folder: bool,
    parent_folder_id: int | None,
) -> int | None:
    if folder_id is not None:
        return int(folder_id)
    if not folder_name:
        return None

    payload = client.list_scenario_folders(team_id=team_id, organization_id=organization_id, limit=300)
    folders = extract_folders(payload)
    match, candidates = find_folder_by_name(folders, folder_name)
    if match is not None:
        resolved = match.get("id")
        if isinstance(resolved, int):
            return resolved

    if len(candidates) > 1:
        names = ", ".join(str(item.get("name", "")) for item in candidates[:8])
        raise click.ClickException(f"Multiple folders match '{folder_name}': {names}")

    if create_folder:
        created = client.create_scenario_folder(
            name=folder_name,
            team_id=team_id,
            organization_id=organization_id,
            parent_id=parent_folder_id,
        )
        folder_payload = created.get("folder", created)
        created_id = folder_payload.get("id") if isinstance(folder_payload, dict) else None
        if isinstance(created_id, int):
            return created_id
        raise click.ClickException("Folder creation did not return a valid folder ID")

    raise click.ClickException(
        f"Folder '{folder_name}' not found. Use --create-folder to create it or pass --folder-id explicitly."
    )


@scenario_builder.command("coach")
@click.option("--goal", help="Workflow outcome in plain language")
@click.option("--team-id", type=int, help="Team ID override")
@click.option("--output", type=click.Path(path_type=Path), help="Where to write draft JSON")
@click.option("--non-interactive", is_flag=True, help="Skip prompts and use defaults")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_coach(
    ctx: click.Context,
    goal: str | None,
    team_id: int | None,
    output: Path | None,
    non_interactive: bool,
    json_output: bool,
) -> None:
    """Low-friction guided brainstorm + draft generation."""
    config: Config = ctx.obj["config"]

    if not goal:
        if non_interactive:
            raise click.ClickException("Provide --goal when using --non-interactive")
        goal = click.prompt("What should this workflow do?")

    goal_text = str(goal)

    inferred_trigger = _infer_trigger(goal_text)
    trigger = inferred_trigger
    native_only = True
    if not non_interactive:
        trigger = click.prompt(
            "Suggested trigger",
            default=inferred_trigger,
            type=click.Choice(["webhook", "schedule"], case_sensitive=False),
        )
        native_only = click.confirm("Use native modules only?", default=True)

    docs_apps = load_documented_app_slugs(refresh=False)
    docs_features = load_documented_features(refresh=False)
    matched_apps = sorted(match_goal_apps(goal_text, docs_apps))
    matched_features = sorted(match_goal_apps(goal_text, docs_features))

    try:
        with APIClient(config) as client:
            resolved_team_id = resolve_team_id(client, config, team_id)
            known_modules = tenant_known_modules(client, config.team_id, config.organization_id, scan_limit=80)
            connections = team_connection_map(client, resolved_team_id)
    except (APIError, click.ClickException) as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "scenario coach"})
            raise SystemExit(1)
        raise

    app_status: list[dict[str, object]] = []
    for app in matched_apps:
        has_connection = app in connections
        has_native_modules = any(module.startswith(f"{app}:") for module in known_modules)
        app_status.append(
            {
                "app": app,
                "connectionId": connections.get(app),
                "hasConnection": has_connection,
                "hasTenantModule": has_native_modules,
                "ready": bool(has_connection and has_native_modules),
            }
        )

    sources = research_goal(goal_text, max_results=4)
    draft = build_draft(goal_text, sources, trigger=trigger, connections=connections or None)
    draft_blueprint = extract_blueprint(draft)
    draft_blueprint, seeded_modules = seed_known_native_modules(draft_blueprint, set(matched_apps), known_modules)
    draft_blueprint, replacements = align_modules_to_known(draft_blueprint, known_modules)

    required_apps = sorted(required_connection_apps(draft_blueprint))
    missing_apps = [app for app in required_apps if app not in connections]

    if native_only:
        http_modules = sorted(module for module in module_names_from_blueprint(draft_blueprint) if module.startswith("http:"))
        if http_modules:
            message = "Native-only mode blocked HTTP fallback modules: " + ", ".join(http_modules)
            if json_output:
                emit_json(
                    ok=False,
                    error=message,
                    data={"httpModules": http_modules, "goal": goal_text},
                    meta={"command": "scenario coach"},
                )
                raise SystemExit(1)
            raise click.ClickException(message)

    if output is None:
        output = Path.cwd() / f"draft-{slugify(goal_text)}.json"

    write_draft = True
    if not non_interactive:
        write_draft = click.confirm("Create draft file now?", default=True)

    if write_draft:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(draft, indent=2), encoding="utf-8")

    recommendations: list[str] = []
    if missing_apps:
        recommendations.append("Create missing native app connections: " + ", ".join(missing_apps))
    if matched_apps and not any(item["ready"] for item in app_status):
        recommendations.append("Run `boost scenario modules` and use tenant-proven modules for matched apps")
    recommendations.append("Run `boost scenario validate --file <draft>` before deploy")
    recommendations.append("Run `boost scenario deploy --file <draft> --dry-run` before real deploy")

    if json_output:
        emit_json(
            ok=not missing_apps,
            error=("Missing connections for: " + ", ".join(missing_apps)) if missing_apps else None,
            data={
                "goal": goal_text,
                "trigger": trigger,
                "nativeOnly": native_only,
                "teamId": resolved_team_id,
                "goalAppsFromDocs": matched_apps,
                "goalFeaturesFromDocs": matched_features,
                "appStatus": app_status,
                "seededNativeModules": seeded_modules,
                "alignedModules": replacements,
                "requiredConnectionApps": required_apps,
                "missingConnectionApps": missing_apps,
                "draftOutput": str(output) if write_draft else None,
                "recommendations": recommendations,
            },
            meta={"command": "scenario coach"},
        )
        if missing_apps:
            raise SystemExit(1)
        return

    table = Table(title="Workflow Coach")
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Goal", goal_text)
    table.add_row("Trigger", trigger)
    table.add_row("Native only", "yes" if native_only else "no")
    table.add_row("Matched apps", ", ".join(matched_apps) or "-")
    table.add_row("Missing connections", ", ".join(missing_apps) or "none")
    table.add_row("Draft", str(output) if write_draft else "not written")
    console.print(table)

    if recommendations:
        console.print("[bold]Recommended next steps:[/bold]")
        for recommendation in recommendations:
            console.print(f"- {recommendation}")

    if missing_apps:
        raise SystemExit(1)


@scenario_builder.command("setup")
@click.option("--app", "apps", multiple=True, help="App key to prepare (repeatable), e.g. --app google-sheets")
@click.option("--file", "file_path", type=click.Path(exists=True, path_type=Path), help="Draft/blueprint file to infer required app connections")
@click.option("--team-id", type=int, help="Team ID override")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_setup(
    ctx: click.Context,
    apps: tuple[str, ...],
    file_path: Path | None,
    team_id: int | None,
    json_output: bool,
) -> None:
    """Check native app connection readiness for draft/deploy."""
    config: Config = ctx.obj["config"]
    requested_apps = {app.strip().casefold() for app in apps if app.strip()}

    inferred_apps: set[str] = set()
    if file_path:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        inferred_apps = required_connection_apps(extract_blueprint(payload))

    target_apps = sorted(requested_apps | inferred_apps)

    with APIClient(config) as client:
        try:
            resolved_team_id = resolve_team_id(client, config, team_id)
            connections = team_connection_map(client, resolved_team_id)
        except (APIError, click.ClickException) as exc:
            if json_output:
                emit_json(ok=False, error=str(exc), meta={"command": "scenario setup"})
                raise SystemExit(1)
            raise

    if not target_apps:
        target_apps = sorted(connections.keys())

    found = [{"app": app, "connectionId": connections[app]} for app in target_apps if app in connections]
    missing = [app for app in target_apps if app not in connections]

    if json_output:
        emit_json(
            ok=not missing,
            error=("Missing connections for: " + ", ".join(missing)) if missing else None,
            data={
                "teamId": resolved_team_id,
                "requestedApps": target_apps,
                "found": found,
                "missing": missing,
            },
            meta={"command": "scenario setup"},
        )
        if missing:
            raise SystemExit(1)
        return

    if found:
        table = Table(title="Native App Connection Setup")
        table.add_column("App", style="white")
        table.add_column("Connection ID", style="cyan")
        for item in found:
            table.add_row(item["app"], str(item["connectionId"]))
        console.print(table)

    if missing:
        console.print("[yellow]Missing app connections:[/yellow] " + ", ".join(missing))
        console.print("[dim]Create these connections in Boost.space, then re-run setup/deploy.[/dim]")
        raise SystemExit(1)


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
@click.option("--trigger", type=click.Choice(["webhook", "schedule"], case_sensitive=False), default="webhook", show_default=True, help="Trigger type")
@click.option("--connection", "connection_pairs", multiple=True, metavar="APP:ID",
              help="Real connection ID for a native app module, e.g. --connection openai-gpt-3:42. Repeat for multiple.")
@click.option("--use-workspace-templates/--no-use-workspace-templates", default=True, show_default=True, help="Use workspace public templates as planning signal")
@click.option("--workspace-template-limit", type=int, default=80, show_default=True, help="How many workspace templates to scan")
@click.option("--template-match-limit", type=int, default=5, show_default=True, help="How many matched templates to attach")
@click.option("--profile", type=click.Choice(["safe", "balanced", "fast"], case_sensitive=False), default="safe", show_default=True, help="Draft speed/safety profile")
@click.option("--fast", "fast_mode", is_flag=True, help="Shortcut for --profile fast")
@click.option("--tenant-scan-limit", type=int, default=60, show_default=True, help="How many scenarios to scan for tenant-proven modules")
@click.option("--refresh-tenant-modules", is_flag=True, help="Force tenant module rescan (ignore cache)")
@click.option("--cache-ttl", type=int, default=TENANT_CACHE_TTL_SECONDS, show_default=True, help="Tenant module cache TTL in seconds")
@click.option("--max-results", type=int, default=6, show_default=True)
@click.option("--timings", is_flag=True, help="Include stage timings in output")
@click.option("--output", type=click.Path(path_type=Path), help="Output path for draft JSON")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_draft(
    ctx: click.Context,
    goal: str | None,
    spec_file: Path | None,
    trigger: str,
    connection_pairs: tuple[str, ...],
    use_workspace_templates: bool,
    workspace_template_limit: int,
    template_match_limit: int,
    profile: str,
    fast_mode: bool,
    tenant_scan_limit: int,
    refresh_tenant_modules: bool,
    cache_ttl: int,
    max_results: int,
    timings: bool,
    output: Path | None,
    json_output: bool,
) -> None:
    """Draft a blueprint from internet research and heuristics."""
    if spec_file:
        spec_payload = json.loads(spec_file.read_text(encoding="utf-8"))
        goal = spec_payload.get("draftGoal") or spec_payload.get("goal")
        trigger = spec_payload.get("trigger", trigger)

    trigger = str(trigger).casefold()

    if not goal:
        raise click.ClickException("Provide --goal or --spec")

    resolved_profile = _resolve_profile(profile, fast_mode)
    if resolved_profile not in {"safe", "balanced", "fast"}:
        raise click.ClickException(f"Unsupported profile: {resolved_profile}")

    effective_max_results = int(max_results)
    effective_scan_limit = int(tenant_scan_limit)
    effective_use_workspace_templates = bool(use_workspace_templates)
    effective_workspace_template_limit = int(workspace_template_limit)
    effective_template_match_limit = max(1, int(template_match_limit))
    if resolved_profile == "balanced":
        if _param_is_default(ctx, "max_results"):
            effective_max_results = 4
        if _param_is_default(ctx, "tenant_scan_limit"):
            effective_scan_limit = 30
        if _param_is_default(ctx, "workspace_template_limit"):
            effective_workspace_template_limit = 60
    elif resolved_profile == "fast":
        if _param_is_default(ctx, "max_results"):
            effective_max_results = 2
        if _param_is_default(ctx, "tenant_scan_limit"):
            effective_scan_limit = 0
        if _param_is_default(ctx, "use_workspace_templates"):
            effective_use_workspace_templates = False
        if _param_is_default(ctx, "workspace_template_limit"):
            effective_workspace_template_limit = 30

    profile_notes: list[str] = []
    if resolved_profile == "balanced":
        profile_notes.append("balanced profile: moderate research depth and tenant scan")
    if resolved_profile == "fast":
        profile_notes.append("fast profile: minimal research depth and cache-first tenant modules")
    if effective_use_workspace_templates:
        profile_notes.append("workspace templates enabled for draft hints")

    stage_timings: dict[str, float] = {}
    t0 = time.perf_counter()

    manual_connections = parse_connection_pairs(connection_pairs)
    auto_connections: dict[str, int] = {}
    matched_workspace_templates: list[dict[str, object]] = []
    template_source_path: str | None = None
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        try:
            resolved_team_id = resolve_team_id(client, config, config.team_id)
            auto_connections = team_connection_map(client, resolved_team_id)
        except Exception:
            auto_connections = {}
        else:
            if effective_use_workspace_templates:
                try:
                    template_payload = client.list_workspace_templates(
                        team_id=resolved_team_id,
                        organization_id=config.organization_id,
                        limit=effective_workspace_template_limit,
                        public_only=True,
                    )
                    template_source_path = template_payload.get("_sourcePath") if isinstance(template_payload, dict) else None
                    templates = extract_templates(template_payload)
                    matched_workspace_templates = search_templates(
                        templates,
                        query=goal,
                        public_only=True,
                        limit=effective_template_match_limit,
                    )
                except Exception:
                    profile_notes.append("workspace templates unavailable in this workspace context")
    stage_timings["connections"] = round(time.perf_counter() - t0, 3)

    connections = {**auto_connections, **manual_connections}

    t1 = time.perf_counter()
    sources = research_goal(goal, max_results=effective_max_results)
    if matched_workspace_templates:
        template_sources = [
            {
                "title": f"Workspace template: {item.get('name', 'Template')}",
                "url": str(item.get("url") or f"workspace-template://{item.get('id')}")
            }
            for item in matched_workspace_templates
        ]
        sources = template_sources + sources
    stage_timings["research"] = round(time.perf_counter() - t1, 3)

    t2 = time.perf_counter()
    draft = build_draft(goal, sources, trigger=trigger, connections=connections or None)
    stage_timings["draftBuild"] = round(time.perf_counter() - t2, 3)

    known_modules: set[str] = set()
    seeded_modules: list[str] = []
    docs_goal_apps: list[str] = []
    docs_goal_features: list[str] = []
    uncovered_docs_apps: list[str] = []
    module_confidence: list[dict[str, str]] = []
    catalog_modules = known_module_ids()

    t3 = time.perf_counter()

    with APIClient(config) as client:
        try:
            known_modules = tenant_known_modules(
                client,
                config.team_id,
                config.organization_id,
                scan_limit=effective_scan_limit,
                use_cache=True,
                refresh_cache=refresh_tenant_modules,
                cache_ttl_seconds=cache_ttl,
            )
            draft_blueprint = extract_blueprint(draft)
            docs_apps = load_documented_app_slugs(refresh=False)
            docs_features = load_documented_features(refresh=False)
            docs_goal_apps = sorted(match_goal_apps(goal, docs_apps))
            docs_goal_features = sorted(match_goal_apps(goal, docs_features))
            draft_blueprint, seeded_modules = seed_known_native_modules(
                draft_blueprint,
                set(docs_goal_apps),
                known_modules,
            )
            draft_blueprint, _ = align_modules_to_known(draft_blueprint, known_modules)

            if docs_goal_apps:
                flow_apps = {module.split(":", 1)[0].casefold() for module in module_names_from_blueprint(draft_blueprint)}
                uncovered_docs_apps = sorted(app for app in docs_goal_apps if app not in flow_apps)

            module_confidence = _module_confidence_rows(
                module_names_from_blueprint(draft_blueprint),
                known_modules,
                catalog_modules,
            )
        except Exception:
            pass
    stage_timings["tenantKnowledge"] = round(time.perf_counter() - t3, 3)

    catalog_age_days = _catalog_staleness_days()
    if catalog_age_days is not None and catalog_age_days > 7:
        profile_notes.append(f"catalog is {catalog_age_days:.1f} days old; run `boost catalog refresh --force`")

    if output is None:
        output = Path.cwd() / f"draft-{slugify(goal)}.json"

    if module_confidence:
        draft["moduleConfidence"] = module_confidence

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(draft, indent=2), encoding="utf-8")

    total_seconds = round(sum(stage_timings.values()), 3)
    if json_output:
        emit_json(
            data={
                "goal": goal,
                "output": str(output),
                "moduleCount": len(extract_blueprint(draft).get("flow", [])),
                "profile": resolved_profile,
                "maxResults": effective_max_results,
                "tenantScanLimit": effective_scan_limit,
                "resolvedConnections": connections,
                "workspaceTemplateMatches": matched_workspace_templates,
                "workspaceTemplateSource": template_source_path,
                "goalAppsFromDocs": docs_goal_apps,
                "goalFeaturesFromDocs": docs_goal_features,
                "seededNativeModules": seeded_modules,
                "uncoveredGoalApps": uncovered_docs_apps,
                "moduleConfidence": module_confidence,
                "profileNotes": profile_notes,
                "catalogAgeDays": round(catalog_age_days, 2) if catalog_age_days is not None else None,
                "timings": stage_timings if timings else None,
                "totalSeconds": total_seconds,
            },
            meta={"command": "scenario draft", "profile": resolved_profile},
        )
        return

    console.print(f"[green]Draft created:[/green] {output}")
    if resolved_profile != "safe":
        console.print(f"[dim]Profile:[/dim] {resolved_profile}")
    for note in profile_notes:
        console.print(f"[dim]{note}[/dim]")
    if seeded_modules:
        console.print("[dim]Seeded native modules from tenant-known apps:[/dim]")
        for module_name in seeded_modules:
            console.print(f"[dim]- {module_name}[/dim]")
    if matched_workspace_templates:
        console.print(f"[dim]Workspace templates matched: {len(matched_workspace_templates)}[/dim]")
    if uncovered_docs_apps:
        console.print("[yellow]Goal includes documented apps without mapped native modules:[/yellow] " + ", ".join(uncovered_docs_apps))
        console.print("[dim]Run `boost scenario setup --app <app>` and ensure tenant-proven modules exist.[/dim]")
    if timings:
        console.print(f"[dim]Timings (s): {stage_timings} | total={total_seconds}[/dim]")
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
            connections = ""

    trigger = trigger or "webhook"
    destinations = destinations or "sheet"
    required_fields = required_fields or "name,email"
    optional_fields = optional_fields or "phone,source"
    connections = connections or ""

    destination_list = parse_csv(destinations)
    required_list = parse_csv(required_fields)
    optional_list = parse_csv(optional_fields)
    connection_list = parse_csv(connections)

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
@click.option("--folder-id", type=int, help="Target folder ID")
@click.option("--folder-name", help="Target folder name")
@click.option("--create-folder", is_flag=True, help="Create folder when --folder-name does not exist")
@click.option("--folder-parent-id", type=int, help="Optional parent folder ID when creating a folder")
@click.option(
    "--schedule-type",
    type=click.Choice(["on-demand", "indefinitely", "once", "immediately"], case_sensitive=False),
    default="on-demand",
    show_default=True,
)
@click.option("--interval", type=int, default=3600, show_default=True, help="Interval in seconds for indefinitely")
@click.option("--inactive", is_flag=True, help="Deactivate right after creation")
@click.option("--dry-run", is_flag=True, help="Validate and resolve target context without creating")
@click.option("--repair", is_flag=True, help="Auto-repair draft in-memory before deploy")
@click.option("--guard-compat/--no-guard-compat", default=True, show_default=True, help="Block deploy when modules are not proven in tenant")
@click.option("--profile", type=click.Choice(["safe", "balanced", "fast"], case_sensitive=False), default="safe", show_default=True, help="Deploy speed/safety profile")
@click.option("--fast", "fast_mode", is_flag=True, help="Shortcut for --profile fast")
@click.option("--allow-http-fallback", is_flag=True, help="Allow HTTP modules when no native module exists")
@click.option("--allow-unknown-modules", is_flag=True, help="Allow modules missing from offline catalog")
@click.option("--credential", "credential_pairs", multiple=True, metavar="KEY=VALUE", help="Credential value to inject into placeholders")
@click.option("--credential-file", type=click.Path(exists=True, path_type=Path), help="JSON file with credential key/value pairs")
@click.option("--sample-file", type=click.Path(exists=True, path_type=Path), help="Sample JSON payload for field mapping + verification run")
@click.option("--sample-json", help="Inline sample JSON payload for field mapping + verification run")
@click.option("--map-fields/--no-map-fields", default=True, show_default=True, help="Auto-map known field placeholders from sample payload")
@click.option("--verify-run/--no-verify-run", default=True, show_default=True, help="Run scenario once after deploy and inspect execution status")
@click.option("--scan-limit", type=int, default=60, show_default=True, help="How many scenarios to scan for known modules")
@click.option("--refresh-tenant-modules", is_flag=True, help="Force tenant module rescan (ignore cache)")
@click.option("--cache-ttl", type=int, default=TENANT_CACHE_TTL_SECONDS, show_default=True, help="Tenant module cache TTL in seconds")
@click.option("--catalog-max-age-days", type=int, default=7, show_default=True, help="Warn when catalog is older than this")
@click.option("--timings", is_flag=True, help="Include stage timings in output")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def scenario_deploy(
    ctx: click.Context,
    file_path: Path,
    override_name: str | None,
    team_id: int | None,
    folder_id: int | None,
    folder_name: str | None,
    create_folder: bool,
    folder_parent_id: int | None,
    schedule_type: str,
    interval: int,
    inactive: bool,
    dry_run: bool,
    repair: bool,
    guard_compat: bool,
    profile: str,
    fast_mode: bool,
    allow_http_fallback: bool,
    allow_unknown_modules: bool,
    credential_pairs: tuple[str, ...],
    credential_file: Path | None,
    sample_file: Path | None,
    sample_json: str | None,
    map_fields: bool,
    verify_run: bool,
    scan_limit: int,
    refresh_tenant_modules: bool,
    cache_ttl: int,
    catalog_max_age_days: int,
    timings: bool,
    json_output: bool,
) -> None:
    """Deploy a draft/blueprint to Boost.space with preflight checks."""
    config: Config = ctx.obj["config"]
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    blueprint = extract_blueprint(payload)
    goal = str(payload.get("goal", "Workflow"))
    schedule_type = normalize_schedule_type(schedule_type)

    resolved_profile = _resolve_profile(profile, fast_mode)
    if resolved_profile not in {"safe", "balanced", "fast"}:
        raise click.ClickException(f"Unsupported profile: {resolved_profile}")

    effective_guard_compat = bool(guard_compat)
    effective_verify_run = bool(verify_run)
    effective_scan_limit = int(scan_limit)
    if resolved_profile == "balanced":
        if _param_is_default(ctx, "verify_run"):
            effective_verify_run = False
        if _param_is_default(ctx, "scan_limit"):
            effective_scan_limit = 30
    elif resolved_profile == "fast":
        if _param_is_default(ctx, "guard_compat"):
            effective_guard_compat = False
        if _param_is_default(ctx, "verify_run"):
            effective_verify_run = False
        if _param_is_default(ctx, "scan_limit"):
            effective_scan_limit = 0

    profile_notes: list[str] = []
    if resolved_profile == "balanced":
        profile_notes.append("balanced profile: verification disabled by default")
    if resolved_profile == "fast":
        profile_notes.append("fast profile: compatibility scan and verify-run are reduced")

    stage_timings: dict[str, float] = {}

    t_preflight = time.perf_counter()
    try:
        credentials = _parse_credentials(credential_pairs, credential_file)
        user_sample = _load_sample_data(sample_file, sample_json)
    except click.ClickException as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "scenario deploy"})
            raise SystemExit(1)
        raise

    blueprint, credential_replacements = apply_credentials(blueprint, credentials)
    unresolved_credentials = unresolved_credential_tokens(blueprint)
    if unresolved_credentials:
        msg = (
            "Missing credential values for placeholders: "
            + ", ".join(unresolved_credentials)
            + ". Provide with --credential KEY=VALUE or --credential-file."
        )
        if json_output:
            emit_json(
                ok=False,
                error=msg,
                data={"missingCredentials": unresolved_credentials},
                meta={"command": "scenario deploy"},
            )
            raise SystemExit(1)
        raise click.ClickException(msg)

    mapping_fixes: list[str] = []
    if map_fields and user_sample:
        blueprint, mapping_fixes = apply_field_mapping_hints(blueprint, user_sample)

    sample_payload = build_sample_payload(blueprint, user_sample)
    stage_timings["preflight"] = round(time.perf_counter() - t_preflight, 3)

    if schedule_type == "indefinitely" and interval <= 0:
        msg = "--interval must be a positive integer when --schedule-type indefinitely"
        if json_output:
            emit_json(ok=False, error=msg, meta={"command": "scenario deploy"})
            raise SystemExit(1)
        raise click.ClickException(msg)

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

    runtime_tokens = sorted(
        token
        for token in collect_placeholder_tokens(blueprint)
        if "." not in token and not token.startswith("connection_") and token not in credentials
    )

    catalog_age_days = _catalog_staleness_days()
    if catalog_age_days is not None and catalog_age_days > max(0, int(catalog_max_age_days)):
        profile_notes.append(f"catalog is {catalog_age_days:.1f} days old; run `boost catalog refresh --force`")

    with APIClient(config) as client:
        t_api_setup = time.perf_counter()
        try:
            me = client.get_user()
            user = me.get("authUser") or me.get("user") or me
            resolved_team_id = resolve_team_id(client, config, team_id)
            resolved_folder_id = _resolve_folder_id(
                client,
                resolved_team_id,
                config.organization_id,
                folder_id=folder_id,
                folder_name=folder_name,
                create_folder=create_folder,
                parent_folder_id=folder_parent_id,
            )
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
        stage_timings["apiContext"] = round(time.perf_counter() - t_api_setup, 3)

        scenario_name = override_name or blueprint.get("name") or f"Draft - {goal[:50]}"
        scheduling: dict[str, object] = {"type": schedule_type}
        if schedule_type == "indefinitely":
            scheduling["interval"] = int(interval)

        live_probe_result: dict[str, object] | None = None

        t_connections = time.perf_counter()
        required_apps = sorted(required_connection_apps(blueprint))
        connections = team_connection_map(client, resolved_team_id)
        blueprint, wired_count, missing_apps = inject_connection_ids(blueprint, connections)
        stage_timings["connections"] = round(time.perf_counter() - t_connections, 3)

        blueprint_modules = module_names_from_blueprint(blueprint)
        http_modules = sorted(module for module in blueprint_modules if module.startswith("http:"))
        if http_modules and not allow_http_fallback:
            msg = (
                "HTTP fallback modules detected: "
                + ", ".join(http_modules)
                + ". Re-run with --allow-http-fallback only if native modules are unavailable."
            )
            if json_output:
                emit_json(
                    ok=False,
                    error=msg,
                    data={"httpModules": http_modules},
                    meta={"command": "scenario deploy"},
                )
                raise SystemExit(1)
            raise click.ClickException(msg)

        if missing_apps:
            msg = (
                "Missing native app connections for: "
                + ", ".join(missing_apps)
                + ". Use `boost connections list` to create/link these before deploy."
            )
            if json_output:
                emit_json(
                    ok=False,
                    error=msg,
                    data={"missingApps": missing_apps, "requiredApps": required_apps},
                    meta={"command": "scenario deploy"},
                )
                raise SystemExit(1)
            raise click.ClickException(msg)

        known_modules: set[str] = set()
        catalog_modules = known_module_ids()
        unknown_modules: list[str] = []
        unproven_tenant_modules: list[str] = []

        if effective_guard_compat:
            t_compat = time.perf_counter()
            known_modules = tenant_known_modules(
                client,
                config.team_id,
                config.organization_id,
                scan_limit=effective_scan_limit,
                use_cache=True,
                refresh_cache=refresh_tenant_modules,
                cache_ttl_seconds=cache_ttl,
            )
            blueprint, replacements = align_modules_to_known(blueprint, known_modules)
            if replacements and not json_output:
                console.print("[dim]Aligned modules to tenant-known variants:[/dim]")
                for replacement in replacements:
                    console.print(f"[dim]- {replacement}[/dim]")
            blueprint_modules = module_names_from_blueprint(blueprint)
            unknown_modules = sorted(module for module in blueprint_modules if module not in catalog_modules)
            unproven_tenant_modules = sorted(module for module in blueprint_modules if module not in known_modules and module in catalog_modules)

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
                if allow_unknown_modules:
                    if not json_output:
                        console.print("[yellow]Proceeding with unknown modules (override enabled):[/yellow]")
                        for module in unknown_modules:
                            console.print(f"  [yellow]-[/yellow] {module}")
                else:
                    if json_output:
                        emit_json(
                            ok=False,
                            error="Deploy blocked: modules missing from offline catalog.",
                            data={"modules": unknown_modules},
                            meta={"command": "scenario deploy"},
                        )
                        raise SystemExit(1)
                    console.print("[red]Deploy blocked: modules missing from offline catalog.[/red]")
                    for module in unknown_modules:
                        console.print(f"  [red]-[/red] {module}")
                    console.print("[dim]Run `boost catalog refresh` to update registry.[/dim]")
                    console.print("[dim]Or bypass once with --allow-unknown-modules.[/dim]")
                    raise SystemExit(1)

            if unproven_tenant_modules and not json_output:
                console.print("[yellow]Warning: modules not yet proven in this tenant scan:[/yellow]")
                for module in unproven_tenant_modules:
                    console.print(f"  [yellow]-[/yellow] {module}")
                console.print("[dim]Continuing because modules are known in offline registry.[/dim]")
            stage_timings["compatScan"] = round(time.perf_counter() - t_compat, 3)

        module_confidence = _module_confidence_rows(blueprint_modules, known_modules, catalog_modules)

        t_live_probe = time.perf_counter()
        live_probe_result = _live_probe_scenario_create(
            client,
            team_id=resolved_team_id,
            blueprint=blueprint,
            scheduling=scheduling,
            folder_id=resolved_folder_id,
            scenario_name=scenario_name,
        )
        stage_timings["liveCompatProbe"] = round(time.perf_counter() - t_live_probe, 3)

        if not bool(live_probe_result.get("ok")):
            error_msg = f"Live compatibility probe failed: {live_probe_result.get('error', 'unknown error')}"
            if json_output:
                emit_json(
                    ok=False,
                    error=error_msg,
                    data={
                        "liveCompatibility": live_probe_result,
                        "requiredConnectionApps": required_apps,
                        "autoWiredConnections": wired_count,
                        "runtimeTokens": runtime_tokens,
                    },
                    meta={"command": "scenario deploy", "dryRun": bool(dry_run), "profile": resolved_profile},
                )
                raise SystemExit(1)
            console.print(f"[red]{error_msg}[/red]")
            raise SystemExit(1)

        if resolved_profile == "balanced" and _param_is_default(ctx, "verify_run") and not inactive:
            effective_verify_run = bool(unproven_tenant_modules)
            if effective_verify_run:
                profile_notes.append("balanced profile enabled verify-run due tenant-unproven modules")

        if dry_run:
            total_seconds = round(sum(stage_timings.values()), 3)
            if json_output:
                emit_json(
                    data={
                        "dryRun": True,
                        "profile": resolved_profile,
                        "guardCompat": effective_guard_compat,
                        "verifyRun": effective_verify_run,
                        "scanLimit": effective_scan_limit,
                        "user": user.get("email", "unknown"),
                        "teamId": resolved_team_id,
                        "folderId": resolved_folder_id,
                        "scenarioName": scenario_name,
                        "scheduleType": schedule_type,
                        "requiredConnectionApps": required_apps,
                        "autoWiredConnections": wired_count,
                        "credentialReplacements": credential_replacements,
                        "fieldMappingFixes": mapping_fixes,
                        "runtimeTokens": runtime_tokens,
                        "samplePayloadKeys": sorted(sample_payload.keys()),
                        "moduleConfidence": module_confidence,
                        "liveCompatibility": live_probe_result,
                        "profileNotes": profile_notes,
                        "catalogAgeDays": round(catalog_age_days, 2) if catalog_age_days is not None else None,
                        "timings": stage_timings if timings else None,
                        "totalSeconds": total_seconds,
                        "warnings": warnings,
                    },
                    meta={"command": "scenario deploy", "dryRun": True, "profile": resolved_profile},
                )
                return
            console.print("[green]Dry-run passed.[/green]")
            console.print(f"[dim]Profile: {resolved_profile}[/dim]")
            console.print(f"[dim]User: {user.get('email', 'unknown')}[/dim]")
            console.print(f"[dim]Team ID: {resolved_team_id}[/dim]")
            console.print(f"[dim]Scenario name: {scenario_name}[/dim]")
            if resolved_folder_id is not None:
                console.print(f"[dim]Folder ID: {resolved_folder_id}[/dim]")
            console.print(f"[dim]Schedule: {schedule_type}[/dim]")
            if mapping_fixes:
                console.print(f"[dim]Field mapping fixes: {len(mapping_fixes)}[/dim]")
            if credential_replacements:
                console.print(f"[dim]Credential replacements: {credential_replacements}[/dim]")
            for note in profile_notes:
                console.print(f"[dim]{note}[/dim]")
            if timings:
                console.print(f"[dim]Timings (s): {stage_timings} | total={total_seconds}[/dim]")
            return

        try:
            t_create = time.perf_counter()
            result = client.create_scenario(
                team_id=resolved_team_id,
                blueprint=blueprint,
                scheduling=scheduling,
                name=scenario_name,
                folder_id=resolved_folder_id,
            )
            stage_timings["createScenario"] = round(time.perf_counter() - t_create, 3)
            created = result.get("scenario", result)
            created_id = int(created.get("id"))

            t_lifecycle = time.perf_counter()
            if not inactive:
                client.start_scenario(created_id)
            if inactive:
                client.stop_scenario(created_id)
            stage_timings["lifecycle"] = round(time.perf_counter() - t_lifecycle, 3)

            verify_result: dict[str, object] = {
                "attempted": bool(effective_verify_run and not inactive),
                "status": None,
                "statusText": None,
                "executionId": None,
                "error": None,
            }

            if effective_verify_run and not inactive:
                t_verify = time.perf_counter()
                try:
                    run_result = client.run_scenario(created_id, data=sample_payload, responsive=True)
                    verify_result["executionId"] = run_result.get("executionId")
                    verify_status = run_result.get("status")
                    verify_result["status"] = verify_status
                    if str(verify_status) == "1":
                        verify_result["statusText"] = "success"
                    elif str(verify_status) == "2":
                        verify_result["statusText"] = "warning"
                    elif str(verify_status) == "3":
                        verify_result["statusText"] = "error"
                    else:
                        verify_result["statusText"] = str(verify_status)
                except APIError as verify_exc:
                    verify_result["error"] = str(verify_exc)
                stage_timings["verifyRun"] = round(time.perf_counter() - t_verify, 3)

            if effective_verify_run and not inactive and (verify_result.get("statusText") == "error" or verify_result.get("error")):
                client.stop_scenario(created_id)
                inactive = True

            total_seconds = round(sum(stage_timings.values()), 3)
            if json_output:
                emit_json(
                    data={
                        "dryRun": False,
                        "profile": resolved_profile,
                        "guardCompat": effective_guard_compat,
                        "verifyRun": effective_verify_run,
                        "scanLimit": effective_scan_limit,
                        "id": created_id,
                        "name": scenario_name,
                        "teamId": resolved_team_id,
                        "folderId": resolved_folder_id,
                        "active": not inactive,
                        "scheduleType": schedule_type,
                        "requiredConnectionApps": required_apps,
                        "autoWiredConnections": wired_count,
                        "credentialReplacements": credential_replacements,
                        "fieldMappingFixes": mapping_fixes,
                        "runtimeTokens": runtime_tokens,
                        "samplePayloadKeys": sorted(sample_payload.keys()),
                        "moduleConfidence": module_confidence,
                        "liveCompatibility": live_probe_result,
                        "profileNotes": profile_notes,
                        "catalogAgeDays": round(catalog_age_days, 2) if catalog_age_days is not None else None,
                        "timings": stage_timings if timings else None,
                        "totalSeconds": total_seconds,
                        "verification": verify_result,
                        "warnings": warnings,
                    },
                    meta={"command": "scenario deploy", "dryRun": False, "profile": resolved_profile},
                )
                if verify_result.get("statusText") == "error" or verify_result.get("error"):
                    raise SystemExit(1)
                return

            console.print(f"[green]Scenario deployed: {scenario_name} ({created_id})[/green]")
            if resolved_folder_id is not None:
                console.print(f"[dim]Folder ID: {resolved_folder_id}[/dim]")
            console.print(f"[dim]Profile: {resolved_profile}[/dim]")
            for note in profile_notes:
                console.print(f"[dim]{note}[/dim]")

            if verify_result.get("attempted"):
                if verify_result.get("error"):
                    console.print(f"[red]Verification run failed:[/red] {verify_result['error']}")
                else:
                    console.print(f"[bold]Verification status:[/bold] {verify_result.get('statusText', 'unknown')}")

            if inactive:
                console.print(f"[yellow]Scenario {created_id} set to inactive.[/yellow]")

            if timings:
                console.print(f"[dim]Timings (s): {stage_timings} | total={total_seconds}[/dim]")

            if verify_result.get("statusText") == "error" or verify_result.get("error"):
                raise SystemExit(1)
        except APIError as exc:
            if json_output:
                emit_json(ok=False, error=f"Deploy failed: {exc}", meta={"command": "scenario deploy"})
                raise SystemExit(1)
            console.print(f"[red]Deploy failed: {exc}[/red]")
            raise SystemExit(1)
