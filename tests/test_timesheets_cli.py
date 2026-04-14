import json
from pathlib import Path

from click.testing import CliRunner


def test_timesheets_init_writes_config(tmp_path, monkeypatch):
    from boostspace_cli.timesheets_cli import timesheets

    created = {"spreadsheetId": "sheet-123"}

    def fake_create(title: str):
        assert title
        return created

    def fake_batch_update(*, spreadsheet_id: str, requests):
        assert spreadsheet_id == "sheet-123"
        assert isinstance(requests, list) and requests
        return {"ok": True}

    def fake_update(*, spreadsheet_id: str, range_a1: str, values, value_input_option="USER_ENTERED"):
        assert spreadsheet_id == "sheet-123"
        assert range_a1
        assert isinstance(values, list)
        return {"ok": True}

    def fake_append(*, spreadsheet_id: str, range_a1: str, values, value_input_option="USER_ENTERED", insert_data_option="INSERT_ROWS"):
        assert spreadsheet_id == "sheet-123"
        assert range_a1
        assert isinstance(values, list)
        return {"ok": True}

    monkeypatch.setattr("boostspace_cli.timesheets_cli.sheets_create_spreadsheet", lambda title: fake_create(title))
    monkeypatch.setattr("boostspace_cli.timesheets_cli.sheets_batch_update", fake_batch_update)
    monkeypatch.setattr("boostspace_cli.timesheets_cli.sheets_values_update", fake_update)
    monkeypatch.setattr("boostspace_cli.timesheets_cli.sheets_values_append", fake_append)

    leads_csv = tmp_path / "leads.csv"
    leads_csv.write_text("Lead A,lead.a@example.com\nLead B,lead.b@example.com\n", encoding="utf-8")

    cfg_path = tmp_path / "timesheets.json"
    runner = CliRunner()
    result = runner.invoke(
        timesheets,
        [
            "init",
            "--template-file-id",
            "tmpl-1",
            "--parent-folder-id",
            "folder-1",
            "--manager-email",
            "mgr@example.com",
            "--leads-csv",
            str(leads_csv),
            "--config",
            str(cfg_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert Path(payload["data"]["configPath"]) == cfg_path
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert cfg["control_spreadsheet_id"] == "sheet-123"
    assert cfg["template_file_id"] == "tmpl-1"


def test_timesheets_provision_appends_tracker_rows(tmp_path, monkeypatch):
    from boostspace_cli.timesheets_cli import timesheets

    cfg_path = tmp_path / "timesheets.json"
    cfg_path.write_text(
        json.dumps(
            {
                "template_file_id": "tmpl-1",
                "parent_folder_id": "folder-1",
                "manager_email": "mgr@example.com",
                "control_spreadsheet_id": "sheet-123",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "boostspace_cli.timesheets_cli.sheets_values_get",
        lambda *, spreadsheet_id, range_a1: {"values": [["Lead A", "a@example.com"], ["Lead B", "b@example.com"]]},
    )

    copies = []

    def fake_copy(*, file_id: str, name: str, parent_folder_id: str | None = None):
        copies.append((file_id, name, parent_folder_id))
        idx = len(copies)
        return {"id": f"file-{idx}", "webViewLink": f"https://drive/{idx}"}

    monkeypatch.setattr("boostspace_cli.timesheets_cli.drive_copy_file", fake_copy)
    monkeypatch.setattr("boostspace_cli.timesheets_cli.drive_create_permission", lambda **kwargs: {"ok": True})

    appended = []

    def fake_append(*, spreadsheet_id: str, range_a1: str, values, **kwargs):
        appended.append((spreadsheet_id, range_a1, values))
        return {"ok": True}

    monkeypatch.setattr("boostspace_cli.timesheets_cli.sheets_values_append", fake_append)

    runner = CliRunner()
    result = runner.invoke(
        timesheets,
        [
            "provision",
            "--month",
            "2026-04",
            "--config",
            str(cfg_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["count"] == 2
    assert len(appended) == 2
    assert appended[0][0] == "sheet-123"
    assert appended[0][1].startswith("tracker!")
