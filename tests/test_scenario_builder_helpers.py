import json
import time

from boostspace_cli.scenario_builder_helpers import (
    module_names_from_blueprint,
    normalize_app_key,
    tenant_known_modules,
)


def test_normalize_app_key_applies_known_aliases():
    assert normalize_app_key("HubSpotCRM") == "hubspot"
    assert normalize_app_key("openai-gpt") == "openai-gpt-3"
    assert normalize_app_key("google_sheets") == "google-sheets"


def test_module_names_from_blueprint_reads_nested_routes():
    blueprint: dict[str, object] = {
        "flow": [
            {"id": 1, "module": "gateway:CustomWebHook"},
            {
                "id": 2,
                "module": "builtin:BasicRouter",
                "routes": [
                    {"flow": [{"id": 3, "module": "instagram-business:CreatePostPhoto"}]}
                ],
            },
        ]
    }
    modules = module_names_from_blueprint(blueprint)
    assert "gateway:CustomWebHook" in modules
    assert "instagram-business:CreatePostPhoto" in modules


def test_tenant_known_modules_reads_cache_without_api_calls(tmp_path):
    cache_path = tmp_path / "tenant_modules.json"
    payload = {
        "entries": {
            "team:1|org:2|limit:0": {
                "teamId": 1,
                "organizationId": 2,
                "scanLimit": 0,
                "scannedAt": int(time.time()),
                "modules": ["gateway:CustomWebHook", "google-sheets:addRow"],
            }
        }
    }
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    class DummyClient:
        def list_scenarios(self, team_id=None, organization_id=None, limit=0):
            raise AssertionError("list_scenarios should not be called when cache is fresh")

        def get_blueprint(self, scenario_id: int):
            raise AssertionError("get_blueprint should not be called when cache is fresh")

    known = tenant_known_modules(
        DummyClient(),  # type: ignore[arg-type]
        team_id=1,
        organization_id=2,
        scan_limit=0,
        use_cache=True,
        refresh_cache=False,
        cache_ttl_seconds=3600,
        cache_path=cache_path,
    )
    assert "gateway:CustomWebHook" in known
    assert "google-sheets:addRow" in known


def test_tenant_known_modules_writes_cache_after_scan(tmp_path):
    cache_path = tmp_path / "tenant_modules.json"

    class DummyClient:
        def list_scenarios(self, team_id=None, organization_id=None, limit=0):
            return {"scenarios": [{"id": 7}]}

        def get_blueprint(self, scenario_id: int):
            assert scenario_id == 7
            return {"flow": [{"id": 1, "module": "openai-gpt-3:CreateCompletion"}]}

    known = tenant_known_modules(
        DummyClient(),  # type: ignore[arg-type]
        team_id=3,
        organization_id=9,
        scan_limit=5,
        use_cache=True,
        refresh_cache=True,
        cache_ttl_seconds=3600,
        cache_path=cache_path,
    )
    assert known == {"openai-gpt-3:CreateCompletion"}

    cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    entry = cached_payload["entries"]["team:3|org:9|limit:5"]
    assert "openai-gpt-3:CreateCompletion" in entry["modules"]
