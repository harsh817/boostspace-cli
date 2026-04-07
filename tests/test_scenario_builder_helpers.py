from boostspace_cli.scenario_builder_helpers import module_names_from_blueprint, normalize_app_key


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
