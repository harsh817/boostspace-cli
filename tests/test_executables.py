from boostspace_cli.executables import resolve_executable


def test_resolve_executable_prefers_env_var(monkeypatch):
    monkeypatch.setenv("TEST_BIN", r"C:\tools\custom.cmd")
    assert resolve_executable("ignored", env_var="TEST_BIN") == r"C:\tools\custom.cmd"


def test_resolve_executable_uses_which(monkeypatch):
    monkeypatch.delenv("TEST_BIN", raising=False)
    monkeypatch.setattr("boostspace_cli.executables.os.name", "posix")
    monkeypatch.setattr("boostspace_cli.executables.shutil.which", lambda name: "/usr/bin/npm" if name == "npm" else None)
    assert resolve_executable("npm") == "/usr/bin/npm"


def test_resolve_executable_checks_windows_candidates(monkeypatch, tmp_path):
    candidate = tmp_path / "npm.cmd"
    candidate.write_text("", encoding="utf-8")
    monkeypatch.setattr("boostspace_cli.executables.os.name", "nt")
    monkeypatch.setattr("boostspace_cli.executables.shutil.which", lambda _name: None)
    assert resolve_executable("npm", windows_candidates=[str(candidate)]) == str(candidate)
