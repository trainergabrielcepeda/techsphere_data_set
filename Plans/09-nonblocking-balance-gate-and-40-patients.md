# 09 — Non-blocking label-balance gate + scale to 40 patients

**Status:** approved
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** Plans 07/08 (small-batch run, executed — 10 patients, Anthropic provider,
480/480 real calls succeeded, `publish_gold` blocked on the §12 label-balance check:
verde=82.5%, amarillo=17.5%, rojo=0%, real data already sitting unpublished in
`postop_dataset_dev`).

## What changed and why

The stated goal shifted: this dataset now needs to **feed a posterior model**, so
blocking publication over label balance at small sample sizes works against the actual
need — real (if imbalanced) data beats no data. Two changes:

1. **The label-balance check (§12 rule 2) stops blocking publication.** Chosen approach —
   your "tag it with an alert" option, not bare removal — because silently deleting the
   check throws away a real signal a model trainer needs (class imbalance matters for
   training even if it shouldn't block getting the data). The check still runs, still
   computes the same `[5%, 75%]` band from Plan 07, but a failure now writes a row to a
   new `silver.alertas_calidad` table instead of raising and aborting.
2. **Scale from 10 to 40 patients**, to get more archetype diversity (10 patients drew
   5 `recuperacion_normal` / 5 `complicacion_leve_vigilancia` / 0 `complicacion_real` —
   plausible at n=10, less likely to stay at 0% with more draws, though not guaranteed).

## Design — non-blocking balance check

**One behavior I'm preserving, worth flagging explicitly:** `check_casos_clinicos_
etiquetados` currently does two different things — flags a completely empty table, and
flags label imbalance. Making the *whole* function's output advisory would mean an
entirely empty `casos_clinicos_etiquetados` table (a real upstream failure, not a
distribution nuance) would also stop blocking — that's not what "tag the imbalance" should
mean. So this plan splits it into two functions:

- **`check_casos_clinicos_etiquetados_no_vacio(rows)`** — the empty-table case, **stays
  blocking**.
- **`check_casos_clinicos_etiquetados_balance(rows)`** — the `[5%, 75%]` label-balance
  check (renamed from today's `check_casos_clinicos_etiquetados`, same logic and band,
  unchanged from Plan 07) — **becomes advisory**.

`run_quality_expectations` changes from returning `bool` to `tuple[bool, list[str]]`
(`ok_para_publicar`, `alertas_no_bloqueantes`). The other four checks (`perfiles_pacientes_
co`, `dialogos_capa1_limpia`, `noise_mapping_log`, `dialogos_capa3_limite`) are untouched —
still blocking, still abort `publish_gold` on failure.

`main()` changes to: if `not ok_para_publicar` → still raise and abort (unchanged
behavior for real failures). If `alertas_no_bloqueantes` is non-empty → write them to
`silver.alertas_calidad` via a new `write_quality_alerts()`, then proceed to
`apply_grants`/`publish_gold_views` as normal.

**New table, `silver.alertas_calidad`** (new DDL file `sql/ddl/14_alertas_calidad.sql`,
positioned with the other silver base tables; new `schemas.ALERTAS_CALIDAD_SCHEMA`):

| Column | Type | Notes |
|---|---|---|
| `alerta_id` | STRING | PK |
| `check_nombre` | STRING | which §12 expectation raised this |
| `detalle` | STRING | same message text the log already prints today |
| `severidad` | STRING | `'advertencia'` — only value today; critical checks still block and never reach this table |
| `catalog_run` | STRING | which catalog/run produced it |
| `generado_ts` | TIMESTAMP | |

Written via `spark.createDataFrame(...).write.format("delta").mode("append")` — an
append-only audit log across runs, not an upserted "current state" table, since each run's
alerts are a record of that run, not a single mutable status.

**Visibility — the actual "tagging" part.** `silver.alertas_calidad` would otherwise be
invisible to participants (the existing `REVOKE SELECT ON SCHEMA postop_dataset.silver
FROM account users` in `sql/ddl/30_publish_gold_grants.sql` hides all of silver by
default). Adding an explicit per-table grant — the same pattern `apply_grants()` already
uses for the committee's access to `silver.dialogos_capa3_limite` — makes this one table
visible to everyone who can see `gold_participantes`, without exposing the rest of silver:

```sql
GRANT USE SCHEMA ON SCHEMA postop_dataset.silver TO `account users`;
GRANT SELECT ON TABLE postop_dataset.silver.alertas_calidad TO `account users`;
```

## Design — scale to 40 patients

Checked the actual generation code rather than assuming this "just works":

- `generate_synthea_profiles.py`: `paciente_id = f"pac_{seed}_{i:05d}"` — deterministic
  per `(seed, index)`, independent of total `n_pacientes`. Patients 0–9 get *identical*
  IDs/content whether `n_pacientes` is 10 or 40.
- `simulate_postop_trajectories.py`: `trayectoria_id = f"tray_{paciente_id}_{dia_postop}"`
  — same determinism, inherited from `paciente_id`.
- `classify_ground_truth.py`: `caso_id = f"caso_{trayectoria_id}"` — same again.
- All four upstream tables write with `mode("overwrite")` (full replace each run), so
  after re-running with `n_pacientes=40`, every upstream silver table correctly ends up
  with exactly the right 40-patient/160-caso content — patients 0–9 unchanged in content,
  patients 10–39 newly added.
- **The payoff:** `simulate_dual_llm`'s existing resume/skip logic (`_casos_pendientes`,
  Plan 06) checks which `caso_id`s already exist in `output_table`
  (`dialogos_capa1_limpia`). Since patients 0–9's `caso_id`s are unchanged, the 40 casos
  already generated in the completed 10-patient run are correctly recognized as
  already-done and **skipped** — only the 120 new casos (30 new patients × 4 `call_days`)
  actually hit the LLM. Not a guess: this follows directly from the deterministic-ID +
  overwrite pattern confirmed above, the same mechanism Plan 06 built for exactly this
  kind of incremental continuation.

**Real cost, from the actual 10-patient run's measured tokens** (8,770 prompt + 1,469
completion tokens/conversation average): 120 new conversations → ≈1.05M prompt + ≈176K
completion tokens → **≈$3.87 additional** (Sonnet 5 intro pricing) on top of the $1.29
already spent → **≈$5.16 total** for the full 40-patient dataset. Matches a from-scratch
40-patient estimate almost exactly, which is the expected sanity check — the resume/skip
logic saves wall-clock time (only 120 new conversations to run, not 160) and avoids
wasteful re-spend, not total dollars (the first 10 patients' cost is already sunk either
way).

**Wall-clock:** the 10-patient run's `simulate_dual_llm` task took the bulk of a ~28-minute
total run. 120 new conversations (1,440 calls, 3x the prior run's *new* work) suggests
roughly 60–75 minutes for that task alone, ~70–85 minutes total — a longer background run,
not a blocker.

- `databricks.yml`: `pilot_n_pacientes` default `"10"` → `"40"`.

## Prerequisite — apply the new DDL to the real catalog

`sql/ddl/00`–`23` were applied manually once in Plan 06 Phase 2 (`publish_gold.py` never
runs them itself — only `30_publish_gold_grants.sql` executes automatically at runtime).
The new `14_alertas_calidad.sql` needs the same one-time manual application against
`postop_dataset_dev` before `publish_gold` can write to it. I'll do this via the SQL
Statement Execution API, same method as Plan 06 Phase 2 and this session's earlier
queries.

## Testing approach

- Existing tests referencing `check_casos_clinicos_etiquetados` get renamed to
  `check_casos_clinicos_etiquetados_balance` (4 tests: pass-balanced, detects-underrepr,
  the two Plan 07 band-boundary tests) — same assertions, same band, just the new name.
- New test for `check_casos_clinicos_etiquetados_no_vacio`: empty rows → one problem;
  non-empty rows → `[]` (regardless of balance — that's the other function's job now).
- New tests for a pure `_build_alertas_rows(alertas, catalog, run_ts) -> list[dict]`
  helper (extracted from `write_quality_alerts` so it's unit-testable without Spark, same
  pattern as `_casos_pendientes`): one row per alert message, unique `alerta_id`s, empty
  list in → empty list out.
- `run_quality_expectations`/`write_quality_alerts` themselves stay untested directly
  (need a real `spark` — same pre-existing limitation as every other Spark-touching
  function in this file).

## Explicitly out of scope

- Changing the `[5%, 75%]` band itself — only the *enforcement* (blocking → advisory)
  changes; the threshold stays what Plan 07 set.
- Re-litigating provider/model choice — stays Anthropic/`claude-sonnet-5`, unchanged from
  Plan 08.
- Any change to `max_tokens`/`effort` settings — unchanged from Plan 08 (`500`/`"low"`),
  already validated against real data in the 10-patient run.
- Retroactively "fixing" the already-published... — nothing published yet; the 10-patient
  run's data is still sitting unpublished in silver tables, and this plan's run will
  supersede it (overwrite semantics) as part of reaching 40 patients.

## Risks

- **The empty-table/balance split is a real behavior change**, not just a rename — worth
  double-checking on review that "empty table still blocks, imbalance doesn't" is actually
  the line you want drawn, not something coarser or finer.
- **Real spend:** ≈$3.87 additional (Anthropic, pay-per-token) for the 30 new patients.
- **Still no guarantee of a better label mix at n=40** — more archetype draws makes 0%
  `rojo` less likely but doesn't eliminate the possibility; if it happens again, that's
  now just an alert row, not a blocker, per this plan's whole point.

## Verification

- `pytest -q` green after implementation.
- DDL application confirmed via `SHOW TABLES`/`DESCRIBE` against the real catalog before
  running the job.
- After the run: confirm `silver.alertas_calidad` has real rows (if the balance is still
  out of band), confirm `gold_participantes.dataset_final`/`gold_comite.dataset_final_
  completo` actually published this time (unlike the last two runs), and confirm the real
  label distribution and token/cost totals from the deployed tables, not estimated.
