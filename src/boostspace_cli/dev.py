"""Developer diagnostics for local CLI installation issues."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import click

from .console import console
from .jsonio import emit_json


def _looks_like_boostspace_repo(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "boostspace-cli"' in text or "name = 'boostspace-cli'" in text


def _repo_root_from_module(module_file: Path) -> Path:
    resolved = module_file.resolve()
    if resolved.parent.name == "boostspace_cli" and resolved.parent.parent.name == "src":
        return resolved.parent.parent.parent
    return resolved.parent


def build_dev_diagnostics(cwd: Path | None = None, module_file: Path | None = None) -> dict[str, Any]:
    """Build diagnostics for local editable-install/source-path drift."""
    current_dir = (cwd or Path.cwd()).resolve()
    current_module = (module_file or Path(__file__)).resolve()
    imported_repo_root = _repo_root_from_module(current_module).resolve()
    cwd_looks_like_repo = _looks_like_boostspace_repo(current_dir)

    import_source_matches_cwd = True
    expected_repo_root: str | None = None
    if cwd_looks_like_repo:
        expected_repo_root = str(current_dir)
        import_source_matches_cwd = imported_repo_root == current_dir

    boost_executable = shutil.which("boost")
    python_paths = [entry for entry in sys.path if "boostspace" in entry.casefold()]
    ok = (not cwd_looks_like_repo) or import_source_matches_cwd

    return {
        "ok": ok,
        "cwd": str(current_dir),
        "cwdLooksLikeRepo": cwd_looks_like_repo,
        "expectedRepoRoot": expected_repo_root,
        "importedRepoRoot": str(imported_repo_root),
        "importSourceMatchesCwd": import_source_matches_cwd,
        "modulePath": str(current_module),
        "boostExecutable": boost_executable,
        "pythonPathEntries": python_paths,
    }


@click.group()
def dev() -> None:
    """Developer diagnostics for local CLI setup."""
    pass


@dev.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def dev_doctor(json_output: bool) -> None:
    """Check whether the installed CLI points at the current repo."""
    diagnostics = build_dev_diagnostics()
    ok = bool(diagnostics["ok"])

    if json_output:
        emit_json(
            ok=ok,
            error=None if ok else "CLI import source does not match the current repo.",
            data=diagnostics,
            meta={"command": "dev doctor"},
        )
        if not ok:
            raise SystemExit(1)
        return

    if ok:
        console.print("[green]Developer environment looks consistent.[/green]")
    else:
        console.print("[red]CLI import source mismatch detected.[/red]")
        console.print("[dim]Run `python -m pip install -e .` from this repo.[/dim]")

    console.print(f"[bold]CWD:[/bold] {diagnostics['cwd']}")
    console.print(f"[bold]Imported repo root:[/bold] {diagnostics['importedRepoRoot']}")
    console.print(f"[bold]Module path:[/bold] {diagnostics['modulePath']}")
    console.print(f"[bold]boost executable:[/bold] {diagnostics['boostExecutable'] or 'not found'}")

    if not ok:
        raise SystemExit(1)
