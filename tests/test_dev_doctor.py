import json
from pathlib import Path

from click.testing import CliRunner

from boostspace_cli import dev as dev_mod
from boostspace_cli.cli import main


def test_build_dev_diagnostics_flags_import_source_mismatch(tmp_path):
    cwd = tmp_path / "boostspace-cli"
    cwd.mkdir()
    (cwd / "pyproject.toml").write_text('[project]\nname = "boostspace-cli"\n', encoding="utf-8")

    module_file = tmp_path / "stale" / "boostspace-cli" / "src" / "boostspace_cli" / "dev.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    diagnostics = dev_mod.build_dev_diagnostics(cwd=cwd, module_file=module_file)

    assert diagnostics["ok"] is False
    assert diagnostics["cwdLooksLikeRepo"] is True
    assert diagnostics["importSourceMatchesCwd"] is False
    assert diagnostics["expectedRepoRoot"] == str(cwd)


def test_dev_doctor_json_envelope():
    runner = CliRunner()

    result = runner.invoke(main, ["dev", "doctor", "--json"])

    assert result.exit_code in {0, 1}
    payload = json.loads(result.output)
    assert payload["meta"]["command"] == "dev doctor"
    assert "modulePath" in payload["data"]
    assert "importedRepoRoot" in payload["data"]
