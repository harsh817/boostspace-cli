"""CLI entry point for Boost.space CLI."""

import click
from .config import Config
from .console import console
from .jsonio import emit_json


@click.group()
@click.pass_context
def main(ctx):
    """Boost.space CLI — manage workflows from the terminal."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config()


@main.command()
@click.option("--backend", type=click.Choice(["make", "boostspace"]), help="API backend to use")
@click.option("--zone", help="Make zone URL (e.g. eu1.make.com)")
@click.option("--org-id", type=int, help="Default organization ID")
@click.option("--team-id", type=int, help="Default team ID")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def configure(ctx, backend, zone, org_id, team_id, json_output):
    """Configure defaults (backend, zone, organization, team)."""
    config: Config = ctx.obj["config"]
    if backend:
        config.backend = backend
        if not json_output:
            console.print(f"[green]Backend set to: {backend}[/green]")
    if zone:
        config.zone_url = f"https://{zone}" if not zone.startswith("http") else zone
        if not json_output:
            console.print(f"[green]Zone URL set to: {config.zone_url}[/green]")
    if org_id:
        config.organization_id = org_id
        if not json_output:
            console.print(f"[green]Organization ID set to: {org_id}[/green]")
    if team_id:
        config.team_id = team_id
        if not json_output:
            console.print(f"[green]Team ID set to: {team_id}[/green]")

    if json_output:
        emit_json(
            data={
                "backend": config.backend,
                "zoneUrl": config.zone_url,
                "organizationId": config.organization_id,
                "teamId": config.team_id,
            },
            meta={"command": "configure"},
        )
        return

    if not any([backend, zone, org_id, team_id]):
        console.print(f"[dim]Config file: {config._path}[/dim]")
        console.print(f"[dim]Backend: {config.backend}[/dim]")
        console.print(f"[dim]Zone URL: {config.zone_url}[/dim]")
        console.print(f"[dim]Organization ID: {config.organization_id or 'not set'}[/dim]")
        console.print(f"[dim]Team ID: {config.team_id or 'not set'}[/dim]")


@main.command("init")
@click.option("--backend", type=click.Choice(["make", "boostspace"]), default="boostspace", show_default=True)
@click.option("--organization-id", type=int, help="Preferred organization ID")
@click.option("--team-id", type=int, help="Preferred team ID")
@click.option("--timeout", type=int, default=600, show_default=True, help="Playwright login timeout in seconds")
@click.option("--headless", is_flag=True, default=False, help="Run Playwright browser headless")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def init_cli(ctx, backend, organization_id, team_id, timeout, headless, json_output):
    """One-command onboarding: login, detect org/team, validate access."""
    from .auth import perform_playwright_login
    from .client import APIClient, APIError

    config: Config = ctx.obj["config"]
    config.backend = backend
    if not json_output:
        console.print(f"[green]Backend set to: {backend}[/green]")

    user = perform_playwright_login(config, timeout=timeout, headless=headless, quiet=json_output)
    if not user:
        if json_output:
            emit_json(ok=False, error="Authentication failed.", meta={"command": "init"})
        raise SystemExit(1)

    if not json_output:
        console.print(f"[green]Authenticated as {user.get('email', 'unknown')}[/green]")

    with APIClient(config) as client:
        try:
            organizations = client.get("/organizations").get("organizations", [])
        except APIError as err:
            if json_output:
                emit_json(ok=False, error=f"Organization lookup failed ({err.status_code})", meta={"command": "init"})
                raise SystemExit(1)
            console.print(f"[red]Organization lookup failed: {err.status_code}[/red]")
            raise SystemExit(1)

        if not organizations:
            if json_output:
                emit_json(ok=False, error="No organizations available for this account.", meta={"command": "init"})
                raise SystemExit(1)
            console.print("[red]No organizations available for this account.[/red]")
            raise SystemExit(1)

        org_ids = {org["id"] for org in organizations}
        selected_org = organization_id if organization_id in org_ids else organizations[0]["id"]
        if organization_id and organization_id not in org_ids:
            if not json_output:
                console.print(f"[yellow]Requested organization {organization_id} not found; using {selected_org}.[/yellow]")

        try:
            teams = client.list_teams(organization_id=selected_org).get("teams", [])
        except APIError as err:
            if json_output:
                emit_json(ok=False, error=f"Team lookup failed ({err.status_code})", meta={"command": "init"})
                raise SystemExit(1)
            console.print(f"[red]Team lookup failed: {err.status_code}[/red]")
            raise SystemExit(1)

        if not teams:
            if json_output:
                emit_json(ok=False, error="No teams available in selected organization.", meta={"command": "init"})
                raise SystemExit(1)
            console.print("[red]No teams available in selected organization.[/red]")
            raise SystemExit(1)

        team_ids = {team["id"] for team in teams}
        selected_team = team_id if team_id in team_ids else teams[0]["id"]
        if team_id and team_id not in team_ids:
            if not json_output:
                console.print(f"[yellow]Requested team {team_id} not found; using {selected_team}.[/yellow]")

        try:
            client.list_scenarios(team_id=selected_team, limit=1)
        except APIError as err:
            if json_output:
                emit_json(ok=False, error=f"Scenario access validation failed ({err.status_code})", meta={"command": "init"})
                raise SystemExit(1)
            console.print(f"[red]Scenario access validation failed: {err.status_code}[/red]")
            raise SystemExit(1)

    config.organization_id = selected_org
    config.team_id = selected_team

    if json_output:
        emit_json(
            data={
                "backend": backend,
                "organizationId": selected_org,
                "teamId": selected_team,
                "user": {
                    "name": user.get("name"),
                    "email": user.get("email"),
                },
                "initialized": True,
            },
            meta={"command": "init"},
        )
        return

    console.print("[green]Initialization complete.[/green]")
    console.print(f"[dim]Organization ID: {selected_org}[/dim]")
    console.print(f"[dim]Team ID: {selected_team}[/dim]")
    console.print("[dim]Next: run `boost scenarios list`[/dim]")


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def whoami(ctx, json_output):
    """Show current user info."""
    from .client import APIClient
    config: Config = ctx.obj["config"]
    with APIClient(config) as client:
        user = client.get_user()
        user_data = user.get("user") or user.get("authUser") or user
        if json_output:
            emit_json(
                data={
                    "name": user_data.get("name", "unknown"),
                    "email": user_data.get("email", "unknown"),
                },
                meta={"command": "whoami"},
            )
            return
        console.print(f"[bold]User:[/bold] {user_data.get('name', 'unknown')}")
        console.print(f"[bold]Email:[/bold] {user_data.get('email', 'unknown')}")


# Import subcommands
from . import scenarios  # noqa: E402
from . import executions  # noqa: E402
from . import webhooks  # noqa: E402
from . import blueprints  # noqa: E402
from . import auth  # noqa: E402
from . import scenario_builder  # noqa: E402

main.add_command(scenarios.scenarios)
main.add_command(executions.executions)
main.add_command(webhooks.webhooks)
main.add_command(blueprints.blueprints)
main.add_command(auth.auth)
main.add_command(scenario_builder.scenario_builder)


if __name__ == "__main__":
    main()
