from boostspace_cli.docs_catalog import extract_app_slugs, extract_feature_slugs, match_goal_apps


def test_extract_app_slugs_from_docs_links():
    raw = """
    https://docs.boost.space/knowledge-base/applications/ai/openai-gpt/
    https://docs.boost.space/knowledge-base/applications/marketing/hubspot/
    https://docs.boost.space/knowledge-base/applications/office/google-sheets/
    https://docs.boost.space/knowledge-base/applications/ai/">AI<
    """
    slugs = extract_app_slugs(raw)
    assert "openai-gpt" in slugs
    assert "hubspot" in slugs
    assert "google-sheets" in slugs
    assert all("<" not in slug and ">" not in slug for slug in slugs)


def test_match_goal_apps_uses_word_boundaries():
    apps = {"google-sheets", "hubspot", "openai-gpt"}
    goal = "Capture lead and push to Google Sheets then notify HubSpot"
    matched = match_goal_apps(goal, apps)
    assert matched == {"google-sheets", "hubspot"}


def test_match_goal_apps_handles_aliases_and_generic_drop():
    apps = {"google", "google-sheets", "hubspotcrm"}
    goal = "Sync records to Google Sheets and HubSpot"
    matched = match_goal_apps(goal, apps)
    assert "google-sheets" in matched
    assert "google" not in matched
    assert "hubspotcrm" in matched


def test_extract_feature_slugs_from_integrations_links():
    raw = """
    https://docs.boost.space/knowledge-base/system/features/comment/
    https://docs.boost.space/knowledge-base/system/features/attachment/
    https://docs.boost.space/knowledge-base/system/connections/setting-up-a-cud-webhook-in-boost-space/
    https://docs.boost.space/knowledge-base/integrations/spaces/what-are-spaces/
    """
    features = extract_feature_slugs(raw)
    assert "comment" in features
    assert "attachment" in features
    assert "setting-up-a-cud-webhook-in-boost-space" in features
    assert "what-are-spaces" in features
