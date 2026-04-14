import json

from click.testing import CliRunner

from boostspace_cli.cli import main
import boostspace_cli.connections as connections_mod
import boostspace_cli.config as config_mod


def test_connections_compat_json_reports_compatible_and_incompatible(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_connections(self, team_id=None):
            _ = team_id
            return {
                "connections": [
                    {"id": 164145, "accountType": "oauth", "accountName": "google-restricted"},
                    {"id": 147240, "accountType": "oauth", "accountName": "google"},
                    {"id": 999, "accountType": "oauth", "accountName": "facebook"},
                ]
            }

    monkeypatch.setattr(connections_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["connections", "compat", "google-sheets:addRow", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "connections compat"
    assert payload["data"]["module"] == "google-sheets:addRow"
    compatible_ids = [row["id"] for row in payload["data"]["compatibleConnections"]]
    incompatible_ids = [row["id"] for row in payload["data"]["incompatibleConnections"]]
    assert 147240 in compatible_ids
    assert 164145 in incompatible_ids
    assert 999 in incompatible_ids
