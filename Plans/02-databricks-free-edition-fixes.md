# 02 — Databricks Free Edition fixes

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `Plans/01-scaffold-databricks-asset-bundle.md` (already scaffolded) and
[Databricks Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations)

## Goal

Plan 01 scaffolded the bundle assuming a normal (paid) Databricks workspace with classic
clusters, Unity Catalog groups, and unrestricted egress. The target deployment is
**Databricks Free Edition**, which has hard constraints that break several pieces of that
scaffold. This plan fixes the scaffold in place — same structure, same stub depth, no
pipeline logic added — so it actually deploys on Free Edition.

## Why the current scaffold won't deploy

Confirmed against the current Free Edition docs:

1. **Serverless compute only — no classic clusters.** "Custom compute configurations are
   not supported." `resources/postop_pipeline.job.yml` currently defines two
   `job_clusters` entries (`new_cluster` with `spark_version`, `node_type_id`,
   `autoscale`/`num_workers`, `custom_tags`). None of that is valid on Free Edition —
   `databricks bundle deploy` will fail validation or the job will fail at runtime.
2. **No account console, no SSO/SCIM.** Free Edition has no group management. The
   `prod` target's `run_as: group_name: comite_academico` in `databricks.yml`, and the
   `GRANT ... TO \`equipos_participantes\`` / `\`comite_academico\`` statements in
   `sql/ddl/30_publish_gold_grants.sql`, all reference Unity Catalog groups that cannot
   be created on Free Edition.
3. **Restricted egress — "a limited set of trusted domains."** `simulate_dual_llm`'s
   external-API path (the `anthropic` SDK calling `api.anthropic.com` directly from a
   job) is the design's fallback for Componente 4 (§8.2). This is now the riskier of
   the two options, not a safe fallback — outbound calls to arbitrary domains may be
   blocked. Databricks Model Serving (`ai_query()`, entirely intra-workspace) becomes
   the primary path, not an equal alternative.
4. **Max 5 concurrent job tasks per account.** Not a code change, but worth confirming:
   the current DAG is fully linear (each task `depends_on` the previous one), so at
   most 1 task runs at a time. Already compliant — noted so nobody "fixes" this later
   by parallelizing tasks without re-checking the limit.
5. **One workspace, one metastore per account.** The `dev`/`prod` split in
   `databricks.yml` still works (two catalogs in one metastore), but it no longer means
   "two separate workspaces" the way the design doc's wording might imply — both
   targets deploy to the *same* Free Edition workspace. Worth a one-line clarifying
   comment so this isn't assumed away later.

Not affected (verified, no change needed): Unity Catalog catalog/schema/volume creation
(`sql/ddl/00_catalog_schemas.sql`) — the volume has no external storage location, so it
uses Free Edition's managed storage and is fine as-is. Databricks-backed secret scopes
are not called out as unsupported, so `llm_secret_scope` stays.

## Changes

### 1. `resources/postop_pipeline.job.yml` — drop classic clusters, go serverless

- Remove the `job_clusters` block entirely (`single_node_synthea`, `standard_autoscale`).
- Remove `job_cluster_key` from every task.
- Add a job-level `environments` block (serverless environment spec) so the packages
  Componente 1/2/4 need (`pysynthea`, `Faker`, `databricks-sdk`, `anthropic`) are
  present — serverless has no cluster-installed libraries, dependencies must be
  declared per environment and referenced from each task via `environment_key`.
- Update the header comment: replace the "single-node vs. autoscale cluster" narrative
  (§11's classic-cluster assumption) with a note that Free Edition forces serverless
  for all tasks, and that this is a documented deviation from §11's literal wording,
  not an oversight.

### 2. `databricks.yml` — drop group-based `run_as`

- Remove `run_as: group_name: comite_academico` from the `prod` target. Free Edition
  has no group management, so this would fail deploy. Leave `prod` running as the
  deploying user (bundle default) and add a comment explaining why, pointing at the
  same limitation.
- Add a short comment on the `targets` block noting both `dev` and `prod` resolve to
  the same Free Edition workspace (one workspace/account), only the catalog differs.

### 3. `sql/ddl/30_publish_gold_grants.sql` — drop named groups

- Replace `GRANT ... TO \`equipos_participantes\`` with `GRANT ... TO \`account users\``
  (Unity Catalog's built-in principal for every user in the metastore) for
  `gold_participantes`.
- Replace `\`comite_academico\`` with explicit user emails read from
  `conf/project.yml` (new `governance.committee_emails` list) for `gold_comite`, since
  there's no group to grant to.
- Keep the `REVOKE` statements (still needed to keep `silver`/`gold_comite` hidden from
  everyone else) — just update the principal names to match.
- Add a header comment documenting that this is a Free-Edition-specific substitute for
  the design's group-based grants (§4, §16), and that a real (paid) workspace should
  revert to named groups.

### 4. `conf/project.yml` — governance section

- Replace `governance.participant_group` / `governance.committee_group` with
  `governance.committee_emails: []` (placeholder list, filled in per cohort) since
  participants are now covered by `account users` and the committee is enumerated by
  email instead of by group.

### 5. `src/postop/simulate_dual_llm.py` — re-rank the two orchestration paths

- No logic changes (still a stub), but update the module docstring and `main()`
  argparse help text to state that Databricks Model Serving (`ai_query()`) is the
  primary path on Free Edition because of the egress restriction, and that the
  external-API-via-secret path is a fallback to validate in a spike before relying on
  it (mirrors how Plan 01 already flags risk R1 for PySynthea — this becomes risk R5).

### 6. `Plans/01-scaffold-databricks-asset-bundle.md` — leave as-is

- No edits to the historical plan file itself; this plan supersedes the
  Free-Edition-incompatible parts of it. (Flagging in case you'd rather I add a
  "superseded by Plan 02" note at the top of Plan 01 — can add if you want it.)

## Explicitly out of scope for this plan

- Still no pipeline logic in any `src/postop/*` module — pure scaffold fix.
- Still no actual `databricks bundle deploy` run (no credentials in this environment).
- Not validating whether `api.anthropic.com` is actually on Free Edition's trusted-domain
  allowlist — that's the spike mentioned in risk R5, to run once there's a real
  workspace to test against.

## Verification

- `databricks bundle validate -t dev` (when run against a real Free Edition workspace)
  should no longer error on cluster fields or group `run_as`.
- Manual read-through: no remaining references to `job_clusters`, `node_type_id`,
  `autoscale`, or named UC groups anywhere in `resources/`, `databricks.yml`, or
  `sql/ddl/`.
- `pytest -q` still passes (these changes don't touch Python stub signatures except
  docstrings/help text in `simulate_dual_llm.py`).
