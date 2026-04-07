from boostspace_cli.scenario_builder_core import (
    build_draft,
    repair_blueprint_data,
    validate_blueprint_data,
)


def test_build_draft_contains_flow():
    draft = build_draft("lead webhook to sheet", [])
    assert "blueprint" in draft
    assert isinstance(draft["blueprint"].get("flow"), list)
    assert len(draft["blueprint"]["flow"]) >= 1


def test_validate_flags_duplicate_module_ids():
    blueprint = {
        "name": "dup-id",
        "flow": [
            {"id": 1, "module": "gateway:CustomWebHook", "version": 1, "parameters": {"maxResults": 1}},
            {"id": 1, "module": "util:SetVariables", "version": 1, "mapper": {}},
        ],
    }
    errors, warnings = validate_blueprint_data(blueprint)
    assert any("Duplicate module id" in err for err in errors)
    assert isinstance(warnings, list)


def test_repair_replaces_legacy_webhook_module():
    blueprint = {
        "name": "legacy",
        "flow": [
            {
                "id": 1,
                "module": "webhooks:CustomWebhook",
                "version": 1,
                "parameters": {"name": "legacy", "type": "custom"},
            }
        ],
    }
    repaired, fixes = repair_blueprint_data(blueprint, "goal")
    assert repaired["flow"][0]["module"] == "gateway:CustomWebHook"
    assert any("Replaced module webhooks:CustomWebhook" in item for item in fixes)
