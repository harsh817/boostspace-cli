"""Timesheet automation commands.

This implements the month-end workflow described in the user story:

- Copy one Google Sheet template per lead
- Share only to that lead (+ manager) with notification email
- Track status in a control spreadsheet
- Support template versioning by swapping the template file id

Slack is intentionally not used.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from .console import console
from .jsonio import emit_json
from .gws import (
    GwsCliError,
    drive_copy_file,
    drive_create_permission,
    sheets_batch_update,
    sheets_create_spreadsheet,
    sheets_values_get,
    sheets_values_append,
    sheets_values_update,
)


DEFAULT_CONFIG_PATH = Path.home() / ".boostspace-cli" / "timesheets.json"


@dataclass(frozen=True)
class TimesheetLead:
    name: str
    email: str


def _utc_now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()


def _is_last_day(day: _dt.date) -> bool:
    return (day + _dt.timedelta(days=1)).month != day.month


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise click.ClickException(f"Config not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON config: {path} ({exc})")


def _save_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_leads_csv(csv_path: Path) -> list[TimesheetLead]:
    raw = csv_path.read_text(encoding="utf-8").splitlines()
    leads: list[TimesheetLead] = []
    for line in raw:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            raise click.ClickException(f"Bad lead row (expected name,email): {line}")
        leads.append(TimesheetLead(name=parts[0], email=parts[1]))
    if not leads:
        raise click.ClickException("No leads found in CSV.")
    return leads


def _provision_for_month(*, month: str, cfg: dict[str, Any], template_file_id: str | None, notify: bool) -> tuple[str, list[dict[str, str]]]:
    tmpl = template_file_id or cfg.get("template_file_id")
    parent_folder_id = cfg.get("parent_folder_id")
    manager_email = cfg.get("manager_email")
    control_sheet_id = cfg.get("control_spreadsheet_id")

    missing = [k for k in ["template_file_id", "parent_folder_id", "manager_email", "control_spreadsheet_id"] if not cfg.get(k) and not (k == "template_file_id" and tmpl)]
    if missing:
        raise click.ClickException(f"Missing config keys: {', '.join(missing)}")
    if not isinstance(tmpl, str) or not tmpl:
        raise click.ClickException("template_file_id is required")
    if not isinstance(parent_folder_id, str) or not parent_folder_id:
        raise click.ClickException("parent_folder_id is required")
    if not isinstance(manager_email, str) or not manager_email:
        raise click.ClickException("manager_email is required")
    if not isinstance(control_sheet_id, str) or not control_sheet_id:
        raise click.ClickException("control_spreadsheet_id is required")

    lead_values = sheets_values_get(spreadsheet_id=control_sheet_id, range_a1="lead_registry!A2:B")
    rows = lead_values.get("values", []) if isinstance(lead_values, dict) else []
    leads: list[TimesheetLead] = []
    for r in rows:
        if not isinstance(r, list) or len(r) < 2:
            continue
        name = str(r[0]).strip()
        email = str(r[1]).strip()
        if name and email:
            leads.append(TimesheetLead(name=name, email=email))
    if not leads:
        raise click.ClickException("No leads found in lead_registry tab.")

    created: list[dict[str, str]] = []
    created_at = _utc_now_iso()
    for lead in leads:
        sheet_name = f"Timesheet {month} - {lead.name}"
        copied = drive_copy_file(file_id=tmpl, name=sheet_name, parent_folder_id=parent_folder_id)
        file_id = str(copied.get("id", ""))
        web = str(copied.get("webViewLink", ""))
        if not file_id:
            raise click.ClickException("Drive copy did not return file id.")

        msg = f"Please fill and submit your timesheet for {month}."
        drive_create_permission(file_id=file_id, email=lead.email, role="writer", notify=notify, email_message=msg)
        drive_create_permission(file_id=file_id, email=manager_email, role="writer", notify=False)

        sheets_values_append(
            spreadsheet_id=control_sheet_id,
            range_a1="tracker!A2:G",
            values=[[month, lead.email, lead.name, file_id, web, "sent", created_at]],
        )

        created.append({"lead": lead.email, "fileId": file_id, "url": web})

    return control_sheet_id, created


@click.group("timesheets")
def timesheets():
    """Automate monthly lead timesheets using Google Workspace."""


@timesheets.command("init")
@click.option("--template-file-id", required=True, help="Google Drive file id of the template spreadsheet")
@click.option("--parent-folder-id", required=True, help="Google Drive folder id where month folders will be created")
@click.option("--manager-email", required=True, help="Manager email to grant access on every copied sheet")
@click.option("--leads-csv", type=click.Path(exists=True, path_type=Path), help="Optional CSV lines: name,email")
@click.option("--control-title", default="Timesheet Control", show_default=True)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def init_timesheets(template_file_id: str, parent_folder_id: str, manager_email: str, leads_csv: Path | None, control_title: str, config_path: Path, json_output: bool):
    """Create the control spreadsheet and a local config file."""
    leads = _parse_leads_csv(leads_csv) if leads_csv else []

    try:
        control = sheets_create_spreadsheet(title=control_title)
        control_sheet_id = control.get("spreadsheetId") or control.get("spreadsheetId", None)
        if not isinstance(control_sheet_id, str) or not control_sheet_id:
            # gws returns full spreadsheet object; spreadsheetId is top-level
            control_sheet_id = control.get("spreadsheetId")
        if not isinstance(control_sheet_id, str) or not control_sheet_id:
            raise click.ClickException("Could not read spreadsheetId from Sheets create response.")

        # Rename default Sheet1 -> lead_registry and add tracker + template_versions.
        sheets_batch_update(
            spreadsheet_id=control_sheet_id,
            requests=[
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": 0, "title": "lead_registry"},
                        "fields": "title",
                    }
                },
                {"addSheet": {"properties": {"title": "tracker"}}},
                {"addSheet": {"properties": {"title": "template_versions"}}},
            ],
        )

        sheets_values_update(
            spreadsheet_id=control_sheet_id,
            range_a1="lead_registry!A1:B1",
            values=[["lead_name", "lead_email"]],
        )
        if leads:
            sheets_values_append(
                spreadsheet_id=control_sheet_id,
                range_a1="lead_registry!A2:B",
                values=[[l.name, l.email] for l in leads],
            )

        sheets_values_update(
            spreadsheet_id=control_sheet_id,
            range_a1="tracker!A1:G1",
            values=[["month", "lead_email", "lead_name", "sheet_file_id", "sheet_url", "status", "created_at"]],
        )

        sheets_values_update(
            spreadsheet_id=control_sheet_id,
            range_a1="template_versions!A1:C1",
            values=[["template_version", "template_file_id", "active_from_month"]],
        )
        sheets_values_append(
            spreadsheet_id=control_sheet_id,
            range_a1="template_versions!A2:C",
            values=[["v1", template_file_id, ""]],
        )
    except GwsCliError as exc:
        raise click.ClickException(f"Google Workspace CLI error: {exc.result.stderr.strip() or str(exc)}")

    cfg = {
        "template_file_id": template_file_id,
        "parent_folder_id": parent_folder_id,
        "manager_email": manager_email,
        "control_spreadsheet_id": control_sheet_id,
    }
    _save_config(config_path, cfg)

    if json_output:
        emit_json(data={"config": cfg, "configPath": str(config_path)}, meta={"command": "timesheets init"})
        return

    console.print(f"[green]Created control sheet:[/green] {control_sheet_id}")
    console.print(f"[green]Wrote config:[/green] {config_path}")


@timesheets.command("provision")
@click.option("--month", required=True, help="Billing month in YYYY-MM format")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--template-file-id", help="Override template file id (for template changes)")
@click.option("--notify/--no-notify", default=True, show_default=True, help="Send Drive notification emails when sharing")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def provision_timesheets(month: str, config_path: Path, template_file_id: str | None, notify: bool, json_output: bool):
    """Copy the template per lead, share it, and register rows in tracker."""
    cfg = _load_config(config_path)
    try:
        control_sheet_id, created = _provision_for_month(month=month, cfg=cfg, template_file_id=template_file_id, notify=notify)
    except GwsCliError as exc:
        raise click.ClickException(f"Google Workspace CLI error: {exc.result.stderr.strip() or str(exc)}")

    if json_output:
        emit_json(
            data={
                "month": month,
                "count": len(created),
                "created": created,
                "controlSpreadsheetId": control_sheet_id,
            },
            meta={"command": "timesheets provision"},
        )
        return

    console.print(f"[green]Provisioned {len(created)} sheets for {month}[/green]")
    for item in created:
        console.print(f"- {item['lead']}: {item.get('url') or item['fileId']}")


@timesheets.command("auto")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--date", "date_override", help="Override date YYYY-MM-DD for testing")
@click.option("--template-file-id", help="Override template file id")
@click.option("--notify/--no-notify", default=True, show_default=True)
@click.option("--force", is_flag=True, help="Run even if not last day")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def auto_timesheets(config_path: Path, date_override: str | None, template_file_id: str | None, notify: bool, force: bool, json_output: bool):
    """Daily-safe command: provisions only on last day of month."""
    if date_override:
        try:
            today = _dt.datetime.strptime(date_override, "%Y-%m-%d").date()
        except ValueError as exc:
            raise click.ClickException(f"Invalid --date value: {exc}")
    else:
        today = _dt.date.today()

    if not force and not _is_last_day(today):
        payload = {"ran": False, "reason": "not_last_day", "date": today.isoformat()}
        if json_output:
            emit_json(data=payload, meta={"command": "timesheets auto"})
            return
        console.print(f"[yellow]Skipped:[/yellow] {today.isoformat()} is not month-end.")
        return

    month = f"{today.year:04d}-{today.month:02d}"
    cfg = _load_config(config_path)
    try:
        control_sheet_id, created = _provision_for_month(month=month, cfg=cfg, template_file_id=template_file_id, notify=notify)
    except GwsCliError as exc:
        raise click.ClickException(f"Google Workspace CLI error: {exc.result.stderr.strip() or str(exc)}")

    payload = {
        "ran": True,
        "month": month,
        "date": today.isoformat(),
        "count": len(created),
        "created": created,
        "controlSpreadsheetId": control_sheet_id,
    }
    if json_output:
        emit_json(data=payload, meta={"command": "timesheets auto"})
        return
    console.print(f"[green]Auto run completed for {month}[/green] ({len(created)} sheets)")


@timesheets.command("install-schedule")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH, show_default=True)
@click.option("--task-name", default="BoostTimesheetsMonthEnd", show_default=True)
@click.option("--time", "start_time", default="18:00", show_default=True, help="HH:MM 24h")
@click.option("--python", "python_exe", default=sys.executable, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def install_schedule(config_path: Path, task_name: str, start_time: str, python_exe: str, json_output: bool):
    """Install a Windows Scheduled Task that runs `timesheets auto` daily."""
    if os.name != "nt":
        raise click.ClickException("install-schedule is currently supported only on Windows.")

    if len(start_time) != 5 or start_time[2] != ":":
        raise click.ClickException("--time must be HH:MM")

    command = f'"{python_exe}" -m boostspace_cli.cli timesheets auto --config "{config_path}" --json'
    schtasks_cmd = [
        "schtasks",
        "/Create",
        "/F",
        "/SC",
        "DAILY",
        "/TN",
        task_name,
        "/TR",
        command,
        "/ST",
        start_time,
    ]

    proc = subprocess.run(schtasks_cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise click.ClickException(f"Failed to create scheduled task: {proc.stderr.strip() or proc.stdout.strip()}")

    payload = {
        "installed": True,
        "taskName": task_name,
        "time": start_time,
        "command": command,
    }
    if json_output:
        emit_json(data=payload, meta={"command": "timesheets install-schedule"})
        return
    console.print(f"[green]Installed scheduled task:[/green] {task_name} at {start_time}")
