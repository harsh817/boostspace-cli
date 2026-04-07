from boostspace_cli.scenario_builder_core import (
    align_modules_to_known,
    apply_credentials,
    apply_field_mapping_hints,
    build_sample_payload,
    collect_placeholder_tokens,
    inject_connection_ids,
    required_connection_apps,
    unresolved_credential_tokens,
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


def test_apply_credentials_replaces_secret_placeholders():
    blueprint = {"flow": [{"id": 1, "module": "http:ActionSendData", "mapper": {"url": "https://x?token={{API_TOKEN}}"}}]}
    updated, count = apply_credentials(blueprint, {"API_TOKEN": "secret123"})
    assert count == 1
    assert "secret123" in updated["flow"][0]["mapper"]["url"]
    assert unresolved_credential_tokens(updated) == []


def test_apply_field_mapping_hints_maps_sheet_row_from_sample():
    blueprint = {
        "flow": [
            {
                "id": 1,
                "module": "google-sheets:addRow",
                "mapper": {"row": "{{mapped_row_fields}}"},
                "parameters": {},
            }
        ]
    }
    mapped, fixes = apply_field_mapping_hints(blueprint, {"email": "x@example.com", "name": "Test"})
    assert isinstance(mapped["flow"][0]["mapper"]["row"], dict)
    assert mapped["flow"][0]["mapper"]["row"]["email"] == "{{email}}"
    assert len(fixes) >= 1


def test_build_sample_payload_skips_credential_tokens():
    blueprint = {
        "flow": [
            {
                "id": 1,
                "module": "http:ActionSendData",
                "mapper": {"body": "{\"token\":\"{{API_TOKEN}}\",\"email\":\"{{email}}\"}"},
                "parameters": {},
            }
        ]
    }
    tokens = collect_placeholder_tokens(blueprint)
    assert "API_TOKEN" in tokens
    sample = build_sample_payload(blueprint)
    assert "API_TOKEN" not in sample
    assert "email" in sample
