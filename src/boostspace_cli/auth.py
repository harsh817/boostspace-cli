"""OAuth authentication commands for Boost.space Integrator."""

import time
from typing import Any, NoReturn, Optional
from urllib.parse import parse_qs, urlparse

import click
import httpx

from .client import APIClient, APIError
from .console import console
from .jsonio import emit_json


def _extract_code_and_redirect(code_or_url: str, fallback_redirect_uri: str) -> tuple[str, str]:
    code = code_or_url
    redirect_uri = fallback_redirect_uri

    if "code=" in code_or_url:
        parsed = urlparse(code_or_url)
        params = parse_qs(parsed.query)
        code = params.get("code", [""])[0]
        redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return code, redirect_uri


def exchange_code(
    token_url: str,
    code: str,
    redirect_uri: str,
    client_id: str = "1",
    cookies: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as http:
        response = http.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            },
            cookies=cookies,
        )
        if response.status_code != 200:
            raise click.ClickException(f"Token exchange failed ({response.status_code}): {response.text}")
        return response.json()


def refresh_token(token_url: str, refresh_token_value: str, client_id: str = "1") -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as http:
        response = http.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_value,
                "client_id": client_id,
            },
        )
        if response.status_code != 200:
            raise click.ClickException(f"Token refresh failed ({response.status_code}): {response.text}")
        return response.json()


def _save_tokens(config: Any, token_data: dict[str, Any]) -> None:
    config.oauth_token = token_data["access_token"]
    config.oauth_refresh_token = token_data.get("refresh_token", "")
    config.oauth_token_expires_at = time.time() + token_data.get("expires_in", 3600)


@click.group()
def auth() -> None:
    """Manage authentication and diagnostics."""


def perform_playwright_login(
    config: Any,
    timeout: int = 600,
    headless: bool = False,
    quiet: bool = False,
) -> Optional[dict[str, Any]]:
    """Log in via Playwright and persist session cookies."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if not quiet:
            console.print("[red]Playwright is not installed. Run: pip install playwright[/red]")
        return None

    start_url = "https://integrator.boost.space/organization/14109/dashboard"
    if not quiet:
        console.print("[bold blue]Opening browser with Playwright...[/bold blue]")
        console.print("[dim]Log in normally; the CLI will capture your session automatically.[/dim]")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")

        seen_code = False

        def mark_code(req: Any) -> None:
            nonlocal seen_code
            if "integrator.boost.space/sso/oauth?code=" in req.url:
                seen_code = True

        context.on("request", mark_code)

        end_at = time.time() + timeout
        reached_dashboard = False
        while time.time() < end_at:
            current_url = page.url
            if "integrator.boost.space/sso/oauth?code=" in current_url:
                seen_code = True
            if seen_code and "/organization/" in current_url and "/dashboard" in current_url:
                reached_dashboard = True
                break
            page.wait_for_timeout(500)

        if not reached_dashboard:
            browser.close()
            if not quiet:
                console.print("[red]Login timeout. Dashboard was not reached.[/red]")
            return None

        me_resp = None
        for _ in range(60):
            me_resp = context.request.get("https://integrator.boost.space/api/v2/users/me")
            if me_resp.status == 200:
                break
            page.wait_for_timeout(500)

        if me_resp is None or me_resp.status != 200:
            status_code = me_resp.status if me_resp else 0
            browser.close()
            if not quiet:
                console.print(f"[red]Logged in UI, but API check failed: {status_code}[/red]")
            return None

        me_data = me_resp.json()
        auth_user = me_data.get("authUser", {})

        cookies_raw = context.cookies()
        cookies_to_save = []
        for cookie in cookies_raw:
            cookies_to_save.append(
                {
                    "name": cookie.get("name", ""),
                    "value": cookie.get("value", ""),
                    "domain": cookie.get("domain", ""),
                    "path": cookie.get("path", "/"),
                }
            )

        browser.close()

    config.save_cookies(cookies_to_save)
    return auth_user


@auth.command("playwright")
@click.option("--timeout", type=int, default=600, show_default=True, help="Wait time in seconds")
@click.option("--headless", is_flag=True, default=False, help="Run browser headless")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def login_playwright(ctx: click.Context, timeout: int, headless: bool, json_output: bool) -> None:
    """Authenticate by saving browser session cookies via Playwright."""
    config = ctx.obj["config"]
    user = perform_playwright_login(config, timeout=timeout, headless=headless, quiet=json_output)
    if not user:
        if json_output:
            emit_json(ok=False, error="Authentication failed.", meta={"command": "auth playwright"})
        raise SystemExit(1)

    if json_output:
        emit_json(
            data={
                "authenticated": True,
                "name": user.get("name", "unknown"),
                "email": user.get("email", "unknown"),
            },
            meta={"command": "auth playwright"},
        )
        return

    console.print("[green]Session authentication successful via Playwright![/green]")
    console.print(f"[dim]Authenticated as: {user.get('name', 'unknown')} ({user.get('email', 'unknown')})[/dim]")


@auth.command("doctor")
@click.option("--fix", is_flag=True, help="Auto-save discovered organization/team defaults")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def doctor(ctx: click.Context, fix: bool, json_output: bool) -> None:
    """Run authentication and configuration diagnostics."""
    config = ctx.obj["config"]
    failed = False

    payload: dict[str, Any] = {
        "fix": bool(fix),
        "storage": "secure keyring" if config.secure_storage_enabled else "config file fallback",
        "authMaterial": False,
        "apiAuth": False,
        "organizationId": None,
        "teamId": None,
        "scenarioAccess": False,
        "warnings": [],
        "errors": [],
        "updated": [],
    }

    def report(message: str) -> None:
        if not json_output:
            console.print(message)

    def fail_with(code: int = 1) -> NoReturn:
        if json_output:
            errors = payload.get("errors") or []
            message = str(errors[0]) if errors else "Doctor checks failed."
            emit_json(ok=False, error=message, data=payload, meta={"command": "auth doctor"})
        raise SystemExit(code)

    report(f"Storage: {payload['storage']}")

    has_session = config.has_cookies() or bool(config.oauth_token)
    payload["authMaterial"] = bool(has_session)
    if not has_session:
        payload["errors"].append("Auth material missing")
        report("[red]Auth material: missing[/red]")
        report("[dim]Run: boost auth playwright[/dim]")
        fail_with(1)
    report("Auth material: present")

    if config.secure_storage_enabled:
        existing_cookies = config.load_cookies()
        if existing_cookies:
            config.save_cookies(existing_cookies)

    with APIClient(config) as client:
        try:
            me = client.get_user()
            user = me.get("authUser") or me.get("user") or me
            payload["apiAuth"] = True
            payload["user"] = {"email": user.get("email", "unknown")}
            report(f"API auth: ok ({user.get('email', 'unknown')})")
        except APIError as err:
            payload["errors"].append(f"API auth failed ({err.status_code})")
            report(f"[red]API auth: failed ({err.status_code})[/red]")
            report("[dim]Run: boost auth playwright[/dim]")
            fail_with(1)

        orgs: list[dict[str, Any]] = []
        try:
            orgs = client.get("/organizations").get("organizations", [])
        except APIError as err:
            payload["errors"].append(f"Organizations check failed ({err.status_code})")
            report(f"[red]Organizations check failed: {err.status_code}[/red]")
            fail_with(1)

        if not orgs:
            payload["errors"].append("No organizations available")
            report("[red]No organizations available.[/red]")
            fail_with(1)

        org_id = config.organization_id or orgs[0]["id"]
        org_ids = {org["id"] for org in orgs}
        if org_id not in org_ids:
            org_id = orgs[0]["id"]
            failed = True
            payload["warnings"].append(f"Configured organization not found; using {org_id}")
            report(f"[yellow]Configured organization not found. Using {org_id}.[/yellow]")

        if fix and config.organization_id != org_id:
            config.organization_id = org_id
            payload["updated"].append("organization_id")
            report(f"Saved organization_id: {org_id}")

        payload["organizationId"] = org_id

        teams: list[dict[str, Any]] = []
        try:
            teams = client.list_teams(organization_id=org_id).get("teams", [])
        except APIError as err:
            payload["errors"].append(f"Team lookup failed ({err.status_code})")
            report(f"[red]Team lookup failed: {err.status_code}[/red]")
            fail_with(1)

        if not teams:
            payload["errors"].append("No teams available in selected organization")
            report("[red]No teams available in this organization.[/red]")
            fail_with(1)

        team_id = config.team_id or teams[0]["id"]
        team_ids = {team["id"] for team in teams}
        if team_id not in team_ids:
            team_id = teams[0]["id"]
            failed = True
            payload["warnings"].append(f"Configured team not found; using {team_id}")
            report(f"[yellow]Configured team not found. Using {team_id}.[/yellow]")

        if fix and config.team_id != team_id:
            config.team_id = team_id
            payload["updated"].append("team_id")
            report(f"Saved team_id: {team_id}")

        payload["teamId"] = team_id

        try:
            client.list_scenarios(team_id=team_id, limit=1)
            payload["scenarioAccess"] = True
            report("Scenario access: ok")
        except APIError as err:
            payload["errors"].append(f"Scenario access failed ({err.status_code})")
            report(f"[red]Scenario access failed: {err.status_code}[/red]")
            failed = True

    payload_ok = not payload["errors"] and not (failed and not fix)

    if json_output:
        error_message = None
        errors = payload.get("errors") or []
        if errors:
            error_message = str(errors[0])
        elif failed and not fix:
            error_message = "Doctor completed with warnings. Run with --fix to auto-save defaults."
        emit_json(ok=payload_ok, error=error_message, data=payload, meta={"command": "auth doctor"})

    if failed and not fix:
        report("[yellow]Doctor completed with warnings. Run with --fix to auto-save defaults.[/yellow]")
        raise SystemExit(1)

    report("[green]Doctor checks passed.[/green]")


@auth.command("code")
@click.argument("code_or_url")
@click.option(
    "--redirect-uri",
    default="https://integrator.boost.space/sso/oauth",
    show_default=True,
    help="Fallback redirect URI when only raw code is passed",
)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def login_with_code(ctx: click.Context, code_or_url: str, redirect_uri: str, json_output: bool) -> None:
    """Authenticate using an OAuth code or callback URL directly."""
    config = ctx.obj["config"]
    code, resolved_redirect_uri = _extract_code_and_redirect(code_or_url, redirect_uri)

    if not code:
        if json_output:
            emit_json(ok=False, error="No OAuth code found in input.", meta={"command": "auth code"})
            return
        console.print("[red]No OAuth code found in input.[/red]")
        return

    if not json_output:
        console.print("[bold blue]Exchanging authorization code for tokens...[/bold blue]")

    try:
        token_data = exchange_code(config.token_url, code, resolved_redirect_uri, client_id=config.oauth_client_id or "1")
    except click.ClickException as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "auth code"})
            return
        console.print(f"[red]Error: {exc}[/red]")
        return

    _save_tokens(config, token_data)
    if json_output:
        emit_json(
            data={
                "authenticated": True,
                "expiresIn": token_data.get("expires_in"),
                "hasRefreshToken": bool(token_data.get("refresh_token")),
            },
            meta={"command": "auth code"},
        )
        return

    console.print("[green]Authentication successful![/green]")
    console.print(f"[dim]Token expires in: {token_data.get('expires_in', 'unknown')}s[/dim]")


@auth.command("refresh")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def refresh(ctx: click.Context, json_output: bool) -> None:
    """Manually refresh OAuth token."""
    config = ctx.obj["config"]
    if not config.oauth_refresh_token:
        if json_output:
            emit_json(ok=False, error="No refresh token.", meta={"command": "auth refresh"})
            return
        console.print("[red]No refresh token. Run 'boost auth playwright' first.[/red]")
        return

    try:
        token_data = refresh_token(config.token_url, config.oauth_refresh_token, client_id=config.oauth_client_id or "1")
    except click.ClickException as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "auth refresh"})
            return
        console.print(f"[red]Error: {exc}[/red]")
        return

    _save_tokens(config, token_data)
    if json_output:
        emit_json(
            data={
                "refreshed": True,
                "expiresIn": token_data.get("expires_in"),
                "hasRefreshToken": bool(token_data.get("refresh_token")),
            },
            meta={"command": "auth refresh"},
        )
        return

    console.print("[green]Token refreshed[/green]")


@auth.command("status")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def status(ctx: click.Context, json_output: bool) -> None:
    """Show authentication status."""
    config = ctx.obj["config"]
    remaining = None
    token_status = None
    if config.oauth_token_expires_at:
        remaining = int(config.oauth_token_expires_at - time.time())
        if remaining <= 0:
            token_status = "expired"

    if json_output:
        emit_json(
            data={
                "backend": config.backend,
                "secureStorage": bool(config.secure_storage_enabled),
                "sessionCookies": bool(config.has_cookies()),
                "accessToken": bool(config.oauth_token),
                "refreshToken": bool(config.oauth_refresh_token),
                "tokenExpiresIn": remaining,
                "tokenStatus": token_status,
            },
            meta={"command": "auth status"},
        )
        return

    console.print(f"Backend: {config.backend}")
    console.print(f"Secure storage: {'yes' if config.secure_storage_enabled else 'no'}")
    console.print(f"Session cookies: {'set' if config.has_cookies() else 'not set'}")
    console.print(f"Access token: {'set' if config.oauth_token else 'not set'}")
    console.print(f"Refresh token: {'set' if config.oauth_refresh_token else 'not set'}")

    if config.oauth_token_expires_at:
        token_remaining = config.oauth_token_expires_at - time.time()
        if token_remaining > 0:
            console.print(f"Token expires in: {int(token_remaining)}s ({int(token_remaining // 60)}m)")
        else:
            console.print("Token status: expired")


@auth.command("clear")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
@click.pass_context
def clear(ctx: click.Context, json_output: bool) -> None:
    """Clear saved authentication data."""
    config = ctx.obj["config"]
    config.oauth_token = ""
    config.oauth_refresh_token = ""
    config.oauth_token_expires_at = None
    config.clear_cookies()
    if json_output:
        emit_json(data={"cleared": True}, meta={"command": "auth clear"})
        return
    console.print("[yellow]Authentication data cleared[/yellow]")
