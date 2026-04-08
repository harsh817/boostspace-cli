from pathlib import Path

import pytest

from boostspace_cli.catalog import refresh as refresh_mod


def test_catalog_refresh_requires_npm(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh_mod.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError):
        refresh_mod._run_npm_pack(Path(tmp_path), package_name="@make-org/apps")
