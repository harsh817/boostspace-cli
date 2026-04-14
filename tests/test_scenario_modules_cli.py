import json

from click.testing import CliRunner

from boostspace_cli.cli import main
import boostspace_cli.scenario_builder as scenario_builder_mod
import boostspace_cli.config as config_mod


def test_scenario_modules_json_reports_runtime_states(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    class FakeClient:
        def __init__(self, _config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(scenario_builder_mod, "APIClient", FakeClient)
    monkeypatch.setattr(scenario_builder_mod, "tenant_known_modules", lambda *args, **kwargs: {"gateway:CustomWebHook", "google-sheets:addRow"})
    monkeypatch.setattr(scenario_builder_mod, "known_module_ids", lambda: {"gateway:CustomWebHook", "google-sheets:addRow", "http:ActionSendData"})

    runner = CliRunner()
    result = runner.invoke(main, ["scenario", "modules", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    rows = {row["module"]: row for row in payload["data"]}
    assert rows["gateway:CustomWebHook"]["catalogKnown"] is True
    assert rows["gateway:CustomWebHook"]["tenantSeen"] is True
    assert rows["gateway:CustomWebHook"]["tenantDeployable"] is True
    assert rows["gateway:CustomWebHook"]["confidence"] == "tenant_proven"
