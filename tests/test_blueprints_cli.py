import json

from click.testing import CliRunner

from boostspace_cli.cli import main
import boostspace_cli.blueprints as blueprints_mod
import boostspace_cli.config as config_mod


def _payload(output: str) -> dict:
    return json.loads(output)


def test_blueprints_validate_accepts_wrapper_file(monkeypatch, tmp_path):
    wrapper_path = tmp_path / "wrapper.json"
    wrapper_path.write_text(
        json.dumps(
            {
                "goal": "test",
                "blueprint": {
                    "name": "Wrapped",
                    "flow": [{"id": 1, "module": "gateway:CustomWebHook", "version": 1, "parameters": {"maxResults": 1}, "mapper": {}}],
                    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
                },
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["blueprints", "validate", str(wrapper_path), "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["data"]["valid"] is True


def test_blueprints_import_accepts_wrapper_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    wrapper_path = tmp_path / "wrapper-import.json"
    wrapper_path.write_text(
        json.dumps(
            {
                "goal": "test import",
                "blueprint": {
                    "name": "Wrapped Import",
                    "flow": [{"id": 1, "module": "gateway:CustomWebHook", "version": 1, "parameters": {"maxResults": 1}, "mapper": {}}],
                    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
                },
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

        def create_scenario(self, **kwargs):
            assert kwargs["blueprint"]["name"] == "Wrapped Import"
            return {"scenario": {"id": 999}}

    monkeypatch.setattr(blueprints_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["blueprints", "import", str(wrapper_path), "--team-id", "123", "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["data"]["id"] == 999


def test_blueprints_update_accepts_wrapper_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_mod, "DEFAULT_COOKIE_PATH", tmp_path / "cookies.json")

    wrapper_path = tmp_path / "wrapper-update.json"
    wrapper_path.write_text(
        json.dumps(
            {
                "goal": "test update",
                "blueprint": {
                    "name": "Wrapped Update",
                    "flow": [{"id": 1, "module": "gateway:CustomWebHook", "version": 1, "parameters": {"maxResults": 1}, "mapper": {}}],
                    "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
                },
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

        def patch(self, path, json=None):
            assert path == "/scenarios/123"
            assert "Wrapped Update" in json["blueprint"]
            return {"scenario": {"id": 123, "name": "Wrapped Update", "isinvalid": False}}

    monkeypatch.setattr(blueprints_mod, "APIClient", FakeClient)

    runner = CliRunner()
    result = runner.invoke(main, ["blueprints", "update", "123", str(wrapper_path), "--json"])

    assert result.exit_code == 0
    payload = _payload(result.output)
    assert payload["ok"] is True
    assert payload["data"]["id"] == 123
