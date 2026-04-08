"""Parallel multi-agent orchestration for build/debug workflows."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .catalog.search import search_modules
from .catalog.store import load_registry_with_source
from .client import APIClient
from .docs_catalog import load_documented_app_slugs, load_documented_features, match_goal_apps
from .scenario_builder_helpers import module_names_from_blueprint, team_connection_map, tenant_known_modules
from .scenario_lookup import resolve_scenario_id
from .workspace_assets import extract_folders, extract_templates, search_templates

AgentFn = Callable[[], dict[str, Any]]


def _tokenize(text: str) -> list[str]:
    tokens = [part for part in re.split(r"[^a-z0-9]+", text.casefold()) if part]
    return [token for token in tokens if len(token) >= 3]


def run_parallel_agents(agent_jobs: dict[str, AgentFn], max_workers: int = 4) -> list[dict[str, Any]]:
    if not agent_jobs:
        return []

    safe_workers = max(1, min(int(max_workers), len(agent_jobs)))
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=safe_workers, thread_name_prefix="boost-agent") as executor:
        future_to_name = {executor.submit(fn): name for name, fn in agent_jobs.items()}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                payload = future.result()
            except Exception as exc:
                results.append({"agent": name, "ok": False, "error": str(exc), "durationSeconds": None, "data": None})
                continue

            if not isinstance(payload, dict):
                payload = {"data": payload}
            payload.setdefault("agent", name)
            payload.setdefault("ok", True)
            payload.setdefault("error", None)
            payload.setdefault("durationSeconds", None)
            results.append(payload)

    results.sort(key=lambda item: str(item.get("agent", "")).casefold())
    return results


def _run_timed(agent: str, fn: AgentFn) -> dict[str, Any]:
    started = time.perf_counter()
    data = fn()
    return {
        "agent": agent,
        "ok": True,
        "error": None,
        "durationSeconds": round(time.perf_counter() - started, 3),
        "data": data,
    }


def _build_agents(
    config: Any,
    team_id: int | None,
    goal: str,
    folder_name: str | None,
    cache_ttl: int,
) -> dict[str, AgentFn]:
    tokens = _tokenize(goal)

    def planner_agent() -> dict[str, Any]:
        steps = [
            "Gather workspace template matches",
            "Match documented apps/features",
            "Collect tenant-proven modules and connection readiness",
            "Generate draft and run preflight deploy dry-run",
        ]
        return {
            "mode": "build",
            "goal": goal,
            "parallelTasks": ["template_scout", "docs_scout", "catalog_scout", "tenant_scout", "folder_scout"],
            "steps": steps,
        }

    def template_scout() -> dict[str, Any]:
        with APIClient(config) as client:
            payload = client.list_workspace_templates(
                team_id=team_id,
                organization_id=config.organization_id,
                limit=120,
                query=goal,
                public_only=True,
            )
        templates = extract_templates(payload)
        matches = search_templates(templates, query=goal, public_only=True, limit=8)
        return {
            "sourcePath": payload.get("_sourcePath") if isinstance(payload, dict) else None,
            "total": len(templates),
            "matches": matches,
        }

    def docs_scout() -> dict[str, Any]:
        docs_apps = load_documented_app_slugs(refresh=False)
        docs_features = load_documented_features(refresh=False)
        return {
            "apps": sorted(match_goal_apps(goal, docs_apps)),
            "features": sorted(match_goal_apps(goal, docs_features)),
        }

    def catalog_scout() -> dict[str, Any]:
        registry, source, _ = load_registry_with_source()
        queries = [goal] + tokens[:4]
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for query in queries:
            for row in search_modules(registry, query=query, limit=12):
                module_id = str(row.get("id", ""))
                if not module_id or module_id in seen:
                    continue
                seen.add(module_id)
                rows.append(row)
        return {
            "source": source,
            "moduleMatches": rows[:20],
        }

    def tenant_scout() -> dict[str, Any]:
        with APIClient(config) as client:
            known = tenant_known_modules(
                client,
                team_id,
                config.organization_id,
                scan_limit=40,
                use_cache=True,
                refresh_cache=False,
                cache_ttl_seconds=cache_ttl,
            )
            connections = team_connection_map(client, team_id)
        return {
            "knownModuleCount": len(known),
            "knownModuleSample": sorted(known, key=str.casefold)[:20],
            "connections": [{"app": app, "id": cid} for app, cid in sorted(connections.items())],
        }

    def folder_scout() -> dict[str, Any]:
        with APIClient(config) as client:
            payload = client.list_scenario_folders(team_id=team_id, organization_id=config.organization_id, limit=250)
        folders = extract_folders(payload)
        q = folder_name or goal
        matches = [row for row in folders if q.casefold() in str(row.get("name", "")).casefold()]
        return {
            "sourcePath": payload.get("_sourcePath") if isinstance(payload, dict) else None,
            "total": len(folders),
            "matches": matches[:20],
        }

    return {
        "planner": lambda: _run_timed("planner", planner_agent),
        "template_scout": lambda: _run_timed("template_scout", template_scout),
        "docs_scout": lambda: _run_timed("docs_scout", docs_scout),
        "catalog_scout": lambda: _run_timed("catalog_scout", catalog_scout),
        "tenant_scout": lambda: _run_timed("tenant_scout", tenant_scout),
        "folder_scout": lambda: _run_timed("folder_scout", folder_scout),
    }


def _debug_agents(
    config: Any,
    team_id: int | None,
    scenario_id: int | None,
    scenario_name: str | None,
    cache_ttl: int,
) -> dict[str, AgentFn]:
    def resolve_agent() -> dict[str, Any]:
        with APIClient(config) as client:
            resolved = resolve_scenario_id(client, team_id, config.organization_id, scenario_id, scenario_name)
        return {"scenarioId": resolved}

    def blueprint_agent() -> dict[str, Any]:
        with APIClient(config) as client:
            resolved = resolve_scenario_id(client, team_id, config.organization_id, scenario_id, scenario_name)
            blueprint = client.get_blueprint(resolved)
        modules = sorted(module_names_from_blueprint(blueprint), key=str.casefold)
        return {"scenarioId": resolved, "moduleCount": len(modules), "modules": modules[:60]}

    def execution_agent() -> dict[str, Any]:
        with APIClient(config) as client:
            resolved = resolve_scenario_id(client, team_id, config.organization_id, scenario_id, scenario_name)
            logs = client.get_logs(resolved, limit=10)
            incomplete = client.get_incomplete_executions(resolved)
        rows = logs.get("scenarioLogs", []) if isinstance(logs, dict) else []
        simplified = []
        for row in rows[:10]:
            if not isinstance(row, dict):
                continue
            simplified.append({"imtId": row.get("imtId"), "status": row.get("status"), "started": row.get("dateStart")})
        pending = incomplete.get("incompleteExecutions", []) if isinstance(incomplete, dict) else []
        return {"scenarioId": resolved, "recentLogs": simplified, "incompleteCount": len(pending)}

    def compat_agent() -> dict[str, Any]:
        with APIClient(config) as client:
            resolved = resolve_scenario_id(client, team_id, config.organization_id, scenario_id, scenario_name)
            blueprint = client.get_blueprint(resolved)
            known = tenant_known_modules(
                client,
                team_id,
                config.organization_id,
                scan_limit=40,
                use_cache=True,
                refresh_cache=False,
                cache_ttl_seconds=cache_ttl,
            )
        registry, _, _ = load_registry_with_source()
        modules_map = registry.get("modules", {}) if isinstance(registry, dict) else {}
        current = module_names_from_blueprint(blueprint)
        unknown = sorted(module for module in current if module not in modules_map)
        unproven = sorted(module for module in current if module not in known and module in modules_map)
        return {"scenarioId": resolved, "unknownModules": unknown, "tenantUnprovenModules": unproven}

    return {
        "resolver": lambda: _run_timed("resolver", resolve_agent),
        "blueprint_inspector": lambda: _run_timed("blueprint_inspector", blueprint_agent),
        "execution_scout": lambda: _run_timed("execution_scout", execution_agent),
        "compat_scout": lambda: _run_timed("compat_scout", compat_agent),
    }


def run_swarm(
    mode: str,
    config: Any,
    team_id: int | None,
    goal: str | None,
    scenario_id: int | None,
    scenario_name: str | None,
    folder_name: str | None,
    parallelism: int,
    cache_ttl: int,
) -> dict[str, Any]:
    if mode == "build":
        if not goal:
            raise ValueError("--goal is required for build mode")
        agents = _build_agents(config, team_id, goal, folder_name, cache_ttl)
    else:
        if scenario_id is None and not scenario_name:
            raise ValueError("Provide --scenario-id or --name for debug mode")
        agents = _debug_agents(config, team_id, scenario_id, scenario_name, cache_ttl)

    started = time.perf_counter()
    agent_results = run_parallel_agents(agents, max_workers=parallelism)
    ok_count = sum(1 for item in agent_results if item.get("ok"))
    fail_count = len(agent_results) - ok_count

    return {
        "mode": mode,
        "parallelism": max(1, int(parallelism)),
        "agents": agent_results,
        "okAgents": ok_count,
        "failedAgents": fail_count,
        "durationSeconds": round(time.perf_counter() - started, 3),
    }
