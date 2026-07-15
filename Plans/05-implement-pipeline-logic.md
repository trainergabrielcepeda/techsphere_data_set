# 05 — Implement pipeline logic (Free Edition-aware, Colombia-representative population)

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `specs/Diseño Técnico — Dataset Seguimiento Post-Operatorio.md` (Technical
Design), `Plans/01`–`04` (scaffold, Free Edition fixes, deploy test, run+destroy test —
all already applied; every `src/postop/*.py` module is still a stub with
`NotImplementedError`).

## Goal

Replace the stub bodies in `src/postop/*.py` and `notebooks/curate_edge_cases.py` with
real, testable logic for all 6 components of the Technical Design, adjusted for two
things the user asked for explicitly:

1. **Databricks Free Edition restrictions** (already characterized in Plan 02: serverless
   compute only, no classic clusters, no Unity Catalog groups, restricted egress).
2. **A dataset scoped to a significant population representative of Colombia** — not an
   unbounded or US-shaped sample.

This plan does **not** deploy or run anything against the real workspace (that stays
gated behind its own plan, per the Plan 03/04 pattern). It also does not execute a real
LLM call against a live endpoint — no endpoint exists yet. Verification here is local:
unit tests over the pure-Python business logic, run in an ephemeral local venv.

## Critical finding that changes Component 1 (read this first)

The Technical Design (§5.2) planned a spike to validate whether the `pysynthea` PyPI
package can generate patients for the 5 allowlisted modules before committing to it, with
a documented fallback (Synthea `.jar` via a Job Task of type JAR) if it couldn't.
I ran that spike now, before writing the rest of this plan, because it determines whether
Component 1 is even buildable as designed:

- `pysynthea` **does exist on PyPI** (`pysynthea==1.0.0`, published Nov 2025) — but it is
  **not a patient generator**. Its own README describes it as: *"a package to work with
  an example OMOP database generated using Synthea."* It downloads a **static,
  pre-generated** dataset (either a full DuckDB export from Zenodo, or a small ~3.3MB
  Eunomia dataset called `Synthea27Nj` — a fixed New Jersey/US cohort from
  `github.com/OHDSI/EunomiaDatasets`) and gives you an ATLAS-style **cohort-query DSL**
  (`ConceptSet`, `Inclusion_Criteria`, entry/exit events) to filter it. There is no
  module allowlist parameter, no seed parameter, and no way to generate a new patient —
  you can only query a fixed population that already exists, is US-shaped, and is not
  scoped to our 5 post-op procedures.
- The documented fallback (Synthea `.jar` as a Job Task of type JAR) is **also blocked**,
  independently, by the Free Edition constraint from Plan 02: Free Edition is
  serverless-only, and JAR-type tasks need a JVM cluster the same way classic clusters do.
  So both the primary and fallback paths from §5.2 are closed.

**Resolution:** implement Component 1 as a **self-contained deterministic synthetic
generator**, pure Python (no external Synthea/PySynthea runtime dependency), calibrated
against the same 5-module allowlist with literature-anchored parameters (age ranges,
comorbidity prevalence, post-op complication rates — approximate, not a substitute for
clinical committee validation, same caveat the design already applies to the
classification rules in §7/§17). This is declared in the data itself, the same way §6
already declares the Colombia demographic substitution: `perfiles_pacientes.synthea_runtime`
is set to `'synthetic_fallback_sin_pysynthea'` instead of `'pysynthea'`/`'synthea_jar'`,
so nobody downstream mistakes this for real Synthea output. `pysynthea` is dropped from
`requirements.txt` and the bundle's serverless `environments` block.

Everything downstream of `perfiles_pacientes` (trajectories, Colombia adaptation,
classification, dual-LLM, noise, publish) is unaffected by this — those components only
depend on the `perfiles_pacientes` schema contract, not on how bronze was produced.

## Colombia-representative population — concrete numbers

"Representative" is made concrete two ways, both already anticipated by the design
(§6's DANE reference table) but not yet given real weights:

1. **Geographic weighting.** New module `src/postop/dane_reference.py`: a static table of
   all 33 Colombian departments + their capital city, with population weights from DANE's
   2025 projection (sourced via Wikipedia's DANE-derived summary table, total ≈53.1M,
   cross-checked against DANE's own July 2025 projection note of 53,057,212). Top of the
   distribution: Bogotá D.C. ~14.9%, Antioquia ~13.1%, Valle del Cauca ~8.8%, Cundinamarca
   ~6.9%, Atlántico ~5.4%, Santander ~4.5%, Bolívar ~4.3%, down to the smallest Amazon
   departments at a fraction of a percent. `adapt_to_colombia` samples
   `(departamento, ciudad)` per patient with `random.Random(seed).choices(..., weights=...)`
   instead of Faker's uniform city picker, so the aggregate department distribution across
   the generated population tracks Colombia's actual population shape, not a flat/uniform
   spread.
2. **Sample size.** New `population` section in `conf/project.yml`:
   ```
   population:
     seed: 42
     n_pacientes_representativos: 300
   ```
   300 is proposed (not fixed) — large enough that each ground-truth label bucket can
   clear the §12 quality bar (no label <10%/>70%) without needing an artificially skewed
   generator, and large enough for the department-weighted sample to actually resemble the
   national distribution instead of a handful of departments dominating by chance; small
   enough to keep dual-LLM simulation cost bounded (§14 already flags this) and to stay
   comfortably inside Free Edition's compute/storage envelope. The existing
   `pilot.n_pacientes: 25` in `conf/project.yml` is kept as-is, as the smaller smoke-test
   tier (§14's "run a 20-30 patient pilot first" — unrelated to Colombia representativeness,
   just cost control). `generate_synthea_profiles.py` takes `--n-pacientes` on the CLI,
   defaulting to `population.n_pacientes_representativos`.

   **Flag for you:** if 300 is wrong for your budget/timeline, tell me a different number
   before I implement — it's a one-line config change either way, but I want the number in
   this plan to be the one you actually approve, not one I guess at silently.

## File-by-file changes

### New: `src/postop/dane_reference.py`
Static list of the 33 departments (name, capital city, 2025 population, normalized
weight). No external calls at runtime — the table is baked in, sourced once now via DANE's
public projections. Exposes `sample_departamento_ciudad(rng: random.Random) -> tuple[str, str]`.

### New: `src/postop/clinical_domains.py`
Shared enumerated value domains and per-archetype distribution parameters used by both the
trajectory simulator and the classifier, so they can't drift out of sync:
- `HERIDA = ["normal", "eritema_leve", "dehiscencia", "secrecion_purulenta"]`
- `MOVILIDAD = ["normal", "limitada_esperada", "incapacitante_nueva"]`
- `APETITO = ["normal", "levemente_disminuido", "muy_disminuido"]`
- `SUENO = ["normal", "levemente_alterado", "muy_alterado"]`
- `dolor_nrs`: int 0-10, `fiebre_c`: float, plausible post-op range
- Per-archetype (`recuperacion_normal`, `complicacion_leve_vigilancia`, `complicacion_real`)
  day-indexed sampling parameters (e.g. probability of each `herida`/`movilidad` state,
  temperature distribution) — monotonically improving for `recuperacion_normal`, a
  transient moderate bump mid-series for `complicacion_leve_vigilancia`, escalating toward
  a 🔴-triggering combination for `complicacion_real`.
- Procedure calibration table for the 5 allowlisted modules (age range, comorbidity pool +
  probability, base complication rate) used by `generate_synthea_profiles.py`.
All of these are explicitly labeled in a module docstring as approximate/engineering
placeholders pending clinical committee sign-off — same posture the design already takes
with `REGLA_VERSION` in §7/§17.

### `src/postop/generate_synthea_profiles.py`
- Replace `run_pysynthea` with `generate_synthetic_profiles(module_allowlist, n_pacientes,
  seed, bronze_volume_path) -> list[dict]`: pure Python, no Spark/pysynthea import at
  module load time. For each patient: pick a module from the allowlist (uniform, so all 5
  procedures are represented), sample age/comorbidities/`complicacion_encounter` from
  `clinical_domains`'s procedure table, deterministic per `seed + patient_index`. Writes
  the raw JSON bundles to the Volume path (still real I/O, just no external generator).
- `parse_bundles_to_perfiles_pacientes` becomes a thin Spark I/O wrapper (lazy
  `from postop import schemas` / `pyspark` imports inside the function body, not at module
  top) that reads the JSON back and writes `silver.perfiles_pacientes` with
  `synthea_runtime='synthetic_fallback_sin_pysynthea'`.
- `main()` reads `--n-pacientes` (default from `population.n_pacientes_representativos`),
  `--seed` (default from `population.seed`).
- Module docstring rewritten to document the §5.2 spike result above instead of claiming
  PySynthea will be used.

### `src/postop/simulate_postop_trajectories.py`
- `simulate_trajectory`: real implementation. Archetype selection:
  `complicacion_encounter=True` ⟹ forced `complicacion_real` (design's own
  non-contradiction rule — a Synthea-flagged complication must converge to 🔴 before the
  encounter date); `complicacion_encounter=False` ⟹ weighted pick between
  `recuperacion_normal` (majority) and `complicacion_leve_vigilancia` (minority), seeded
  per patient. For each `call_days` entry, sample the 6-symptom vector from the archetype's
  day-indexed distribution in `clinical_domains`.
- `build_trayectorias_postop`: thin Spark I/O wrapper (lazy imports), writes
  `silver.trayectorias_postop`.

### `src/postop/adapt_colombia.py`
- `adapt_to_colombia`: real implementation. Per patient, seeded
  `random.Random(hash((seed_column_value, seed)))`:
  - `nombre_completo`, `direccion` via `Faker("es_CO")`, seeded per patient for determinism.
  - `ciudad`/`departamento` via `dane_reference.sample_departamento_ciudad` (population-weighted).
  - `documento_cc`: synthetic cédula-shaped number in a range that doesn't collide with
    real DANE cédula ranges (documented constant offset).
  - `eps`: uniform pick from the curated static list already named in the design
    (Sura, Sanitas, Compensar, Nueva EPS, + a few more).
  - `adaptation_fields` set to the literal list of columns actually replaced;
    `source_country='US'`, `adapted_country='CO'`, `adaptation_ts=now()`.
  - Works on a plain list-of-dicts/pandas path so it's unit-testable without Spark; the
    Spark DataFrame variant is a thin `mapInPandas`/`applyInPandas` wrapper.

### `src/postop/classify_ground_truth.py`
- `classify(sintomas)`: implement exactly the rule already documented in the stub
  docstring (§7) — no new clinical logic invented, just turning the documented pseudocode
  into real code against the `clinical_domains` enums. Bump `REGLA_VERSION` to
  `"v1-implementada-sin-validacion-clinica"` (still flagged as pending committee
  calibration, per §17 — this unblocks the rest of the pipeline without pretending the
  clinical validation already happened).
- `classify_casos_clinicos`: thin Spark I/O wrapper.
- Existing `tests/test_classify_ground_truth.py` placeholder tests (which currently assert
  `NotImplementedError`) are replaced with real assertions: each individual red flag alone
  triggers `rojo`; the amarillo 2-of-5 threshold (1 signal ⟹ verde, 2 ⟹ amarillo); boundary
  values (`fiebre_c == 38.5`, `dolor_nrs == 8`); default `verde`.

### `src/postop/simulate_dual_llm.py`
- `build_patient_prompt` / `build_agent_prompt`: real template rendering from
  `prompts/patient_system.md` / `prompts/agent_system.md` (simple `{{placeholder}}`
  substitution — the templates already exist and document their own variables).
- `simulate_conversation`: real orchestration logic, but the actual model call goes
  through a small injected client interface (`Protocol`/callable) so it's unit-testable
  with a fake client — real calls need `ai_query()` against a live Model Serving endpoint,
  which doesn't exist yet (out of scope here, same as Plan 03/04's stance on not running
  against real infra prematurely). Turn loop alternates patient/agent, stops when the
  agent's script has covered the 6 symptom areas or a max-turn cap is hit, accumulates
  `prompt_tokens`/`completion_tokens` from whatever the client returns.
- `run_dual_llm_batch`: thin Spark orchestration wrapper (`mapInPandas` shape), with the
  per-case checkpointing behavior described in §8.2 delegated to a real `MERGE`-shaped
  upsert helper — still requires a live endpoint to actually run, but the batching/rate
  limiting/merge logic is implemented and unit-testable against a fake client.

### `src/postop/inject_noise.py`
- Split the 6 noise types (§9.1) into two groups because of a signature constraint the
  stub already fixed (`inject_noise_udf(texto, tipo_ruido, intensidad, seed) -> str`,
  text-in/text-out — can't add or drop rows from inside it):
  - **Text-mutating types**, implemented inside `inject_noise_udf`: `ruido_stt` (seeded
    char/word-level corruption + `[inaudible]` insertion, probability scaled by
    intensidad), `modismo_regional` (small curated Colombian-Spanish phrase-substitution
    map), `respuesta_ambigua` (templated evasive-phrase pool), `contradiccion` (appends a
    templated contradictory clause).
  - **Structural types**, implemented in `inject_noise_batch` directly (they add/remove
    rows, which a per-text UDF can't do): `informacion_faltante` (drops a turn, still logs
    it in `noise_mapping_log` with `texto_ruidoso` empty), `cambio_interlocutor` (inserts a
    `hablante='tercero'` row).
  - This split is called out explicitly in the module docstring so it doesn't look like an
    accidental inconsistency later.
- `inject_noise_batch`: for every affected turn, writes one `noise_mapping_log` row
  (§9.2 — the "no silent transformation" invariant becomes a real, checkable property, not
  just a comment) and copies `label_ground_truth` unchanged from Capa 1.

### `src/postop/publish_gold.py`
- `run_quality_expectations`: implement the concrete checks from §12 (no-null demographic
  fields + `adapted_country='CO'` 100%; label distribution within [10%, 70%]; every
  `caso_id` has ≥1 patient turn and ≥1 agent turn, no empty turns; every Capa 2 dialogo has
  ≥1 `noise_mapping_log` row; 100% `validado_por` non-null in Capa 3) as pure functions
  over pandas/list-of-dict inputs (unit-testable), plus a thin Spark wrapper that pulls
  each table and calls them.
- `apply_grants`: executes `sql/ddl/30_publish_gold_grants.sql` plus, per
  `governance.committee_emails`, one `GRANT USE SCHEMA, SELECT ON SCHEMA
  postop_dataset.gold_comite TO `<email>`` and one `GRANT SELECT ON TABLE
  postop_dataset.silver.dialogos_capa3_limite TO `<email>`` per entry (the SQL file
  already documents these as templated comments — this is what fills them in for real).
- `publish_gold_views`: executes the two `CREATE OR REPLACE VIEW` statements already fully
  written in the SQL file.

### `notebooks/curate_edge_cases.py`
- `submit_edge_case`: real implementation — validate `categoria_caso_limite` against
  `CATEGORIAS_CASO_LIMITE`, run `classify_ground_truth.classify()` against the case's
  symptom vector as an **advisory** consistency check (log a warning, don't block — per
  §7, curated edge cases are allowed to sit outside the rule on purpose), require
  `validado_por`/`criterio_clinico_ref` non-empty, then `MERGE INTO
  silver.dialogos_capa3_limite` keyed on `dialogo_id`. Still zero fabricated edge cases —
  this is human-in-the-loop by design (§10) and stays out of scope to fake.

### `conf/project.yml`
- Add the `population:` section above.
- No changes to `governance`/`synthea`/`trajectories` sections.

### `requirements.txt` and `resources/postop_pipeline.job.yml`
- Remove `pysynthea>=0.1` from both (requirements.txt comment + bundle `environments.postop_env.spec.dependencies`).
- Add `numpy` (weighted sampling) to both.

### Tests (`tests/`)
New test modules, one per component, running against the pure-Python logic paths only (no
pyspark/Faker-cluster dependency required beyond what's in `requirements.txt`):
- `test_classify_ground_truth.py` — rewritten (see above).
- `test_dane_reference.py` — weights sum to 1.0, all 33 departments present, sampling is
  deterministic for a fixed seed.
- `test_adapt_colombia.py` — determinism (same `paciente_id` + seed ⟹ identical row across
  runs), `adaptation_fields` matches what actually changed, over ~500 sampled patients the
  department distribution is within a reasonable tolerance of the DANE weights (not
  concentrated in 1-2 departments).
- `test_simulate_postop_trajectories.py` — `complicacion_encounter=True` always yields
  `arquetipo_trayectoria == 'complicacion_real'` and the last call day classifies to
  `rojo`; `recuperacion_normal` trajectories never classify to `rojo` on the last call day.
- `test_generate_synthea_profiles.py` — reproducibility for a fixed seed, all 5 allowlisted
  modules appear across a large-enough sample, per-module complication rate roughly
  matches the configured calibration.
- `test_inject_noise.py` — every affected turn produces exactly one `noise_mapping_log`
  row; `label_ground_truth` is byte-identical between Capa 1 and Capa 2 for the same case;
  determinism for a fixed seed.
- `test_publish_gold_expectations.py` — each §12 check independently catches the fixture
  case engineered to violate it, and passes on a clean fixture.

## Explicitly out of scope for this plan

- **No real LLM calls, no live Model Serving endpoint.** `simulate_dual_llm` logic is
  complete and unit-tested against a fake client; nothing calls a real endpoint.
- **No actual clinical committee validation** of `classify_ground_truth`'s rule thresholds
  or the `clinical_domains`/procedure-calibration parameters — implemented from the
  design's own documented rule + literature-anchored approximations, explicitly flagged as
  provisional (same posture the design already takes).
- **No fabricated Capa 3 edge cases** — `submit_edge_case` becomes real, but curating
  actual cases is human-in-the-loop by design.
- **No `databricks bundle deploy`/`run` against the real workspace**, no execution of
  `sql/ddl/*.sql` against a live catalog, no actual 300-patient generation run. This plan
  only makes the code real and locally testable; running it for real is a follow-up plan,
  same pattern as Plan 03/04.
- **No changes to `sql/ddl/*.sql` schemas** — the population/geography work fits inside
  the existing `perfiles_pacientes_co` contract (`departamento`/`ciudad` columns already
  exist), no DDL changes needed.

## Verification

- Local ephemeral venv (`.venv/`, already gitignored) with `pip install PyYAML Faker numpy
  pytest` (skip `pyspark`/`delta-spark`/`databricks-sdk`/`anthropic` — not needed for the
  pure-logic tests, and heavy to install locally; every module keeps Spark imports lazy
  inside I/O-boundary functions specifically so this works).
- `pytest -q` passes, covering all the new test modules above.
- Manual read-through confirming no module does a top-level `import pyspark` (would break
  local testability) and that `pysynthea` is fully gone from `requirements.txt` and
  `resources/postop_pipeline.job.yml`.
