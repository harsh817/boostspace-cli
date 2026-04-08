import json

from boostspace_cli.mcp_knowledge import (
    extract_public_blueprint_candidates,
    load_knowledge_store,
    save_knowledge_store,
)


def test_extract_public_blueprint_candidates_finds_links_and_inline_blueprint():
    html = """
    <html>
      <body>
        <a href="https://example.com/template-blueprint.json">Download</a>
        <script>
          window.__DATA__ = {"blueprint": {"flow": [{"id": 1, "module": "gateway:CustomWebHook"}]}};
        </script>
      </body>
    </html>
    """

    rows = extract_public_blueprint_candidates(html)
    assert len(rows) >= 2
    assert any(item.get("type") == "json_link" for item in rows)
    inline = next((item for item in rows if item.get("type") == "inline_blueprint"), None)
    assert inline is not None
    assert inline["value"]["flow"][0]["module"] == "gateway:CustomWebHook"


def test_save_and_load_knowledge_store_roundtrip(tmp_path):
    payload = {"meta": {"generatedAt": "2026-04-08T00:00:00Z"}, "modules": {"meta": {"moduleCount": 1}}}
    path = tmp_path / "knowledge_store.json"
    saved = save_knowledge_store(payload, path=path)
    assert saved == path

    loaded = load_knowledge_store(path=path)
    assert loaded is not None
    assert loaded["meta"]["generatedAt"] == "2026-04-08T00:00:00Z"
    assert loaded["modules"]["meta"]["moduleCount"] == 1

    # sanity check file actually contains JSON object
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["meta"]["generatedAt"] == payload["meta"]["generatedAt"]
