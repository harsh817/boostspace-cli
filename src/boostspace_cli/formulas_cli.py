"""Top-level formulas registry commands."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.table import Table

from .console import console
from .formulas.lint import lint_formula_file
from .formulas.search import function_detail, search_functions
from .formulas.store import known_formula_functions, load_formula_registry
from .jsonio import emit_json


@click.group("formulas")
def formulas_cli() -> None:
    """Search and lint formula/function usage."""


@formulas_cli.command("search")
@click.argument("query", type=str)
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def formulas_search(query: str, limit: int, json_output: bool) -> None:
    """Search known formula functions."""
    registry = load_formula_registry()
    rows = search_functions(registry, query=query, limit=limit)

    if json_output:
        emit_json(data=rows, meta={"command": "formulas search", "query": query, "limit": limit})
        return

    if not rows:
        console.print("[yellow]No matching formulas found.[/yellow]")
        return

    table = Table(title=f"Formula Search ({len(rows)})")
    table.add_column("Function", style="cyan")
    table.add_column("Signature", style="white")
    table.add_column("Description", style="white")
    for row in rows:
        table.add_row(str(row.get("name", "")), str(row.get("signature", "")), str(row.get("description", "")))
    console.print(table)


@formulas_cli.command("info")
@click.argument("name", type=str)
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def formulas_info(name: str, json_output: bool) -> None:
    """Show one formula function definition."""
    registry = load_formula_registry()
    details = function_detail(registry, name)
    if details is None:
        if json_output:
            emit_json(ok=False, error=f"Function not found: {name}", meta={"command": "formulas info"})
            raise SystemExit(1)
        console.print(f"[red]Function not found: {name}[/red]")
        raise SystemExit(1)

    if json_output:
        emit_json(data=details, meta={"command": "formulas info"})
        return

    console.print_json(json.dumps(details, indent=2))


@formulas_cli.command("lint")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--strict", is_flag=True, help="Exit non-zero on unknown functions")
@click.option("--json", "json_output", is_flag=True, help="Output JSON")
def formulas_lint(file_path: Path, strict: bool, json_output: bool) -> None:
    """Lint formula function calls inside a blueprint file."""
    try:
        result = lint_formula_file(file_path, known_formula_functions())
    except ValueError as exc:
        if json_output:
            emit_json(ok=False, error=str(exc), meta={"command": "formulas lint"})
            raise SystemExit(1)
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    if json_output:
        unknown = result.get("unknown", [])
        error = "Unknown formula functions detected" if unknown else None
        emit_json(ok=result.get("ok", False), error=error, data=result, meta={"command": "formulas lint", "strict": strict})
        if strict and result.get("unknown"):
            raise SystemExit(1)
        return

    unknown = result.get("unknown", [])
    if unknown:
        console.print(f"[yellow]Unknown formula functions: {len(unknown)}[/yellow]")
        for entry in unknown:
            console.print(f"- {entry.get('name')} ({entry.get('count')}x)")
    else:
        console.print("[green]No unknown formula functions found.[/green]")

    if strict and unknown:
        raise SystemExit(1)
