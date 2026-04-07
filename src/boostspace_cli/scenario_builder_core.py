"""Core helpers for internet-first scenario building."""

from __future__ import annotations

import json
import re
import time
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")
RESULT_LINK_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")

MODULE_COMPATIBILITY_RULES: dict[str, dict[str, str]] = {
    "webhooks:CustomWebhook": {
        "severity": "error",
        "message": "Legacy webhook module name is invalid in this tenant.",
        "replacement": "gateway:CustomWebHook",
    },
    "google-sheets:addRow": {
        "severity": "warning",
        "message": "Module may be unsupported in some tenants/versions. Verify against your existing Google Sheets scenario modules.",
    },
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "workflow"


def _decode_duckduckgo_link(raw_link: str) -> str:
    if raw_link.startswith("//"):
        raw_link = "https:" + raw_link
    parsed = urlparse(raw_link)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [raw_link])[0]
        return unescape(target)
    return unescape(raw_link)


def _strip_html(html: str) -> str:
    text = TAG_RE.sub(" ", html)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def search_web(query: str, max_results: int = 8) -> list[dict[str, str]]:
    url = f"{DUCKDUCKGO_HTML}?q={quote_plus(query)}"
    headers = {"User-Agent": "boostspace-cli/0.1"}

    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as http:
        response = http.get(url)
        response.raise_for_status()
        html = response.text

    matches = RESULT_LINK_RE.findall(html)
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for raw_link, raw_title in matches:
        link = _decode_duckduckgo_link(raw_link)
        if link in seen:
            continue
        seen.add(link)
        title = _strip_html(raw_title)
        results.append({"title": title, "url": link})
        if len(results) >= max_results:
            break

    return results


def fetch_summary(url: str, max_chars: int = 700) -> str:
    headers = {"User-Agent": "boostspace-cli/0.1"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as http:
            response = http.get(url)
            response.raise_for_status()
            return _strip_html(response.text)[:max_chars]
    except Exception as exc:
        return f"Could not fetch summary: {exc}"


def research_goal(goal: str, max_results: int) -> list[dict[str, str]]:
    queries = [
        f"{goal} make.com scenario",
        f"{goal} boost.space integrator",
        f"{goal} automation module mapping",
    ]
    merged: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for query in queries:
        try:
            results = search_web(query, max_results=max_results)
        except Exception:
            continue
        for item in results:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            merged.append(item)
            if len(merged) >= max_results:
                return merged

    return merged[:max_results]


def guess_modules(goal: str) -> list[dict[str, Any]]:
    g = goal.casefold()
    flow: list[dict[str, Any]] = [
        {
            "id": 1,
            "module": "gateway:CustomWebHook",
            "version": 1,
            "parameters": {"maxResults": 1},
            "mapper": {},
        }
    ]
    module_id = 2

    if "sheet" in g:
        flow.append(
            {
                "id": module_id,
                "module": "google-sheets:addRow",
                "version": 1,
                "parameters": {
                    "__IMTCONN__": "{{connection_google_sheets}}",
                    "spreadsheetId": "{{spreadsheet_id}}",
                    "sheetName": "{{sheet_name}}",
                },
                "mapper": {"row": "{{mapped_row_fields}}"},
            }
        )
        module_id += 1

    if "hubspot" in g or "crm" in g:
        flow.append(
            {
                "id": module_id,
                "module": "hubspot:createContact",
                "version": 1,
                "parameters": {"__IMTCONN__": "{{connection_hubspot}}"},
                "mapper": {"email": "{{email}}", "firstname": "{{first_name}}", "lastname": "{{last_name}}"},
            }
        )
        module_id += 1

    if "slack" in g:
        flow.append(
            {
                "id": module_id,
                "module": "slack:createMessage",
                "version": 1,
                "parameters": {"__IMTCONN__": "{{connection_slack}}", "channel": "{{slack_channel}}"},
                "mapper": {"text": "{{message_text}}"},
            }
        )
        module_id += 1

    if len(flow) == 1:
        flow.append(
            {
                "id": module_id,
                "module": "http:MakeRequest",
                "version": 1,
                "parameters": {"url": "{{target_url}}", "method": "POST"},
                "mapper": {"body": "{{payload}}"},
            }
        )

    return flow


def build_draft(goal: str, sources: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "goal": goal,
        "createdAt": int(time.time()),
        "sources": sources,
        "blueprint": {
            "name": f"Draft - {goal[:70]}",
            "flow": guess_modules(goal),
            "metadata": {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}},
        },
        "notes": [
            "Replace all {{placeholders}} before deploy.",
            "Run `boost scenario validate --file <file>` before create/import.",
        ],
    }


def extract_blueprint(payload: dict[str, Any]) -> dict[str, Any]:
    if "blueprint" in payload and isinstance(payload["blueprint"], dict):
        return payload["blueprint"]
    return payload


def validate_blueprint_data(blueprint: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    flow = blueprint.get("flow") or blueprint.get("modules")

    if not isinstance(flow, list) or not flow:
        errors.append("Blueprint must include non-empty 'flow' list.")
        return errors, warnings

    module_ids: set[int] = set()
    for idx, module in enumerate(flow):
        if not isinstance(module, dict):
            errors.append(f"Module at index {idx} is not an object.")
            continue

        mid = module.get("id")
        if not isinstance(mid, int):
            errors.append(f"Module at index {idx} must have integer 'id'.")
        elif mid in module_ids:
            errors.append(f"Duplicate module id: {mid}")
        else:
            module_ids.add(mid)

        mod = module.get("module")
        if not isinstance(mod, str) or ":" not in mod:
            errors.append(f"Module {mid} missing valid 'module' value (expected app:action).")
        elif mod in MODULE_COMPATIBILITY_RULES:
            rule = MODULE_COMPATIBILITY_RULES[mod]
            text = f"Module {mod}: {rule['message']}"
            if rule.get("severity") == "error":
                errors.append(text)
            else:
                warnings.append(text)

    placeholders = sorted(set(PLACEHOLDER_RE.findall(json.dumps(blueprint))))
    if placeholders:
        warnings.append("Unresolved placeholders: " + ", ".join(placeholders[:20]))

    if "metadata" not in blueprint:
        warnings.append("Missing metadata block.")

    return errors, warnings


def repair_blueprint_data(blueprint: dict[str, Any], goal: str) -> tuple[dict[str, Any], list[str]]:
    fixes: list[str] = []
    flow = blueprint.get("flow") or blueprint.get("modules") or []

    if not isinstance(flow, list) or not flow:
        blueprint["flow"] = guess_modules(goal)
        fixes.append("Added generated flow from goal keywords.")
        flow = blueprint["flow"]

    new_flow: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    next_id = 1

    for module in flow:
        if not isinstance(module, dict):
            continue

        mid = module.get("id")
        if not isinstance(mid, int) or mid in used_ids:
            while next_id in used_ids:
                next_id += 1
            module["id"] = next_id
            used_ids.add(next_id)
            fixes.append(f"Reassigned module id to {next_id}.")
            next_id += 1
        else:
            used_ids.add(mid)

        if not module.get("module"):
            module["module"] = "http:MakeRequest"
            module.setdefault("parameters", {"url": "{{target_url}}", "method": "POST"})
            fixes.append(f"Set default module type for id {module['id']}.")

        module_name = module.get("module")
        if isinstance(module_name, str) and module_name in MODULE_COMPATIBILITY_RULES:
            replacement = MODULE_COMPATIBILITY_RULES[module_name].get("replacement")
            if replacement:
                module["module"] = replacement
                if replacement == "gateway:CustomWebHook":
                    module.setdefault("parameters", {})
                    module["parameters"].pop("name", None)
                    module["parameters"].pop("type", None)
                    module["parameters"].setdefault("maxResults", 1)
                fixes.append(f"Replaced module {module_name} with {replacement}.")

        new_flow.append(module)

    blueprint["flow"] = new_flow
    if not blueprint.get("name"):
        blueprint["name"] = f"Draft - {goal[:70]}"
        fixes.append("Added scenario name.")
    if "metadata" not in blueprint:
        blueprint["metadata"] = {"version": 1, "scenario": {"roundtrips": 1, "maxErrors": 3}}
        fixes.append("Added metadata block.")

    return blueprint, fixes
