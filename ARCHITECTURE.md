# Boost.space CLI — Architecture & Fix Plan

## Current State

The CLI wraps the Boost.space Integrator API (Make-compatible) via session-cookie auth.
It ships 19 passing tests, ~3700 lines of source, and 9 command groups.

All tests pass as of the audit date. The issues below are not crashes — they are gaps
that make the tool unreliable for real workflow automation.

---

## Command Map

```
boost
├── init                      # login + org/team detection
├── configure                 # set backend/zone/org/team
├── whoami                    # current user
├── auth
│   ├── playwright            # login via browser automation
│   ├── status                # check session health
│   ├── clear                 # wipe stored credentials
│   └── doctor [--fix]        # diagnose + optionally repair auth
├── scenarios
│   ├── list                  # list all scenarios
│   ├── get <id>              # get scenario details + optional blueprint
│   ├── create                # create from blueprint file
│   ├── update <id>           # rename, reschedule, toggle active
│   ├── delete <id>           # delete
│   ├── clone <id>            # clone to a team
│   ├── start <id>            # activate
│   ├── stop <id>             # deactivate
│   ├── health                # health report (DLQ, last status)
│   └── top-issues            # scenarios ranked by operational risk
├── scenario
│   ├── brainstorm            # produce a spec JSON from a goal
│   ├── research              # web-search patterns for a goal
│   ├── draft                 # generate blueprint from spec/goal
│   ├── validate              # lint blueprint + check auth
│   ├── repair                # auto-fix common blueprint issues
│   ├── deploy                # create + activate scenario from blueprint
│   └── modules               # list modules proven in your tenant
├── executions
│   ├── run <id>              # trigger a scenario run
│   ├── history <id>          # list execution logs
│   └── status <id>           # check a specific execution
├── webhooks
│   └── list                  # list webhooks
├── blueprints
│   └── ...                   # blueprint management
└── connections               # NEW (added this session)
    └── list                  # list connections with real IDs
```

---

## File Structure

```
src/boostspace_cli/
├── cli.py                    # entry point, command registration
├── client.py                 # HTTP client, all API calls
├── config.py                 # config file + keyring storage
├── auth.py                   # Playwright login, doctor
├── scenarios.py              # scenario CRUD commands
├── scenario_builder.py       # brainstorm/research/draft/validate/repair/deploy
├── scenario_builder_core.py  # pure functions: guess_modules, build_draft, validate, repair
├── connections.py            # NEW: connections list
├── executions.py             # execution run/history/status
├── webhooks.py               # webhook list
├── blueprints.py             # blueprint management
├── scenario_lookup.py        # resolve scenario by name or ID
├── jsonio.py                 # standardised JSON output envelope
└── console.py                # rich console singleton
```

---

## Known Issues (Priority Order)

### P0 — Breaks silently or corrupts data

**1. `__IMTCONN__` sends string placeholders instead of integer IDs**

File: `scenario_builder_core.py`, `guess_modules()`

The API requires `"__IMTCONN__": 108535` (integer). The old code emitted
`"__IMTCONN__": "{{connection_openai}}"` (string). The API returns
`22P02 invalid_text_representation` (PostgreSQL integer parse failure) and the
scenario is never created.

Fix added this session: `guess_modules()` now accepts a `connections: dict[str, int]`
argument. When passed, `__IMTCONN__` is set to the integer. Without it, the module
is omitted entirely (the API allows connectionless HTTP modules).

**What still needs to happen:** the `deploy` command should auto-resolve connections
from the live tenant instead of requiring the user to pass `--connection APP:ID`
manually. See P1 item 3 below.

---

**2. `scenarios create` silently requires `scheduling` but the CLI doesn't enforce it**

File: `scenarios.py`, `create_scenario()`

When `scheduling` is omitted, the API returns:
`SC400: Missing value of required parameter 'scheduling'`

But the CLI shows a generic "bad request" with no hint about what's missing.

Fix: the `create_scenario` command should always pass a scheduling dict.
The default should be `{"type": "on-demand"}` when no schedule flags are given.

```python
# scenarios.py — create_scenario command
scheduling = {"type": schedule_type}
if schedule_type == "indefinitely" and interval:
    scheduling["interval"] = interval
# Always pass it — the API requires it
result = client.create_scenario(..., scheduling=scheduling, ...)
```

---

**3. `scenario deploy` blocks on `IM007` with no actionable message**

File: `scenario_builder.py`, `scenario_deploy()`

`IM007` means "invalid blueprint/module". The guard-compat check scans existing
scenario blueprints to build a "proven modules" list. But `get_blueprint()` uses the
wrong response path:

```python
# scenario_builder.py:91 — WRONG
blueprint = bp_resp.get("response", {}).get("blueprint")

# The actual API response shape is:
# {"response": {"blueprint": {...}}}  OR  {"blueprint": {...}}
# Neither is validated before use — if wrong path, blueprint is None
# and _tenant_known_modules returns empty set, causing all modules to
# be flagged as "unproven" and deploy is blocked
```

Fix: normalise the blueprint extraction:

```python
# client.py — get_blueprint should return the inner blueprint dict
def get_blueprint(self, scenario_id: int) -> dict:
    resp = self.get(f"/scenarios/{scenario_id}/blueprint")
    # Try both known response shapes
    return (
        resp.get("response", {}).get("blueprint")
        or resp.get("blueprint")
        or resp
    )
```

---

### P1 — Feature gaps that force manual workarounds

**1. No `connections list` command**

Added this session in `connections.py`. Exposes real integer IDs so users can pass
them via `--connection APP:ID` to `scenario draft`.

Still missing: `connections get <id>` and `connections test <id>` (verify a
connection is still valid before deploying a scenario that depends on it).

---

**2. `scenario draft` doesn't auto-resolve connections**

Current flow requires the user to:
1. Run `boost connections list` to find the ID
2. Manually pass `--connection openai-gpt-3:108535` to `boost scenario draft`

What it should do:

```
boost scenario draft --goal "..." --trigger schedule
```

...and the CLI auto-queries `/connections`, matches app names in the generated
modules to connection names, picks the first valid match, and wires up `__IMTCONN__`
automatically.

Implementation location: `scenario_builder.py`, `scenario_draft()`.

```python
# After goal/spec parsing, before build_draft():
with APIClient(config) as client:
    conn_resp = client.list_connections(team_id=resolved_team_id)
    conn_list = conn_resp.get("connections", [])

auto_connections: dict[str, int] = {}
for c in conn_list:
    app = c.get("accountType") or c.get("name") or ""
    cid = c.get("id")
    if app and cid and app not in auto_connections:
        auto_connections[app] = int(cid)

# Merge: explicit --connection flags take priority over auto-resolved
merged_connections = {**auto_connections, **connections}
draft = build_draft(goal, sources, trigger=trigger, connections=merged_connections)
```

---

**3. No native Instagram module — no workaround surfaced**

There is no `instagram-for-business:CreatePost` module in this tenant (or in most
Make/Boost.space tenants). The only path is the Instagram Graph API via HTTP.

The current implementation uses `http:ActionSendData` correctly. What it lacks is
a clear user-facing explanation and a config surface for the 3 required values.

Proposed: add a `boost scenario setup instagram` sub-command that walks the user
through getting their IG User ID and access token interactively, stores them in the
config file (encrypted via keyring), and substitutes them automatically when
deploying Instagram scenarios.

---

**4. `scenario brainstorm` triggers interactive prompts when `--non-interactive` is not passed**

File: `scenario_builder.py`, `scenario_brainstorm()`

`--trigger` is a required prompt. If the user runs it without `--non-interactive`,
it blocks the terminal waiting for input, then aborts (Aborted!) on Enter.

Fix: change the prompt to have a default:

```python
@click.option("--trigger", default="webhook", prompt="Trigger source", show_default=True)
```

Or just make it non-interactive by default with a `--interactive` flag to opt in.

---

**5. `scenario modules` scans blueprints via `get_blueprint()` which has the broken path (see P0.3)**

Same root cause as P0.3. Modules list always returns empty when the blueprint
response shape doesn't match. The fix is the same: normalise `get_blueprint()` in
`client.py`.

---

**6. `scheduling` type values are case-sensitive but not validated client-side**

The API accepts `indefinitely` (lowercase). The CLI passes whatever the user
gives or the `scheduling` dict in the blueprint metadata specifies. Blueprint
drafts generated by `build_draft()` can write `"INDEFINITELY"` (from old metadata)
and silently fail on deploy.

Fix in `scenario_builder_core.py`:

```python
# In build_draft() and repair_blueprint_data()
sched = blueprint.get("metadata", {}).get("scenario", {}).get("scheduling", {})
if isinstance(sched.get("type"), str):
    sched["type"] = sched["type"].lower()
```

Also fix in `deploy` command: normalise scheduling type before API call.

---

### P2 — Developer experience / maintainability

**1. `scenario_builder_core.py` uses keyword-matching strings for module selection**

`guess_modules()` does `if "instagram" in g`, `if "sheet" in g` etc.
This is fragile. A goal like "extract data from a spreadsheet" won't match `"sheet"`.

Proposed: replace with a weighted intent classifier. A minimal version maps
keyword lists to app names:

```python
INTENT_PATTERNS: list[tuple[list[str], str]] = [
    (["sheet", "spreadsheet", "google sheet", "gsheet"], "google-sheets"),
    (["slack", "channel message"], "slack"),
    (["hubspot", "crm", "contact"], "hubspot"),
    (["instagram", "ig post", "social media post"], "instagram"),
    (["openai", "gpt", "ai post", "ai-written", "generate", "write with ai"], "openai-gpt-3"),
    (["email", "gmail", "send email"], "google-email"),
    (["telegram"], "telegram"),
    (["whatsapp"], "whatsapp-business-cloud"),
]
```

Map each matched app to its builder function. This separates intent detection
from module construction and makes both testable in isolation.

---

**2. No tests for `connections.py`, `guess_modules()` with connections, or the deploy path**

Current test coverage:
- `test_scenario_builder_core.py` — tests validate/repair, NOT guess_modules
- `test_cli_json_contract.py` — tests JSON envelope shape only
- `test_client_errors.py` — tests error hint strings

Missing tests:
- `guess_modules()` with `trigger="schedule"` — should produce no trigger module
- `guess_modules()` with `connections={"openai-gpt-3": 42}` — `__IMTCONN__` should be int 42
- `connections list` command output shape
- `scenarios create` always sends `scheduling`
- `get_blueprint()` normalises both response shapes

---

**3. `client.py` has no retry logic**

All requests timeout at 30s with no retry. Any transient 429 or 503 drops the
command. Add exponential backoff for 429/503:

```python
# client.py
import time

def _request(self, method, path, retries=3, **kwargs):
    for attempt in range(retries):
        response = self._client.request(method, path, **kwargs)
        if response.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        break
    ...
```

---

**4. `scenario_builder.py` is 614 lines — approaching the 300-line limit**

Split into:
- `scenario_builder.py` — click commands only (no logic)
- `scenario_builder_core.py` — pure functions (already exists)
- `scenario_deploy.py` — deploy command + preflight checks (the heaviest part)

---

## Fix Sequence

Work through issues in this order. Each item is independently deployable.

```
Phase 1 — Stop the bleeding (P0)
  1. Fix get_blueprint() response path in client.py
  2. Always pass scheduling in scenarios create
  3. Add regression tests for both

Phase 2 — Connection wiring (P1.1, P1.2)
  4. connections get + connections test commands
  5. Auto-resolve connections in scenario draft
  6. Add tests: auto-resolve selects first matching connection by app name

Phase 3 — Deploy reliability (P1.3–P1.6)
  7. Fix scheduling type normalisation (lowercase)
  8. Fix brainstorm interactive prompt default
  9. Add boost scenario setup instagram (interactive credential wizard)

Phase 4 — Maintainability (P2)
  10. Replace keyword matching with INTENT_PATTERNS in guess_modules()
  11. Split scenario_builder.py → scenario_deploy.py
  12. Add retry logic to client.py
  13. Fill test coverage gaps
```

---

## Quick Reference: API Gotchas Discovered

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `22P02 invalid_text_representation` | `__IMTCONN__` sent as string, API expects int | Pass integer connection ID |
| `SC400 Missing scheduling` | scheduling param required even for on-demand | Always pass `{"type": "on-demand"}` minimum |
| `IM307 Unprocessable Entity` | scheduling type was uppercase `"INDEFINITELY"` | Use lowercase `"indefinitely"` |
| `IM007 Invalid blueprint/module` | modules list empty because `get_blueprint()` uses wrong response path | Normalise response extraction in `client.py` |
| `scenario modules` returns empty | Same `get_blueprint()` path issue | Same fix |
| deploy blocked on "unproven modules" | All modules unproven because known set is empty | Fix `get_blueprint()` first, then this self-heals |
