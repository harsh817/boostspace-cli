from boostspace_cli.scenario_builder_core import (
    align_modules_to_known,
    inject_connection_ids,
    required_connection_apps,
    seed_known_native_modules,
)


def test_required_connection_apps_detects_unwired_modules():
    blueprint = {
        "flow": [
            {"id": 1, "module": "openai-gpt-3:CreateCompletion", "parameters": {"__IMTCONN__": "{{connection_openai}}"}},
            {"id": 2, "module": "google-sheets:addRow", "parameters": {"__IMTCONN__": "{{connection_google_sheets}}"}},
        ]
    }
    apps = required_connection_apps(blueprint)
    assert "openai-gpt-3" in apps
    assert "google-sheets" in apps


def test_inject_connection_ids_wires_integer_values():
    blueprint = {
        "flow": [
            {"id": 1, "module": "openai-gpt-3:CreateCompletion", "parameters": {"__IMTCONN__": "{{connection_openai}}"}},
            {"id": 2, "module": "slack:createMessage", "parameters": {"__IMTCONN__": "{{connection_slack}}"}},
        ]
    }
    wired_blueprint, wired_count, missing = inject_connection_ids(
        blueprint,
        {"openai-gpt-3": 41, "slack": 99},
    )

    assert wired_count == 2
    assert missing == []
    assert wired_blueprint["flow"][0]["parameters"]["__IMTCONN__"] == 41
    assert wired_blueprint["flow"][1]["parameters"]["__IMTCONN__"] == 99


def test_align_modules_to_known_replaces_unknown_variant():
    blueprint = {
        "flow": [
            {"id": 1, "module": "slack:postMessage", "parameters": {}, "mapper": {}},
        ]
    }
    aligned, replacements = align_modules_to_known(blueprint, {"slack:createMessage"})
    assert aligned["flow"][0]["module"] == "slack:createMessage"
    assert replacements == ["slack:postMessage -> slack:createMessage"]


def test_seed_known_native_modules_adds_missing_goal_app():
    blueprint = {
        "flow": [
            {"id": 1, "module": "gateway:CustomWebHook", "parameters": {"maxResults": 1}, "mapper": {}},
        ]
    }
    seeded, added = seed_known_native_modules(
        blueprint,
        {"hubspot"},
        {"hubspot:createContact", "hubspot:searchContacts"},
    )
    assert len(added) == 1
    assert seeded["flow"][1]["module"].startswith("hubspot:")
