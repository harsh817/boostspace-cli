from boostspace_cli.scenario_builder_helpers import normalize_app_key


def test_normalize_app_key_applies_known_aliases():
    assert normalize_app_key("HubSpotCRM") == "hubspot"
    assert normalize_app_key("openai-gpt") == "openai-gpt-3"
    assert normalize_app_key("google_sheets") == "google-sheets"
