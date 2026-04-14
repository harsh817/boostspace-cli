"""Thin wrapper for Google Workspace CLI (`gws`).

This project already automates Boost.space Integrator. For spreadsheet-heavy
workflows, the Google Workspace CLI is the most reliable way to create/copy
files and apply permissions without depending on tenant-specific native modules.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .executables import resolve_executable


@dataclass(frozen=True)
class GwsResult:
    stdout: str
    stderr: str
    returncode: int


class GwsCliError(RuntimeError):
    def __init__(self, message: str, *, result: GwsResult, command: list[str]):
        super().__init__(message)
        self.result = result
        self.command = command


def _run(command: list[str]) -> GwsResult:
    proc = subprocess.run(command, capture_output=True, text=True, check=False, env=_gws_env())
    return GwsResult(stdout=proc.stdout or "", stderr=proc.stderr or "", returncode=int(proc.returncode))


def _find_gws_bin() -> str:
    appdata = os.getenv("APPDATA", "").strip()
    windows_candidates: list[str] = []
    if appdata:
        windows_candidates.append(str(Path(appdata) / "npm" / "gws.cmd"))

    return resolve_executable("gws", env_var="GWS_BIN", windows_candidates=windows_candidates) or "gws"


def _gcloud_access_token() -> str:
    localapp = os.getenv("LOCALAPPDATA", "").strip()
    windows_candidates: list[str] = []
    if localapp:
        windows_candidates.append(str(Path(localapp) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"))

    gcloud_bin = resolve_executable("gcloud", windows_candidates=windows_candidates)
    if not gcloud_bin:
        return ""

    proc = subprocess.run(
        [gcloud_bin, "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def _gws_env() -> dict[str, str]:
    env = os.environ.copy()
    token = env.get("GOOGLE_WORKSPACE_CLI_TOKEN", "").strip()
    if token:
        return env

    token = _gcloud_access_token()
    if token:
        env["GOOGLE_WORKSPACE_CLI_TOKEN"] = token
    return env


def run_gws(*args: str, params: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> Any:
    cmd: list[str] = [_find_gws_bin(), *args]
    if params is not None:
        cmd.extend(["--params", json.dumps(params, separators=(",", ":"))])
    if body is not None:
        cmd.extend(["--json", json.dumps(body, separators=(",", ":"))])
    cmd.extend(["--format", "json"])

    result = _run(cmd)
    if result.returncode != 0:
        raise GwsCliError(
            f"gws failed (exit {result.returncode}).",
            result=result,
            command=cmd,
        )

    out = result.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise GwsCliError(
            f"gws returned non-JSON output: {exc}",
            result=result,
            command=cmd,
        )


def drive_copy_file(*, file_id: str, name: str, parent_folder_id: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "fileId": file_id,
        "fields": "id,name,webViewLink,parents",
        "supportsAllDrives": True,
    }
    body: dict[str, Any] = {"name": name}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    return run_gws("drive", "files", "copy", params=params, body=body)


def drive_create_permission(
    *,
    file_id: str,
    email: str,
    role: str = "writer",
    notify: bool = True,
    email_message: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "fileId": file_id,
        "supportsAllDrives": True,
        "sendNotificationEmail": bool(notify),
    }
    if email_message:
        params["emailMessage"] = email_message

    body: dict[str, Any] = {
        "type": "user",
        "role": role,
        "emailAddress": email,
    }
    return run_gws("drive", "permissions", "create", params=params, body=body)


def sheets_create_spreadsheet(*, title: str) -> dict[str, Any]:
    body = {"properties": {"title": title}}
    return run_gws("sheets", "spreadsheets", "create", body=body)


def sheets_batch_update(*, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    params = {"spreadsheetId": spreadsheet_id}
    body = {"requests": requests}
    return run_gws("sheets", "spreadsheets", "batchUpdate", params=params, body=body)


def sheets_values_update(
    *,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
) -> dict[str, Any]:
    params = {
        "spreadsheetId": spreadsheet_id,
        "range": range_a1,
        "valueInputOption": value_input_option,
    }
    body = {"values": values}
    return run_gws("sheets", "spreadsheets", "values", "update", params=params, body=body)


def sheets_values_append(
    *,
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[Any]],
    value_input_option: str = "USER_ENTERED",
    insert_data_option: str = "INSERT_ROWS",
) -> dict[str, Any]:
    params = {
        "spreadsheetId": spreadsheet_id,
        "range": range_a1,
        "valueInputOption": value_input_option,
        "insertDataOption": insert_data_option,
    }
    body = {"values": values}
    return run_gws("sheets", "spreadsheets", "values", "append", params=params, body=body)


def sheets_values_get(*, spreadsheet_id: str, range_a1: str) -> dict[str, Any]:
    params = {
        "spreadsheetId": spreadsheet_id,
        "range": range_a1,
    }
    return run_gws("sheets", "spreadsheets", "values", "get", params=params)
