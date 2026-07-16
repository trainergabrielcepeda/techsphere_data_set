# 11 — Fix stale README + commit Plan 09 (sync docs with code)

**Status:** awaiting approval
**Context:** follow-up to a repo audit (security / docs / lint / orphans). Two findings
to fix:

1. `README.md`'s "Estado" section and stack comment are stale — they describe the repo
   as an unimplemented scaffold, which hasn't been true for several commits.
2. `docs/generador-datos.md` (already committed in `2b4246b`) documents Plan 09 behavior
   (non-blocking label-balance gate, 40-patient default, `silver.alertas_calidad`), but
   the code implementing it is still uncommitted working-tree changes + untracked files.
   Docs and code are out of sync at HEAD until this is committed.

**⚠️ Open question before I touch anything:** `Plans/09-nonblocking-balance-gate-and-40-
patients.md` itself is headed "Status: awaiting approval." I don't have confirmation in
this conversation that you reviewed and approved that plan — the matching code changes
were already sitting in the working tree when I started the audit. Before I commit them
under your name, please confirm: **did you review Plan 09's diff (the non-blocking
balance gate + 40-patient scale-up, summarized in the audit) and want it committed as
described?** If not, tell me and I'll leave step 2 out of this plan.

## Step 1 — Fix `README.md`

- Rewrite the "## Estado" section (`README.md:22-29`) to reflect reality: 6 components
  implemented in `src/postop/`, 92 passing tests, real pilot runs executed against
  Databricks (per commit history), Plan 09 (balance gate + 40-patient scale) as the most
  recent change. Point to `docs/generador-datos.md` as the authoritative "as-implemented"
  reference, same as it already does elsewhere in the file.
- Fix the project-structure comment (`README.md:35`) — drop the stale `pysynthea`
  mention (`requirements.txt` itself documents it as replaced by the internal generator)
  and describe the actual stack (pyspark, delta-spark, Faker, databricks-sdk, anthropic).
- No code or behavior changes — documentation only.

## Step 2 — Commit the Plan 09 changes (contingent on your confirmation above)

Stage and commit exactly what's already in the working tree — no new code, just landing
what's there:

- Modified: `databricks.yml`, `sql/ddl/30_publish_gold_grants.sql`,
  `src/postop/publish_gold.py`, `src/postop/schemas.py`,
  `tests/test_publish_gold_expectations.py`
- New: `sql/ddl/14_alertas_calidad.sql`, `Plans/09-nonblocking-balance-gate-and-40-patients.md`

Before committing:
- Re-run `pytest -q` to confirm still green (was 92 passed as of the audit).
- Update `Plans/09-...md`'s status header from "awaiting approval" to "approved" (only
  if you confirm approval in Step 2's open question above).

Commit message will describe the actual change: label-balance check becomes a
non-blocking advisory (`silver.alertas_calidad`) instead of aborting publication, plus
scaling the pilot run from 10 to 40 patients.

## Step 3 — Commit the README fix

Separate commit from Step 2, since they're unrelated changes (docs cleanup vs. shipping
Plan 09) — keeps history readable if either needs to be reverted independently.

## What I will NOT do

- No push to any remote — commits stay local unless you separately ask for a push.
- No changes to the actual balance-gate logic, grants, or schema beyond what's already
  in the working tree (i.e. I'm not second-guessing Plan 09's design in this plan, just
  landing it as-is or leaving it out, per your answer above).
