# Monthly Timesheet Automation Runbook

This package uses two scenarios:

1. `examples/monthly-timesheet-provisioning.json`
2. `examples/monthly-timesheet-consolidation-finance.json`

## Architecture

Primary path:

1. Scheduler runs month-end provisioning scenario.
2. One sheet is created from template per lead.
3. Lead-only permission is applied and lead is notified.
4. Tracker row is created (`sent`, with sheet URL).
5. Consolidation scenario watches tracker updates.
6. Once all leads are `submitted`, consolidated sheet is updated.
7. Manager approves; finance webhook is called.
8. Tracker status is updated to `finance_verified` / `invoiced`.

Fallback path:

1. If not all leads submitted by cutoff, send reminder and keep status `pending`.

Error path:

1. On API or permission failure, write `error` status in tracker and notify ops channel.

## Required Control Sheets

Create one control spreadsheet with these tabs:

- `lead_registry`: `project_id`, `lead_id`, `lead_name`, `lead_email`, `lead_slack_channel_or_user`, `active`
- `tracker`: `project_id`, `lead_id`, `lead_email`, `billing_month`, `template_version`, `sheet_id`, `sheet_url`, `status`, `submitted_at`, `approved_at`, `finance_ticket_id`
- `template_versions`: `template_version`, `template_sheet_id`, `header_map_json`, `active_from_month`, `is_active`

## Deploy Steps

From repository root:

```bash
python -m boostspace_cli.cli scenario validate --file examples/monthly-timesheet-provisioning.json --json
python -m boostspace_cli.cli scenario validate --file examples/monthly-timesheet-consolidation-finance.json --json

python -m boostspace_cli.cli scenario deploy --file examples/monthly-timesheet-provisioning.json --dry-run --json
python -m boostspace_cli.cli scenario deploy --file examples/monthly-timesheet-consolidation-finance.json --dry-run --json

python -m boostspace_cli.cli scenario deploy --file examples/monthly-timesheet-provisioning.json --json
python -m boostspace_cli.cli scenario deploy --file examples/monthly-timesheet-consolidation-finance.json --json
```

After deploy in Boost UI:

- Set scenario 1 to monthly schedule (last day, local timezone).
- Keep scenario 2 active for continuous watch on tracker updates.
- Add filters:
  - before consolidation: all leads submitted for current month
  - before finance webhook: manager approval equals `approved`

## Test Checklist (UAT)

1. Trigger provisioning for a test month and verify one sheet per lead.
2. Verify Lead A cannot access Lead B sheet.
3. Mark all 5 lead rows as submitted and verify consolidation runs once.
4. Verify manager approval gate blocks finance call until approved.
5. Verify finance webhook returns success and tracker status updates.
6. Re-run same month and verify no duplicate rows/sheets (idempotency key by `project_id+lead_id+month`).

## Template Change Procedure

When template changes next month:

1. Copy the new template sheet and record its ID.
2. Add a new row to `template_versions` with incremented `template_version`.
3. Update `header_map_json` only for changed columns.
4. Set `active_from_month` for cutover month.
5. Keep old version rows for historical reruns.
6. Run dry-run deploy and one test execution before month-end.

This keeps old months reproducible while allowing future template changes safely.
