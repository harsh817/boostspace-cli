from boostspace_cli.catalog.templates import parse_templates_html, search_templates


def test_parse_templates_html_extracts_templates_and_apps():
    html = """
    <div class="card">
      <img alt="Instagram" src="insta.svg" />
      <img alt="Google Sheets" src="gs.svg" />
      <a href="/en/templates/1234-post-instagram-content-from-sheets">Instagram Posts from Sheets</a>
    </div>
    <div class="card">
      <img alt="Slack" src="slack.svg" />
      <a href="/en/templates/9999-send-daily-alert-to-slack">Daily Slack Alert</a>
    </div>
    """

    rows = parse_templates_html(html)
    assert len(rows) == 2
    assert rows[0]["title"] == "Daily Slack Alert"
    assert rows[1]["slug"] == "1234-post-instagram-content-from-sheets"
    assert "Instagram" in rows[1]["apps"]
    assert "Google Sheets" in rows[1]["apps"]


def test_search_templates_filters_by_query_and_app():
    registry = {
        "templates": [
            {
                "slug": "1234-post-instagram-content-from-sheets",
                "url": "https://www.make.com/en/templates/1234-post-instagram-content-from-sheets",
                "title": "Instagram Posts from Sheets",
                "apps": ["Instagram", "Google Sheets"],
            },
            {
                "slug": "9999-send-daily-alert-to-slack",
                "url": "https://www.make.com/en/templates/9999-send-daily-alert-to-slack",
                "title": "Daily Slack Alert",
                "apps": ["Slack"],
            },
        ]
    }

    instagram_rows = search_templates(registry, query="instagram")
    assert len(instagram_rows) == 1
    assert instagram_rows[0]["slug"] == "1234-post-instagram-content-from-sheets"

    slack_rows = search_templates(registry, app="slack")
    assert len(slack_rows) == 1
    assert slack_rows[0]["title"] == "Daily Slack Alert"
