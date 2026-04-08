"""Knowledge snapshot builder for local MCP server tools."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .catalog.search import search_modules
from .catalog.store import CACHE_REGISTRY_PATH, load_registry_with_source
from .catalog.templates import DEFAULT_TEMPLATES_URL, build_template_registry, load_template_registry, save_template_registry
from .client import APIClient
from .config import Config
from .formulas.search import search_functions
from .formulas.store import load_formula_registry
from .workspace_assets import extract_folders, extract_templates

MCP_CACHE_DIR = Path.home() / ".boostspace-cli" / "mcp"
MCP_KNOWLEDGE_PATH = MCP_CACHE_DIR / "knowledge_store.json"

_JSON_LINK_RE = re.compile(r"href=[\"'](?P<href>[^\"']+\.json[^\"']*)[\"']", flags=re.IGNORECASE)
_BLUEPRINT_KEY_RE = re.compile(r"\"blueprint\"\s*:", flags=re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _extract_balanced_json_object(text: str, start_index: int) -> dict[str, Any] | None:
    depth = 0
    in_string = False
    escaped = False
    begin = -1

    for idx in range(start_index, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            if begin < 0:
                begin = idx
            depth += 1
            continue

        if ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and begin >= 0:
                raw = text[begin : idx + 1]
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None

    return None


def extract_public_blueprint_candidates(html: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for match in _JSON_LINK_RE.finditer(html):
        href = match.group("href").strip()
        candidates.append({"type": "json_link", "value": href})

    for match in _BLUEPRINT_KEY_RE.finditer(html):
        obj = _extract_balanced_json_object(html, match.end())
        if obj:
            candidates.append({"type": "inline_blueprint", "value": obj})
            break

    return candidates


def _collect_public_blueprints(
    templates: list[dict[str, Any]],
    blueprint_limit: int,
    timeout_seconds: float = 20.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if blueprint_limit <= 0:
        return rows

    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for template in templates[: blueprint_limit]:
            url = str(template.get("url", "")).strip()
            if not url:
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
                candidates = extract_public_blueprint_candidates(html)
                rows.append(
                    {
                        "templateUrl": url,
                        "title": template.get("title"),
                        "slug": template.get("slug"),
                        "candidateCount": len(candidates),
                        "candidates": candidates[:5],
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "templateUrl": url,
                        "title": template.get("title"),
                        "slug": template.get("slug"),
                        "candidateCount": 0,
                        "error": str(exc),
                    }
                )
    return rows


def _collect_workspace_assets(config: Config) -> dict[str, Any]:
    with APIClient(config) as client:
        team_id = config.team_id
        org_id = config.organization_id
        templates_payload = client.list_workspace_templates(team_id=team_id, organization_id=org_id, limit=200, public_only=False)
        folders_payload = client.list_scenario_folders(team_id=team_id, organization_id=org_id, limit=300)
        connections_payload = client.list_connections(team_id=team_id)

    templates = extract_templates(templates_payload)
    folders = extract_folders(folders_payload)
    connections = connections_payload.get("connections", []) if isinstance(connections_payload, dict) else []
    return {
        "templates": templates,
        "folders": folders,
        "connections": connections,
        "sourcePaths": {
            "templates": templates_payload.get("_sourcePath") if isinstance(templates_payload, dict) else None,
            "folders": folders_payload.get("_sourcePath") if isinstance(folders_payload, dict) else None,
        },
    }


def build_knowledge_store(
    config: Config,
    refresh_templates: bool = False,
    include_workspace_assets: bool = True,
    include_public_blueprints: bool = True,
    blueprint_limit: int = 30,
) -> dict[str, Any]:
    registry, registry_source, _ = load_registry_with_source()
    formulas = load_formula_registry()

    templates_registry, template_source, _ = load_template_registry()
    if refresh_templates or templates_registry is None:
        templates_registry = build_template_registry(DEFAULT_TEMPLATES_URL)
        save_template_registry(templates_registry)
        template_source = "fresh"

    public_templates = templates_registry.get("templates", []) if isinstance(templates_registry, dict) else []
    if not isinstance(public_templates, list):
        public_templates = []

    workspace_assets: dict[str, Any] | None = None
    workspace_error: str | None = None
    if include_workspace_assets:
        try:
            workspace_assets = _collect_workspace_assets(config)
        except Exception as exc:
            workspace_error = str(exc)

    public_blueprints: list[dict[str, Any]] = []
    if include_public_blueprints:
        public_blueprints = _collect_public_blueprints(
            [item for item in public_templates if isinstance(item, dict)],
            blueprint_limit=max(0, int(blueprint_limit)),
        )

    sample_queries = ["webhook", "instagram", "google sheets", "openai"]
    module_samples = {
        query: search_modules(registry, query=query, limit=8)
        for query in sample_queries
    }
    formula_samples = {
        query: search_functions(formulas, query=query, limit=8)
        for query in ["date", "if", "replace", "concat"]
    }

    payload = {
        "meta": {
            "generatedAt": _utc_now(),
            "registrySource": registry_source,
            "templateSource": template_source,
            "moduleCount": registry.get("meta", {}).get("moduleCount") if isinstance(registry, dict) else None,
            "formulaCount": formulas.get("meta", {}).get("functionCount") if isinstance(formulas, dict) else None,
            "publicTemplateCount": len(public_templates),
            "publicBlueprintProbeCount": len(public_blueprints),
            "workspaceCollected": workspace_assets is not None,
            "workspaceError": workspace_error,
        },
        "modules": registry,
        "formulas": formulas,
        "publicTemplates": templates_registry,
        "publicBlueprintCandidates": public_blueprints,
        "workspace": workspace_assets,
        "samples": {
            "moduleMatches": module_samples,
            "formulaMatches": formula_samples,
        },
        "files": {
            "moduleRegistryCache": str(CACHE_REGISTRY_PATH),
            "knowledgePath": str(MCP_KNOWLEDGE_PATH),
        },
    }
    return payload


def save_knowledge_store(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or MCP_KNOWLEDGE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_knowledge_store(path: Path | None = None) -> dict[str, Any] | None:
    target = path or MCP_KNOWLEDGE_PATH
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
