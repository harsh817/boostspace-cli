import json

from click.testing import CliRunner

import boostspace_cli.client as client_mod
import boostspace_cli.config as config_mod
import boostspace_cli.executions as executions_mod
import boostspace_cli.scenario_builder as scenario_builder_mod
import boostspace_cli.webhooks as webhooks_mod
from boostspace_cli.cli import main
from boostspace_cli.client import APIError


def _payload(output: str) -> dict:
    return json.loads(output)


def test_configure_json_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    runner = CliRunner()
    result = runner.invoke(main, ["configure", "--backend", "boostspace", "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["error"] is None
    assert payload["meta"]["command"] == "configure"
    assert payload["data"]["backend"] == "boostspace"


def test_whoami_json_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_user(self):
            return {"user": {"name": "QA Lead", "email": "qa@example.com"}}

    monkeypatch.setattr(client_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["whoami", "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "whoami"
    assert payload["data"]["name"] == "QA Lead"
    assert payload["data"]["email"] == "qa@example.com"


def test_webhooks_list_json_error_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    class FailingClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_webhooks(self):
            raise APIError(403, "Forbidden", {"code": "IM015"})

    monkeypatch.setattr(webhooks_mod, "APIClient", FailingClient)

    runner = CliRunner()
    result = runner.invoke(main, ["webhooks", "list", "--json"])

    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    assert payload["meta"]["command"] == "webhooks list"
    assert "API error 403" in payload["error"]


def test_scenario_deploy_dry_run_json_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    blueprint_path = tmp_path / "draft.json"
    blueprint_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "name": "Dry Run Draft",
                    "flow": [
                        {
                            "id": 1,
                            "module": "gateway:CustomWebHook",
                            "version": 1,
                            "parameters": {"maxResults": 1},
                            "mapper": {},
                        }
                    ],
                    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_user(self):
            return {"user": {"email": "qa@example.com"}}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "deploy",
            "--file",
            str(blueprint_path),
            "--dry-run",
            "--no-guard-compat",
            "--team-id",
            "123",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "scenario deploy"
    assert payload["data"]["dryRun"] is True
    assert payload["data"]["teamId"] == 123


def test_executions_status_json_envelope(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get_execution(self, _scenario_id, _execution_id):
            return {"execution": {"status": 1, "duration": 42, "operations": 3}}

    monkeypatch.setattr(executions_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["executions", "status", "exec-1", "--scenario-id", "123", "--json"],
    )

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "executions status"
    assert payload["data"]["scenarioId"] == 123
    assert payload["data"]["statusText"] == "success"
