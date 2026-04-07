"""Consistent JSON envelope output helpers for CLI commands."""

from __future__ import annotations

import json
from typing import Any

import click


def emit_json(data: Any = None, ok: bool = True, error: str | None = None, meta: dict[str, Any] | None = None) -> None:
    payload = {
        "ok": bool(ok),
        "data": data,
        "error": error,
        "meta": meta or {},
    }
    click.echo(json.dumps(payload, indent=2, default=str))
