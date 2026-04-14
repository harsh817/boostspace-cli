"""Helpers for resolving external executables consistently across platforms."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_executable(
    name: str,
    *,
    env_var: str | None = None,
    windows_candidates: list[str] | None = None,
) -> str | None:
    if env_var:
        env_value = os.getenv(env_var, "").strip()
        if env_value:
            return env_value

    candidates = [name]
    if os.name == "nt" and not name.lower().endswith(".cmd"):
        candidates.append(f"{name}.cmd")

    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    if os.name == "nt":
        for candidate in windows_candidates or []:
            path = Path(candidate)
            if path.exists():
                return str(path)

    return None
