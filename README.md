# Boost.space CLI

CLI to manage Boost.space Integrator workflows from the terminal.

## Install

```bash
pip install -e .
```

## Quick Start (recommended)

```bash
# One-command setup: login + org/team detection + validation
boost init

# Verify health and auto-fix missing defaults
boost auth doctor --fix

# List scenarios
boost scenarios list --limit 20
```

## Authentication

```bash
# Session auth via browser automation (Playwright)
boost auth playwright

# Check auth status
boost auth status

# Clear auth data
boost auth clear
```

## Common Commands

```bash
# Who am I
boost whoami

# Scenario details
boost scenarios get 123456 --blueprint

# Trigger execution
boost executions run 123456 --data '{"email":"test@example.com"}'

# Execution history
boost executions history 123456 --limit 20

# Execution status (supports SCENARIO_ID:EXECUTION_ID shorthand)
boost executions status 123456:abc123

# Status by history imtId (explicit log lookup)
boost executions status --name "HM | Daily Report Leads" --from-history 145029
```

## Offline Catalog + Formulas

```bash
# Catalog metadata and integrity
boost catalog info
boost catalog doctor

# Search module registry offline
boost catalog search "instagram"
boost catalog module "instagram-business:CreatePostPhoto"

# Refresh cache from @make-org/apps (requires npm)
boost catalog refresh

# Pull template pattern signals from make.com templates page (supplemental source)
boost catalog templates --refresh
boost catalog templates --query instagram --limit 10

# Configure npm auth for private package access (prompts for token)
boost catalog auth --scope @make-org --registry https://registry.npmjs.org/

# Formula/function lookup and linting
boost formulas search date
boost formulas info formatDate
boost formulas lint --file draft-capture-lead-webhook-and-push-to-google-sheets.json
```

## Internet-First Scenario Builder

```bash
# One-command guided brainstorm + draft
boost scenario coach --goal "Capture lead webhook and push to Google Sheets" --json

# 0) Brainstorm interactively into a spec
boost scenario brainstorm --goal "Capture lead webhook and push to Google Sheets"

# 1) Research latest patterns from the web
boost scenario research --goal "Capture lead webhook and push to Google Sheets"

# 2) Generate a draft blueprint from spec (or use --goal directly)
boost scenario draft --spec spec-capture-lead-webhook-and-push-to-google-sheets.json

# (Optional) check native connection readiness from a draft
boost scenario setup --file draft-capture-lead-webhook-and-push-to-google-sheets.json

# 3) Validate structure + account readiness
boost scenario validate --file draft-capture-lead-webhook-and-push-to-google-sheets.json --check-auth

# 4) Auto-repair common blueprint issues
boost scenario repair --file draft-capture-lead-webhook-and-push-to-google-sheets.json

# 5) Preflight deploy (safe)
boost scenario deploy --file draft-capture-lead-webhook-and-push-to-google-sheets.json --dry-run

# 6) Deploy for real
boost scenario deploy --file draft-capture-lead-webhook-and-push-to-google-sheets.json

# 6b) Deploy with credentials + sample payload + verification run
boost scenario deploy --file draft-capture-lead-webhook-and-push-to-google-sheets.json \
  --credential API_TOKEN=... --sample-file sample.json --json

# If draft intentionally contains HTTP fallback modules, opt in explicitly
boost scenario deploy --file draft-capture-lead-webhook-and-push-to-google-sheets.json --allow-http-fallback

# 7) Check tenant-proven module names (deploy guard helper)
boost scenario modules --limit 60

# 8) Sync/list documented apps + platform features from Boost docs catalog
boost scenario catalog --refresh
```

JSON output examples:

```bash
boost whoami --json
boost auth status --json
boost scenarios list --limit 20 --json
boost scenarios health --json
boost scenarios top-issues --limit 10 --json
boost executions run --name "HM | Daily Report Leads" --json
boost executions status --name "HM | Daily Report Leads" --from-history 145029 --json
boost executions history --name "HM | Daily Report Leads" --json
boost executions incomplete --name "HM | Daily Report Leads" --json
boost webhooks list --json
boost scenario setup --file draft-capture-lead-webhook-and-push-to-google-sheets.json --json
boost scenario catalog --json
boost catalog info --json
boost catalog search instagram --json
boost catalog templates --query instagram --json
boost formulas search date --json
boost scenario deploy --file draft-capture-lead-webhook-and-push-to-google-sheets.json --sample-json '{"email":"qa@example.com"}' --json
```

JSON schema (all `--json` commands):

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "command": "scenarios list"
  }
}
```

`jq`-friendly automation examples:

```bash
# Extract scenario IDs and names
boost scenarios list --limit 20 --json | jq -r '.data[] | "\(.id)\t\(.name)"'

# Fail CI if doctor reports not ok
boost auth doctor --json | jq -e '.ok == true' > /dev/null

# Pull execution status text from structured JSON
boost executions status --name "HM | Daily Report Leads" --from-history 145029 --json | jq -r '.data.statusText'
```

Sample workflow file:

`examples/sample-workflow-lead-capture.json`
