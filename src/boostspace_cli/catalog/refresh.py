"""Refresh offline catalog from Make.com integration page snapshots or @make-org/apps npm package."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Literal

from ..executables import resolve_executable
from .builders.make_apps_npm import build_registry_from_extracted_package
from .builders.make_apps_web import build_registry_from_web_snapshot
from .store import CACHE_REGISTRY_PATH, load_cached_registry, save_cached_registry, validate_registry

CatalogSource = Literal["web", "npm"]
DEFAULT_SOURCE: CatalogSource = "web"


def _run_npm_pack(workdir: Path, package_name: str) -> tuple[Path, str]:
    appdata = os.getenv("APPDATA", "").strip()
    windows_candidates: list[str] = []
    if appdata:
        windows_candidates.append(str(Path(appdata) / "npm" / "npm.cmd"))
    npm_bin = resolve_executable("npm", windows_candidates=windows_candidates)
    if npm_bin is None:
        raise RuntimeError("npm not found. Install Node.js/npm to use --source npm.")

    process = subprocess.run(
        [npm_bin, "pack", package_name, "--json"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "npm pack failed"
        raise RuntimeError(f"npm pack failed: {message}")

    package_file: Path | None = None
    package_version = "unknown"
    stdout = process.stdout.strip()
    if stdout:
        try:
            payload = json.loads(stdout)
            if isinstance(payload, list) and payload:
                item = payload[0]
                if isinstance(item, dict):
                    filename = item.get("filename")
                    if isinstance(filename, str) and filename.strip():
                        package_file = workdir / filename
                    version = item.get("version")
                    if isinstance(version, str) and version.strip():
                        package_version = version
        except Exception:
            pass

    if package_file is None:
        tgz_files = sorted(workdir.glob("*.tgz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not tgz_files:
            raise RuntimeError("npm pack did not produce a .tgz file")
        package_file = tgz_files[0]

    return package_file, package_version


def _build_from_npm(package_name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="boost-catalog-") as tmp:
        temp_root = Path(tmp)
        tgz_path, package_version = _run_npm_pack(temp_root, package_name=package_name)

        extract_root = temp_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tgz_path, mode="r:gz") as archive:
            archive.extractall(path=extract_root)

        registry = build_registry_from_extracted_package(extract_root)
        if package_version != "unknown":
            meta = registry.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["packageVersion"] = package_version

    return registry


def refresh_catalog(
    force: bool = False,
    source: CatalogSource = DEFAULT_SOURCE,
    package_name: str = "@make-org/apps",
) -> dict[str, Any]:
    """Refresh the offline module catalog.

    Args:
        force: Skip cache and rebuild even if a cached registry exists.
        source: ``"web"`` uses the bundled Make.com integration page snapshot
                (no network required, always works). ``"npm"`` fetches the
                ``@make-org/apps`` npm package (requires Node.js, may fail).
        package_name: npm package name, only used when *source* is ``"npm"``.
    """
    if not force:
        cached = load_cached_registry()
        if cached is not None:
            meta = cached.get("meta", {}) if isinstance(cached, dict) else {}
            return {
                "cachePath": str(CACHE_REGISTRY_PATH),
                "source": meta.get("source", "cache"),
                "packageVersion": meta.get("packageVersion", "unknown"),
                "moduleCount": meta.get("moduleCount", 0),
                "appCount": meta.get("appCount", 0),
                "reused": True,
            }

    if source == "npm":
        registry = _build_from_npm(package_name)
    else:
        registry = build_registry_from_web_snapshot()

    valid, errors = validate_registry(registry)
    if not valid:
        raise RuntimeError("Catalog build produced invalid registry: " + "; ".join(errors[:5]))

    cache_path = save_cached_registry(registry)
    meta = registry.get("meta", {}) if isinstance(registry, dict) else {}

    return {
        "cachePath": str(cache_path),
        "source": meta.get("source", source),
        "packageVersion": meta.get("packageVersion", "unknown"),
        "moduleCount": meta.get("moduleCount", 0),
        "appCount": meta.get("appCount", 0),
        "reused": False,
    }
