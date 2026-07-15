# 03 — Test bundle deployment to the workspace

**Status:** awaiting approval
**Author:** Claude, for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `Plans/01-scaffold-databricks-asset-bundle.md`, `Plans/02-databricks-free-edition-fixes.md`
(scaffold + Free Edition fixes, both already applied to the repo). Plan 02 explicitly
deferred this step: *"no actual `databricks bundle deploy` run (no credentials in this
environment)"*. Credentials now exist (`databricks auth login`, profile `default`,
workspace `dbc-5dde2f73-7c6f.cloud.databricks.com`), so this plan closes that gap.

## Goal

Confirm the Databricks Asset Bundle (`databricks.yml` + `resources/postop_pipeline.job.yml`)
actually deploys to the real Free Edition workspace under the `dev` target — i.e. that the
Free Edition fixes from Plan 02 (serverless-only, no group `run_as`) hold up against the
live workspace, not just static review.

This is a deployment test, not a pipeline run: it verifies the bundle's shape is accepted
by the workspace. It does **not** execute the job. Every `src/postop/*.py` task script is
still a stub (Plan 01/02 — no generation logic yet, see `generate_synthea_profiles.py`
docstring: *"stub de scaffolding (Plan 01) — sin lógica de generación aún"*), and the
`postop_dataset_dev` catalog/schemas (`sql/ddl/00_catalog_schemas.sql`) have not been
created in this workspace yet. Running the job now would fail immediately and isn't useful
signal — that's a separate, later step.

## Steps

1. `databricks bundle validate -t dev --profile default` — static schema/reference
   validation. No workspace changes; safe to run freely.
2. `databricks bundle deploy -t dev --profile default` — uploads the bundle to the
   workspace and registers the `postop_pipeline_dev` job definition (per
   `name: postop_pipeline_${bundle.target}` in the job resource). This **does** create
   real state in the shared workspace:
   - A bundle-managed workspace folder under the deploying user
     (`/Workspace/Users/cartmangabriel@gmail.com/.bundle/postop_dataset/dev`, standard
     bundle layout).
   - A registered job named `postop_pipeline_dev`, visible to anyone with workspace
     access, using the serverless `postop_env` environment (pysynthea, Faker,
     databricks-sdk, anthropic).
3. `databricks bundle summary -t dev --profile default` — confirm what got deployed
   (job ID, workspace path) without triggering a run.
4. Report back: pass/fail of validate and deploy, and the resulting job URL/ID.

## Explicitly out of scope for this plan

- **No `databricks bundle run postop_pipeline -t dev`.** That would execute all 7 tasks
  on serverless compute, attempt real writes to a catalog that doesn't exist yet, and
  hit stub code — real compute spend for no useful signal. Would need its own
  plan/approval once the catalog DDL and at least the early pipeline stubs are real.
- **No running of `sql/ddl/*.sql`** (catalog/schema/volume creation). Not needed to test
  bundle deploy; in scope for a future "bootstrap the workspace" plan.
- **No `prod` target deploy.** Only `dev` (the bundle's default target) is tested here.
- **No teardown.** The deployed job stays in the workspace after this plan unless you
  ask me to run `databricks bundle destroy -t dev` afterward.

## Risks / things to confirm with you before I run this

- This creates a real, visible job in your Databricks workspace (reversible via
  `bundle destroy`, but not nothing — flagging per the "actions visible to others /
  affecting shared state" guidance).
- If `bundle validate` surfaces issues Plan 02 didn't anticipate (e.g. an
  `environments` field Free Edition rejects, or a variable resolution problem), I'll
  report the exact error rather than start editing files to fix it — that'd be a new
  change requiring its own plan.

## Verification

- `databricks bundle validate -t dev` exits 0.
- `databricks bundle deploy -t dev` exits 0 and `bundle summary` shows the
  `postop_pipeline_dev` job with a valid job ID.
