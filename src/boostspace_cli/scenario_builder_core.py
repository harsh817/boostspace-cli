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
TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")

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

INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic", "claude", "claude ai", "anthropic claude"),
    "openai": ("openai", "gpt", "ai post", "ai-written", "ai written", "generate post", "caption", "rewrite"),
    "google_sheets": ("sheet", "spreadsheet", "google sheet", "gsheet"),
    "hubspot": ("hubspot", "crm", "create contact", "sync contact"),
    "slack": ("slack", "notify", "notification", "send message", "channel"),
    "instagram": ("instagram", "ig", "reel", "post to instagram"),
    "linkedin": ("linkedin", "linkedin post", "post on linkedin", "linkedin profile"),
    "http": ("http", "api", "webhook forward", "post to api"),
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


def _has_intent(goal_lc: str, intent: str) -> bool:
    terms = INTENT_PATTERNS.get(intent, ())
    return any(term in goal_lc for term in terms)


def _module_app(module_name: str) -> str:
    return module_name.split(":", 1)[0].strip().casefold() if ":" in module_name else module_name.strip().casefold()


def iter_blueprint_modules(blueprint: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return all modules in a blueprint including nested router routes.

    Returns tuples of (path, module_dict) where path is a best-effort string
    pointing to where the module lives inside the blueprint.
    """

    flow = blueprint.get("flow") or blueprint.get("modules") or []
    if not isinstance(flow, list):
        return []

    out: list[tuple[str, dict[str, Any]]] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, list):
            for idx, item in enumerate(node):
                walk(item, f"{path}[{idx}]")
            return
        if not isinstance(node, dict):
            return

        if "module" in node:
            out.append((path, node))

        routes = node.get("routes")
        if isinstance(routes, list):
            for ridx, route in enumerate(routes):
                if not isinstance(route, dict):
                    continue
                walk(route.get("flow"), f"{path}.routes[{ridx}].flow")

    walk(flow, "flow")
    return out


def module_requires_connection(module: dict[str, Any]) -> bool:
    """Best-effort check whether a module requires __IMTCONN__.

    Many exported blueprints include metadata.parameters that declares __IMTCONN__.
    When present, we treat it as authoritative.
    """

    meta = module.get("metadata")
    if not isinstance(meta, dict):
        return False
    declared = meta.get("parameters")
    if not isinstance(declared, list):
        return False

    for row in declared:
        if not isinstance(row, dict):
            continue
        if row.get("name") == "__IMTCONN__" and bool(row.get("required", False)):
            return True
    return False


def required_connection_apps(blueprint: dict[str, Any]) -> set[str]:
    """Return app keys that need __IMTCONN__ wiring."""
    apps: set[str] = set()

    for _, module in iter_blueprint_modules(blueprint):
        module_name = module.get("module")
        if not isinstance(module_name, str):
            continue

        requires = module_requires_connection(module)
        params = module.get("parameters")
        if not isinstance(params, dict):
            params = {}
        value = params.get("__IMTCONN__")

        # If the module explicitly declares __IMTCONN__, require an integer.
        if requires:
            if not isinstance(value, int):
                apps.add(_module_app(module_name))
            continue

        # Back-compat: If __IMTCONN__ is present, we still consider it a wiring target.
        if "__IMTCONN__" in params and not isinstance(value, int):
            apps.add(_module_app(module_name))
    return apps


def inject_connection_ids(blueprint: dict[str, Any], connections: dict[str, int]) -> tuple[dict[str, Any], int, list[str]]:
    """Inject integer connection IDs into modules requiring __IMTCONN__."""
    wired = 0
    missing: set[str] = set()

    for _, module in iter_blueprint_modules(blueprint):
        module_name = module.get("module")
        if not isinstance(module_name, str):
            continue

        requires = module_requires_connection(module)
        params = module.get("parameters")
        if not isinstance(params, dict):
            params = {}
            module["parameters"] = params

        should_wire = requires or "__IMTCONN__" in params
        if not should_wire:
            continue
        if isinstance(params.get("__IMTCONN__"), int):
            continue

        app = _module_app(module_name)
        conn_id = connections.get(app)
        if conn_id is None:
            missing.add(app)
            continue
        params["__IMTCONN__"] = int(conn_id)
        wired += 1

    return blueprint, wired, sorted(missing)


def align_modules_to_known(blueprint: dict[str, Any], known_modules: set[str]) -> tuple[dict[str, Any], list[str]]:
    """Replace unknown modules with best known module from same app family."""
    flow = blueprint.get("flow") or blueprint.get("modules") or []
    if not isinstance(flow, list) or not known_modules:
        return blueprint, []

    replacements: list[str] = []
    known_by_app: dict[str, list[str]] = {}
    for known in known_modules:
        app = _module_app(known)
        known_by_app.setdefault(app, []).append(known)

    for module in flow:
        if not isinstance(module, dict):
            continue
        current = module.get("module")
        if not isinstance(current, str) or current in known_modules:
            continue
        app = _module_app(current)
        candidates = sorted(known_by_app.get(app, []), key=str.casefold)
        if not candidates:
            continue

        current_action = current.split(":", 1)[1].casefold() if ":" in current else ""
        preferred = next((item for item in candidates if current_action and current_action in item.casefold()), None)
        replacement = preferred or candidates[0]
        module["module"] = replacement
        replacements.append(f"{current} -> {replacement}")

    return blueprint, replacements


def seed_known_native_modules(
    blueprint: dict[str, Any],
    goal_apps: set[str],
    known_modules: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Append tenant-known native modules for requested goal apps not yet in flow."""
    flow = blueprint.get("flow") or blueprint.get("modules") or []
    if not isinstance(flow, list) or not goal_apps or not known_modules:
        return blueprint, []

    existing_apps = {_module_app(str(module.get("module", ""))) for module in flow if isinstance(module, dict)}
    max_id = 0
    for module in flow:
        if isinstance(module, dict) and isinstance(module.get("id"), int):
            max_id = max(max_id, int(module["id"]))

    known_by_app: dict[str, list[str]] = {}
    for item in known_modules:
        app = _module_app(item)
        known_by_app.setdefault(app, []).append(item)

    def rank(module_name: str) -> tuple[int, str]:
        lowered = module_name.casefold()
        if "create" in lowered or "add" in lowered:
            return (0, module_name)
        if "update" in lowered or "upsert" in lowered:
            return (1, module_name)
        if "watch" in lowered or "new" in lowered:
            return (2, module_name)
        if "search" in lowered or "list" in lowered or "get" in lowered:
            return (3, module_name)
        return (4, module_name)

    added: list[str] = []
    for app in sorted(goal_apps):
        if app in existing_apps:
            continue
        candidates = sorted(known_by_app.get(app, []), key=rank)
        if not candidates:
            continue
        max_id += 1
        selected = candidates[0]
        flow.append(
            {
                "id": max_id,
                "module": selected,
                "version": 1,
                "parameters": {},
                "mapper": {},
            }
        )
        added.append(selected)
        existing_apps.add(app)

    return blueprint, added


def guess_modules(
    goal: str,
    trigger: str = "webhook",
    connections: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Build a flow list from a goal string.

    Args:
        goal: Natural-language workflow goal.
        trigger: One of 'webhook', 'schedule'. Defaults to 'webhook'.
        connections: Optional mapping of app name -> integer connection ID,
                     e.g. {"openai-gpt-3": 42, "google-sheets": 17}.
                     When provided, native app modules use the real ID instead
                     of a string placeholder (which the API rejects).
    """
    g = goal.casefold()
    conns = connections or {}

    # --- trigger module ---
    if trigger == "schedule":
        flow: list[dict[str, Any]] = []  # scheduled scenarios have no trigger module
    else:
        flow = [
            {
                "id": 1,
                "module": "gateway:CustomWebHook",
                "version": 1,
                "parameters": {"maxResults": 1},
                "mapper": {},
            }
        ]
    module_id = len(flow) + 1

    # --- AI text generation (Anthropic preferred; OpenAI as fallback) ---
    needs_ai = _has_intent(g, "anthropic") or _has_intent(g, "openai") or _has_intent(g, "instagram") or _has_intent(g, "linkedin")
    if needs_ai:
        use_anthropic = _has_intent(g, "anthropic") or not _has_intent(g, "openai")
        if use_anthropic:
            conn_id = conns.get("anthropic-claude")
            params: dict[str, Any] = {}
            if conn_id:
                params["__IMTCONN__"] = conn_id
            flow.append(
                {
                    "id": module_id,
                    "module": "anthropic-claude:createAMessage",
                    "version": 1,
                    "parameters": params,
                    "mapper": {
                        "model": "claude-opus-4-5",
                        "max_tokens": 1024,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Write an engaging social media post for today. Include relevant hashtags. Keep it under 200 words.",
                            }
                        ],
                    },
                }
            )
        else:
            conn_id = conns.get("openai-gpt-3")
            params = {}
            if conn_id:
                params["__IMTCONN__"] = conn_id
            flow.append(
                {
                    "id": module_id,
                    "module": "openai-gpt-3:CreateCompletion",
                    "version": 1,
                    "parameters": params,
                    "mapper": {
                        "model": "gpt-3.5-turbo-instruct",
                        "prompt": "Write an engaging social media post for today. Include emojis and 5-8 relevant hashtags at the end. Keep it under 200 words.",
                        "max_tokens": 300,
                        "temperature": 0.8,
                    },
                }
            )
        ai_module_id = module_id
        module_id += 1
    else:
        ai_module_id = None

    # --- Google Sheets ---
    if _has_intent(g, "google_sheets") or _has_intent(g, "linkedin") or _has_intent(g, "instagram"):
        conn_id = conns.get("google-sheets")
        # For scheduled/trigger scenarios reading topics from a sheet, use watchRows.
        # For webhook-driven scenarios writing results, use addRow.
        reading_from_sheet = trigger == "schedule" or any(
            kw in g for kw in ("read from", "read topic", "fetch from", "get from", "from sheet", "from spreadsheet")
        )
        if reading_from_sheet:
            params = {
                "__IMTCONN__": conn_id if conn_id else "{{connection_google_sheets}}",
            }
            flow.insert(
                0,
                {
                    "id": module_id,
                    "module": "google-sheets:watchRows",
                    "version": 2,
                    "parameters": params,
                    "mapper": {},
                },
            )
            # Re-assign IDs so watchRows is always first
            for i, mod in enumerate(flow):
                if isinstance(mod, dict):
                    mod["id"] = i + 1
            module_id = len(flow) + 1
        else:
            params = {
                "spreadsheetId": "{{spreadsheet_id}}",
                "sheetName": "{{sheet_name}}",
            }
            if conn_id:
                params["__IMTCONN__"] = conn_id
            else:
                params["__IMTCONN__"] = "{{connection_google_sheets}}"
            flow.append(
                {
                    "id": module_id,
                    "module": "google-sheets:addRow",
                    "version": 1,
                    "parameters": params,
                    "mapper": {"row": "{{mapped_row_fields}}"},
                }
            )
            module_id += 1

    # --- HubSpot / CRM ---
    if _has_intent(g, "hubspot"):
        conn_id = conns.get("hubspot")
        params = {}
        if conn_id:
            params["__IMTCONN__"] = conn_id
        else:
            params["__IMTCONN__"] = "{{connection_hubspot}}"
        flow.append(
            {
                "id": module_id,
                "module": "hubspot:createContact",
                "version": 1,
                "parameters": params,
                "mapper": {"email": "{{email}}", "firstname": "{{first_name}}", "lastname": "{{last_name}}"},
            }
        )
        module_id += 1

    # --- Slack ---
    if _has_intent(g, "slack"):
        conn_id = conns.get("slack")
        params = {"channel": "{{slack_channel}}"}
        if conn_id:
            params["__IMTCONN__"] = conn_id
        else:
            params["__IMTCONN__"] = "{{connection_slack}}"
        flow.append(
            {
                "id": module_id,
                "module": "slack:createMessage",
                "version": 1,
                "parameters": params,
                "mapper": {"text": "{{message_text}}"},
            }
        )
        module_id += 1

    # --- LinkedIn (native module) ---
    if _has_intent(g, "linkedin"):
        conn_id = conns.get("linkedin")
        params = {}
        if conn_id:
            params["__IMTCONN__"] = conn_id
        else:
            params["__IMTCONN__"] = "{{connection_linkedin}}"
        ai_output_ref = "{{" + str(ai_module_id) + ".content[0].text}}" if ai_module_id else "{{post_content}}"
        flow.append(
            {
                "id": module_id,
                "module": "linkedin:CreatePost",
                "version": 2,
                "parameters": params,
                "mapper": {
                    "content": ai_output_ref,
                    "visibility": "PUBLIC",
                    "feedDistribution": "MAIN_FEED",
                    "isReshareDisabledByAuthor": False,
                },
            }
        )
        module_id += 1

    # --- Instagram (native instagram-business module) ---
    if _has_intent(g, "instagram"):
        conn_id = conns.get("instagram-business")
        params = {}
        if conn_id:
            params["__IMTCONN__"] = conn_id
        else:
            params["__IMTCONN__"] = "{{connection_instagram_business}}"
        caption_ref = "{{" + str(ai_module_id) + ".content[0].text}}" if ai_module_id else "{{caption}}"
        flow.append(
            {
                "id": module_id,
                "module": "instagram-business:createAPhotoPost",
                "version": 1,
                "parameters": params,
                "mapper": {
                    "imageUrl": "{{IMAGE_URL}}",
                    "caption": caption_ref,
                },
            }
        )
        module_id += 1

    # --- fallback ---
    if trigger == "schedule" and not flow:
        flow.append(
            {
                "id": module_id,
                "module": "util:SetVariables",
                "version": 1,
                "parameters": {},
                "mapper": {"value": "{{payload}}"},
            }
        )
    elif len(flow) == 1 and flow[0]["module"] == "gateway:CustomWebHook" and _has_intent(g, "http"):
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


def build_draft(
    goal: str,
    sources: list[dict[str, str]],
    trigger: str = "webhook",
    connections: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "goal": goal,
        "createdAt": int(time.time()),
        "sources": sources,
        "blueprint": {
            "name": f"Draft - {goal[:70]}",
            "flow": guess_modules(goal, trigger=trigger, connections=connections),
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

    modules = iter_blueprint_modules(blueprint)
    if not modules:
        errors.append("Blueprint must include non-empty 'flow' list.")
        return errors, warnings

    module_ids: set[int] = set()
    for path, module in modules:
        mid = module.get("id")
        if not isinstance(mid, int):
            errors.append(f"Module at {path} must have integer 'id'.")
        elif mid in module_ids:
            errors.append(f"Duplicate module id: {mid} (at {path})")
        else:
            module_ids.add(mid)

        mod = module.get("module")
        if not isinstance(mod, str) or ":" not in mod:
            errors.append(f"Module {mid} at {path} missing valid 'module' value (expected app:action).")
        elif mod in MODULE_COMPATIBILITY_RULES:
            rule = MODULE_COMPATIBILITY_RULES[mod]
            text = f"Module {mod}: {rule['message']}"
            if rule.get("severity") == "error":
                errors.append(text)
            else:
                warnings.append(text)

        if module_requires_connection(module):
            params = module.get("parameters")
            conn_ok = isinstance(params, dict) and isinstance(params.get("__IMTCONN__"), int)
            if not conn_ok:
                errors.append(f"Module {mid} at {path} missing required __IMTCONN__ connection id.")

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


def collect_placeholder_tokens(payload: Any) -> set[str]:
    tokens: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, str):
            for match in TOKEN_RE.findall(node):
                token = match.strip()
                if token:
                    tokens.add(token)

    walk(payload)
    return tokens


def _is_credential_token(token: str) -> bool:
    if "." in token:
        return False
    upper_token = token.upper()
    credential_markers = (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "API_KEY",
        "CLIENT_ID",
        "CLIENT_SECRET",
        "ACCESS",
        "BEARER",
    )
    if any(marker in upper_token for marker in credential_markers):
        return True
    return token.isupper() and len(token) >= 4


def apply_credentials(payload: Any, credentials: dict[str, str]) -> tuple[Any, int]:
    """Replace {{TOKEN}} placeholders with credential values."""
    replaced = 0

    def replace_string(text: str) -> str:
        nonlocal replaced

        def sub(match: re.Match[str]) -> str:
            nonlocal replaced
            token = match.group(1).strip()
            if token in credentials:
                replaced += 1
                return str(credentials[token])
            return match.group(0)

        return TOKEN_RE.sub(sub, text)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return replace_string(node)
        return node

    return walk(payload), replaced


def unresolved_credential_tokens(payload: Any) -> list[str]:
    tokens = collect_placeholder_tokens(payload)
    unresolved = sorted(token for token in tokens if _is_credential_token(token))
    return unresolved


def apply_field_mapping_hints(blueprint: dict[str, Any], sample_data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Improve mapper placeholders using provided sample data."""
    flow = blueprint.get("flow") or blueprint.get("modules") or []
    if not isinstance(flow, list):
        return blueprint, []

    sample_keys = [str(key) for key in sample_data.keys()]
    sample_keys_lc = {key.casefold(): key for key in sample_keys}
    fixes: list[str] = []

    def best_key(token: str) -> str | None:
        if token in sample_data:
            return token
        token_lc = token.casefold()
        if token_lc in sample_keys_lc:
            return sample_keys_lc[token_lc]
        compact = re.sub(r"[^a-z0-9]", "", token_lc)
        for key in sample_keys:
            key_compact = re.sub(r"[^a-z0-9]", "", key.casefold())
            if key_compact == compact:
                return key
        return None

    for module in flow:
        if not isinstance(module, dict):
            continue
        module_name = str(module.get("module", ""))
        mapper = module.get("mapper")
        if not isinstance(mapper, dict):
            continue

        if module_name == "google-sheets:addRow" and mapper.get("row") == "{{mapped_row_fields}}":
            mapper["row"] = {key: "{{" + key + "}}" for key in sample_keys}
            fixes.append("Mapped google-sheets:addRow row fields from sample payload")

        for key, value in list(mapper.items()):
            if not isinstance(value, str):
                continue
            matches = TOKEN_RE.findall(value)
            if len(matches) != 1:
                continue
            token = matches[0]
            if token in sample_data:
                continue
            replacement_key = best_key(token)
            if not replacement_key:
                continue
            mapper[key] = "{{" + replacement_key + "}}"
            fixes.append(f"Mapped {module_name}.{key} from {token} to {replacement_key}")

    return blueprint, fixes


def build_sample_payload(blueprint: dict[str, Any], seed_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a sample payload for test-run validation."""
    sample: dict[str, Any] = dict(seed_data or {})
    tokens = collect_placeholder_tokens(blueprint)

    for token in sorted(tokens):
        if token in sample:
            continue
        if token.startswith("connection_") or "." in token:
            continue
        if _is_credential_token(token):
            continue
        if token.startswith("spreadsheet") or token.startswith("sheet"):
            continue

        token_lc = token.casefold()
        if "email" in token_lc:
            sample[token] = "qa@example.com"
        elif "phone" in token_lc:
            sample[token] = "+12025550123"
        elif "name" in token_lc:
            sample[token] = "Test User"
        elif "id" in token_lc:
            sample[token] = "test-id-001"
        elif "date" in token_lc:
            sample[token] = "2026-01-01"
        else:
            sample[token] = f"sample-{token}"

    return sample
