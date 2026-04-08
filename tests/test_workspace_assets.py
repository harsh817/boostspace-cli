from boostspace_cli.workspace_assets import (
    extract_folders,
    extract_templates,
    find_folder_by_name,
    search_templates,
)


def test_extract_templates_reads_common_payload_shapes():
    payload = {
        "templates": [
            {"id": 11, "name": "Lead Capture to Sheets", "isPublic": True, "folderId": 7},
            {"id": 12, "title": "Slack Alerts", "visibility": "private"},
        ]
    }
    rows = extract_templates(payload)
    assert len(rows) == 2
    assert rows[0]["name"] == "Lead Capture to Sheets"
    assert rows[0]["public"] is True
    assert rows[1]["public"] is False


def test_search_templates_filters_by_query_and_public():
    templates = [
        {"id": 1, "name": "Lead Capture to Sheets", "description": "Webhook to Google Sheets", "public": True},
        {"id": 2, "name": "Internal Ops", "description": "Private task", "public": False},
    ]
    rows = search_templates(templates, query="lead", public_only=True, limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == 1


def test_extract_folders_and_match_by_name():
    payload = {
        "folders": [
            {"id": 101, "name": "Marketing"},
            {"id": 102, "name": "Sales Ops", "parentId": 101},
        ]
    }
    folders = extract_folders(payload)
    assert len(folders) == 2
    match, candidates = find_folder_by_name(folders, "sales")
    assert match is not None
    assert match["id"] == 102
    assert len(candidates) == 1
