import json

from click.testing import CliRunner

from boostspace_cli.catalog.search import search_modules
from boostspace_cli.catalog.store import known_module_ids, load_registry_with_source, validate_registry
from boostspace_cli.cli import main


def test_shipped_catalog_registry_valid():
    registry, source, _ = load_registry_with_source()
    assert source in {"shipped", "cache"}
    valid, errors = validate_registry(registry)
    assert valid is True
    assert errors == []
    assert isinstance(registry.get("modules"), dict)


def test_known_module_ids_include_native_and_catalog():
    module_ids = known_module_ids()
    assert "gateway:CustomWebHook" in module_ids
    assert "http:ActionSendData" in module_ids


def test_catalog_search_finds_instagram_module():
    registry, _, _ = load_registry_with_source()
    rows = search_modules(registry, query="instagram", limit=10)
    ids = {row.get("id") for row in rows}
    assert "instagram-business:createAPhotoPost" in ids


def test_catalog_module_cli_json_contract():
    runner = CliRunner()
    result = runner.invoke(main, ["catalog", "module", "gateway:CustomWebHook", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "catalog module"
    assert payload["data"]["id"] == "gateway:CustomWebHook"
