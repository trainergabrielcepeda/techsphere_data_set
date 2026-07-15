# 04 — Run the deployed job, then destroy the bundle

**Status:** awaiting approval
**Author:** Claude, for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `Plans/03-test-bundle-deployment-to-workspace.md` (bundle deployed,
`postop_pipeline_dev` job registered, job ID `784301521213099`).

## Goal

Run the deployed `postop_pipeline` job in the `dev` target on real serverless compute,
then tear the bundle down (`databricks bundle destroy -t dev`), and report the results.

## Why this needs its own approval

Plan 03 explicitly scoped this out:

> **No `databricks bundle run postop_pipeline -t dev`.** That would execute all 7 tasks
> on serverless compute, attempt real writes to a catalog that doesn't exist yet, and
> hit stub code — real compute spend for no useful signal. Would need its own
> plan/approval once the catalog DDL and at least the early pipeline stubs are real.

Nothing has changed since then:

- All 7 scripts in `src/postop/*.py` are still stubs (confirmed just now — each contains
  a "stub de scaffolding (Plan 01) — sin lógica de generación aún" docstring, no
  generation/write logic).
- `sql/ddl/00_catalog_schemas.sql` has **not** been executed against the workspace, so
  the `postop_dataset_dev` catalog/schemas the job would write to don't exist yet.

## Expected outcome

**The run will almost certainly fail**, likely on the first task
(`generate_synthea_profiles`) or on whichever early task tries to reference the
nonexistent catalog/schema. This is expected, not a bug to fix mid-run. Given that, this
plan is a "confirm it fails the way we expect, and capture the exact error" exercise,
not a real data-generation run.

## Steps

1. `databricks bundle run postop_pipeline -t dev --profile default` — trigger the job,
   wait for it to reach a terminal state (success/failure). This spends real serverless
   compute for however long the tasks run before failing.
2. Pull the run result/status (`databricks bundle summary` job URL, or
   `databricks jobs get-run <run-id>` / task-level error) so I can report which task
   failed and why.
3. `databricks bundle destroy -t dev --profile default` — tear down the bundle: deletes
   the `postop_pipeline_dev` job definition and the bundle-managed workspace folder
   (`/Workspace/Users/cartmangabriel@gmail.com/.bundle/postop_dataset/dev`). This is the
   destructive step — irreversible via the CLI (bundle would need to be redeployed from
   scratch, which is cheap, but any run history/logs tied to the job go away once
   deleted).
4. Report back: run outcome (task-by-task pass/fail), the specific error captured, and
   confirmation the destroy completed.

## Explicitly out of scope for this plan

- **No fixing the stub code or writing the catalog DDL** to make the run succeed. If you
  want a real, meaningful pipeline run, that's a future plan once Plan 01/02's stubs are
  filled in and `sql/ddl/00_catalog_schemas.sql` has been applied.
- **No `prod` target** — `dev` only.

## Risks / things to confirm with you before I run this

- Real compute spend on Databricks Free Edition serverless for a run that's expected to
  fail early — should be minimal given it'll fail fast, but flagging since it's real
  usage against your account.
- `bundle destroy` is a destructive, hard-to-reverse action against shared workspace
  state (removes the job + bundle folder). Confirming you want the teardown to happen
  automatically right after the run, in the same pass, rather than pausing for a
  separate go-ahead once you see the run result.

## Verification

- Job run reaches a terminal state (`FAILED` expected, or `SUCCESS` if stubs
  surprisingly no-op cleanly) and I can quote the task-level error.
- `databricks bundle destroy -t dev` exits 0, and a follow-up `bundle summary` shows no
  deployed resources.
