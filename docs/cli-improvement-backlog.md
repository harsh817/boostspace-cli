# CLI Improvement Backlog

This backlog captures concrete improvements discovered while building and deploying the monthly timesheet automation in Boost.

## Priority 1

### 1. Make dry-run reflect live deploy reality

Problem:
- `scenario deploy --dry-run` reported success for blueprints that failed on live create with `IM007`.
- This creates false confidence and slows debugging.

Observed examples:
- Module exists in offline catalog but not in tenant runtime.
- Connection is auto-wired by app alias, but the account is not actually compatible with the module.

Relevant files:
- `src/boostspace_cli/scenario_builder.py:1508`
- `src/boostspace_cli/client.py:182`

Suggested change:
- Add a `preflight_live_compatibility()` step before dry-run success is returned.
- For every module in the blueprint:
  - verify the module exists in tenant runtime
  - verify the selected connection is accepted for that module
- Return a structured failure if any module/connection pair is invalid.

Suggested output:
```json
{
  "ok": false,
  "error": "Live compatibility check failed",
  "data": {
    "module": "google-sheets:addRow",
    "connectionId": 164145,
    "reason": "Provided account is not compatible with module"
  }
}
```

### 2. Surface raw `IM007` details in normal CLI output

Problem:
- `IM007` is currently summarized too generically.
- The raw API payload contained the actual fix path.

Observed examples:
- `Provided account '164145' is not compatible with 'google-sheets:addRow' module.`
- `Module not found 'google-drive:copyAFile' version '1'.`

Relevant files:
- `src/boostspace_cli/client.py:31`

Suggested change:
- Preserve and print raw `detail` when available.
- If `detail` is a string, include it in the error message.
- If `detail` is a dict, include key fields like `detail`, `message`, `suberrors[0]`.

Suggested result:
- `boost scenario deploy` should directly print the tenant-reported cause without requiring raw manual API inspection.

### 3. Replace alias-based connection matching with module-compatibility matching

Problem:
- Auto-wiring currently relies too much on aliases like `google`, `google-restricted`, `google-sheets`, `google-drive`.
- Those aliases were not sufficient to determine real module compatibility.

Relevant files:
- `src/boostspace_cli/scenario_builder_helpers.py:240`

Suggested change:
- Introduce a compatibility cache:
  - key: module id
  - value: list of compatible connection ids discovered from tenant or deployment probes
- Auto-wire by module compatibility first, alias second.

Suggested command:
```bash
boost connections compat google-sheets:addRow
```

Suggested output:
```json
{
  "module": "google-sheets:addRow",
  "compatibleConnections": [147240],
  "incompatibleConnections": [164145, 148313]
}
```

### 4. Unify blueprint extraction in all commands

Problem:
- `scenario deploy` accepts draft wrapper files containing `goal` + `blueprint`.
- `blueprints import` and `blueprints update` rejected the same files because they expected raw blueprint only.

Relevant files:
- `src/boostspace_cli/blueprints.py:82`
- `src/boostspace_cli/blueprints.py:235`
- `src/boostspace_cli/scenario_builder_core.py` or wherever `extract_blueprint()` lives

Suggested change:
- Use the same `extract_blueprint()` helper in:
  - `blueprints import`
  - `blueprints update`
  - `blueprints validate`

Benefit:
- Users can pass either raw blueprints or draft wrapper files consistently.

## Priority 2

### 5. Distinguish offline catalog knowledge from tenant runtime knowledge

Problem:
- The local catalog claimed modules existed, but the tenant runtime rejected them.

Relevant files:
- `src/boostspace_cli/data/module_registry.json`
- `src/boostspace_cli/catalog_cli.py`

Suggested change:
- Split module metadata into three states:
  - `catalog_known`
  - `tenant_seen`
  - `tenant_deployable`
- Expose this in `scenario modules` and `catalog module` output.

Suggested output:
```json
{
  "id": "google-drive:copyAFile",
  "catalogKnown": true,
  "tenantSeen": false,
  "tenantDeployable": false
}
```

### 6. Improve external binary resolution on Windows

Problem:
- External commands like `gws` and `gcloud` failed when only `.cmd` executables were present.

Relevant files:
- `src/boostspace_cli/gws.py`

Suggested change:
- Centralize a helper like `resolve_executable(name)` that checks:
  - `name`
  - `name.cmd`
  - common Windows install paths
- Reuse it anywhere the CLI shells out to external tools.

### 7. Make automation-friendly guidance more obvious for interactive commands

Problem:
- Commands like `scenarios delete` silently prompt unless `--yes` is used.
- This is correct behavior, but the CLI should be more explicit when run in automation contexts.

Relevant files:
- `src/boostspace_cli/scenarios.py`

Suggested change:
- On prompt abort, print a follow-up hint:
  - `Retry with --yes for non-interactive use.`

## Priority 3

### 8. Add verbose connection metadata

Problem:
- We could list connections, but not see enough about what scopes/module families each one supports.

Relevant files:
- `src/boostspace_cli/connections.py`

Suggested change:
- Add `connections list --verbose` to include:
  - provider/app family
  - inferred scope family
  - last compatibility result by module family
  - whether it is preferred for Sheets/Drive/Email

### 9. Add a direct live probe command

Problem:
- Manual raw API probing was the fastest way to diagnose real deploy issues.
- The CLI should expose this intentionally.

Suggested command:
```bash
boost scenario probe --file blueprint.json --module google-sheets:addRow --connection 147240 --json
```

Expected behavior:
- Performs a minimal create/update validation against tenant runtime.
- Returns the actual compatibility/error result without requiring a full deploy.

## Recommended Implementation Order

1. Dry-run/live compatibility validation
2. Raw `IM007` detail surfacing
3. Shared blueprint extraction across commands
4. Module-level connection compatibility mapping
5. Catalog runtime state separation
6. Windows executable resolution helper

## Notes From Timesheet Automation Work

- Native Google module deployment was the main friction point.
- The working production path used `code:ExecuteCode` because it was tenant-deployable and reliable.
- Better runtime compatibility checks in the CLI would likely have saved most of the debugging time.
