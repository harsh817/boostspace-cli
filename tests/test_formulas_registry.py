import json

from click.testing import CliRunner

from boostspace_cli.cli import main
from boostspace_cli.formulas.lint import lint_formula_usage
from boostspace_cli.formulas.search import search_functions
from boostspace_cli.formulas.store import known_formula_functions, load_formula_registry


def test_formula_search_returns_date_functions():
    registry = load_formula_registry()
    rows = search_functions(registry, query="date", limit=10)
    names = {row.get("name") for row in rows}
    assert "formatDate" in names


def test_formula_lint_detects_unknown_functions():
    payload = {
        "blueprint": {
            "flow": [
                {
                    "id": 1,
                    "module": "util:SetVariables",
                    "mapper": {"foo": "{{unknownFunc(email)}}", "bar": "{{lower(email)}}"},
                }
            ]
        }
    }
    result = lint_formula_usage(payload, known_formula_functions())
    assert result["ok"] is False
    unknown_names = {item["name"] for item in result["unknown"]}
    assert "unknownFunc" in unknown_names


def test_formulas_lint_cli_strict_returns_nonzero(tmp_path):
    file_path = tmp_path / "blueprint.json"
    file_path.write_text(
        json.dumps(
            {
                "blueprint": {
                    "flow": [
                        {
                            "id": 1,
                            "module": "util:SetVariables",
                            "mapper": {"foo": "{{badFn(x)}}"},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["formulas", "lint", "--file", str(file_path), "--strict", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["meta"]["command"] == "formulas lint"
