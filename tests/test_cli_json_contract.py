import json

from click.testing import CliRunner

import boostspace_cli.client as client_mod
import boostspace_cli.connections as connections_mod
import boostspace_cli.config as config_mod
import boostspace_cli.executions as executions_mod
import boostspace_cli.scenarios as scenarios_mod
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

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": []}

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


def test_connections_list_json_envelope(monkeypatch, tmp_path):
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
                    {"id": 9, "accountName": "OpenAI Prod", "accountType": "openai-gpt-3"},
                    {"id": 12, "accountName": "Sheets Main", "accountType": "google-sheets"},
                ]
            }

    monkeypatch.setattr(connections_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["connections", "list", "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "connections list"
    assert len(payload["data"]) == 2


def test_scenario_deploy_dry_run_autowires_connection_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    draft_path = tmp_path / "draft-wire.json"
    draft_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "name": "Wire Draft",
                    "flow": [
                        {
                            "id": 1,
                            "module": "openai-gpt-3:CreateCompletion",
                            "version": 1,
                            "parameters": {"__IMTCONN__": "{{connection_openai}}"},
                            "mapper": {"prompt": "hello"},
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

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": [{"id": 42, "accountType": "openai-gpt-3", "accountName": "OpenAI"}]}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "deploy",
            "--file",
            str(draft_path),
            "--team-id",
            "123",
            "--dry-run",
            "--no-guard-compat",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["data"]["autoWiredConnections"] == 1
    assert "openai-gpt-3" in payload["data"]["requiredConnectionApps"]


def test_scenario_deploy_dry_run_fails_when_connection_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    draft_path = tmp_path / "draft-missing.json"
    draft_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "name": "Missing Conn Draft",
                    "flow": [
                        {
                            "id": 1,
                            "module": "google-sheets:addRow",
                            "version": 1,
                            "parameters": {"__IMTCONN__": "{{connection_google_sheets}}"},
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

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": []}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "deploy",
            "--file",
            str(draft_path),
            "--team-id",
            "123",
            "--dry-run",
            "--no-guard-compat",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    assert "Missing native app connections" in payload["error"]


def test_scenario_draft_auto_resolves_connections(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")
    monkeypatch.setenv("BOOST_TEAM_ID", "123")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": [{"id": 11, "accountType": "google-sheets", "accountName": "Sheet"}]}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)

    output_file = tmp_path / "draft-sheet.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "draft",
            "--goal",
            "webhook to google sheet",
            "--output",
            str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0
    draft = json.loads(output_file.read_text(encoding="utf-8"))
    flow = draft["blueprint"]["flow"]
    sheet_modules = [m for m in flow if m.get("module") == "google-sheets:addRow"]
    assert len(sheet_modules) == 1
    assert sheet_modules[0]["parameters"]["__IMTCONN__"] == 11


def test_scenarios_create_validates_indefinite_interval(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")
    monkeypatch.setenv("BOOST_TEAM_ID", "123")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def create_scenario(self, **_kwargs):
            raise AssertionError("create_scenario should not be called for invalid interval")

    monkeypatch.setattr(scenarios_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenarios",
            "create",
            "--name",
            "bad-schedule",
            "--schedule-type",
            "indefinitely",
            "--interval",
            "0",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    assert "--interval must be a positive integer" in payload["error"]


def test_scenario_coach_json_minimal_guidance(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")
    monkeypatch.setenv("BOOST_TEAM_ID", "123")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def list_scenarios(self, team_id=None, organization_id=None, limit=80):
            _ = team_id, organization_id, limit
            return {"scenarios": []}

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": [{"id": 42, "accountType": "openai-gpt-3", "accountName": "OpenAI"}]}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)
    monkeypatch.setattr(scenario_builder_mod, "research_goal", lambda goal, max_results=4: [])

    output_file = tmp_path / "coach-draft.json"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "coach",
            "--goal",
            "Generate response with OpenAI",
            "--non-interactive",
            "--output",
            str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "scenario coach"
    assert payload["data"]["draftOutput"] == str(output_file)
    assert isinstance(payload["data"]["recommendations"], list)


def test_scenario_deploy_replaces_credentials_and_verifies_run(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    draft_path = tmp_path / "draft-cred.json"
    draft_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "name": "Credential Draft",
                    "flow": [
                        {
                            "id": 1,
                            "module": "http:ActionSendData",
                            "version": 3,
                            "parameters": {},
                            "mapper": {"url": "https://api.example.com?token={{API_TOKEN}}", "body": "{\"email\":\"{{email}}\"}"},
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

        def list_connections(self, team_id=None):
            _ = team_id
            return {"connections": []}

        def create_scenario(self, **_kwargs):
            return {"scenario": {"id": 555}}

        def run_scenario(self, scenario_id, data=None, responsive=True, callback_url=None):
            _ = scenario_id, data, responsive, callback_url
            return {"executionId": "exec-1", "status": 1}

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "deploy",
            "--file",
            str(draft_path),
            "--team-id",
            "123",
            "--allow-http-fallback",
            "--no-guard-compat",
            "--credential",
            "API_TOKEN=secret",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["data"]["credentialReplacements"] >= 1
    assert payload["data"]["verification"]["statusText"] == "success"


def test_scenario_deploy_fails_when_credentials_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    draft_path = tmp_path / "draft-missing-cred.json"
    draft_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "name": "Missing Credential Draft",
                    "flow": [
                        {
                            "id": 1,
                            "module": "http:ActionSendData",
                            "version": 3,
                            "parameters": {},
                            "mapper": {"url": "https://api.example.com?token={{API_TOKEN}}"},
                        }
                    ],
                    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
                }
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "scenario",
            "deploy",
            "--file",
            str(draft_path),
            "--dry-run",
            "--allow-http-fallback",
            "--no-guard-compat",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = _payload(result.output)
    assert payload["ok"] is False
    assert "Missing credential values" in payload["error"]
