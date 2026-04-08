import json

from click.testing import CliRunner

import boostspace_cli.config as config_mod
import boostspace_cli.mcp_cli as mcp_cli_mod
from boostspace_cli.cli import main


def _payload(output: str) -> dict:
    return json.loads(output)


def test_mcp_sync_json_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    def fake_build(*_args, **_kwargs):
        return {
            "meta": {
                "generatedAt": "2026-04-08T00:00:00Z",
                "moduleCount": 12,
                "formulaCount": 16,
                "publicTemplateCount": 100,
                "publicBlueprintProbeCount": 30,
                "workspaceCollected": True,
                "workspaceError": None,
            }
        }

    monkeypatch.setattr(mcp_cli_mod, "build_knowledge_store", fake_build)
    monkeypatch.setattr(mcp_cli_mod, "save_knowledge_store", lambda payload: tmp_path / "knowledge_store.json")

    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "sync", "--json"])
    assert result.exit_code == 0

    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "mcp sync"
    assert payload["data"]["moduleCount"] == 12


def test_mcp_info_json_missing_store(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")
    monkeypatch.setattr(mcp_cli_mod, "load_knowledge_store", lambda: None)

    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "info", "--json"])
    assert result.exit_code == 1

    payload = _payload(result.output)
    assert payload["ok"] is False
    assert payload["meta"]["command"] == "mcp info"
    assert "boost mcp sync" in payload["error"]
