# 01 — Scaffold Databricks Asset Bundle

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `specs/Diseño Técnico — Dataset Seguimiento Post-Operatorio.md` (§4, §8.3, §9.2, §10, §11, §16)
and `specs/Ficha Técnica — Dataset Seguimiento Post-Operatorio.pdf` (§4, §6)

## Goal

Prepare the project skeleton — the Databricks Asset Bundle (DAB), stack/dependencies,
catalog config, table contracts (DDL), and stubbed pipeline modules — so the team can
start filling in the 6 components and deploy to Databricks. This implements §11 and §16
of the technical design.

**No pipeline logic is written in this plan.** Every module in `src/postop/` is a pure
stub: correct signature, docstring referencing the relevant design section, explicit
Spark schema where applicable, and a `raise NotImplementedError(...)` body. Real logic
(Synthea generation, trajectory simulation, Colombia adaptation, rule engine, dual-LLM
calls, noise injection, edge-case curation) is deferred to follow-up plans, one per
component.

## Decisions already made (confirmed with user)

- **Stub depth:** pure scaffold only — no component gets real logic in this pass,
  including `classify_ground_truth.classify()` even though its rules are fully
  specified in design §7.
- **Layout:** the bundle lives at the **repo root** (`databricks.yml`, `src/`,
  `resources/`, `sql/`, etc. directly under `techsphere_data_set/`), as siblings to
  `specs/` and `Plans/` — not nested under a `postop-dataset/` subfolder.

## Resulting structure

```
techsphere_data_set/
├── databricks.yml                       # DAB definition: targets dev/prod, vars, workspace
├── requirements.txt                     # stack pins (see below)
├── .gitignore                           # .databricks/, __pycache__, *.egg-info, secrets
├── README.md                            # updated: how to deploy/run the bundle
├── conf/
│   └── project.yml                      # catalog/schema names, module allowlist, N pacientes, trajectory days
├── resources/
│   └── postop_pipeline.job.yml          # Workflow DAG (7 tasks + cluster specs per §11)
├── sql/
│   └── ddl/                             # one .sql per table = the versioned data contracts (§4,§8.3,§9.2,§10)
│       ├── 00_catalog_schemas.sql
│       ├── 10_perfiles_pacientes.sql
│       ├── 11_trayectorias_postop.sql
│       ├── 12_perfiles_pacientes_co.sql
│       ├── 13_casos_clinicos_etiquetados.sql
│       ├── 20_dialogos_capa1_limpia.sql   (+ CHECK label_valido)
│       ├── 21_dialogos_capa2_ruidosa.sql
│       ├── 22_noise_mapping_log.sql
│       ├── 23_dialogos_capa3_limite.sql
│       └── 30_publish_gold_grants.sql     (grants/revokes §4)
├── src/postop/                          # importable package (stubs: signatures + docstrings + schemas)
│   ├── __init__.py
│   ├── config.py                        # loads conf/project.yml, three-level names
│   ├── schemas.py                       # StructType defs mirroring the DDL (explicit schemas)
│   ├── generate_synthea_profiles.py     # Componente 1
│   ├── simulate_postop_trajectories.py  # Componente 1 §5.3
│   ├── adapt_colombia.py                # Componente 2
│   ├── classify_ground_truth.py         # Componente 3 (rule engine stub — signature from §7)
│   ├── simulate_dual_llm.py             # Componente 4 (+ prompts/ dir referenced)
│   ├── inject_noise.py                  # Componente 5
│   └── publish_gold.py                  # grants + gold views
├── prompts/                             # dual-LLM system prompts as repo files (§8.1, §16)
│   ├── patient_system.md
│   └── agent_system.md
├── notebooks/
│   └── curate_edge_cases.py             # Componente 6, human-in-the-loop (Databricks notebook source)
└── tests/
    └── test_classify_ground_truth.py    # placeholder test that just imports the stub module
```

## Stack (`requirements.txt`)

Aligned with the design's already-made tooling decisions:

- `pyspark`, `delta-spark` — Delta/Spark idioms per skill guidance
- `pysynthea` — recommended runtime (§4); code comment notes the JAR fallback risk R1
- `faker` — Colombia adaptation (§6)
- `databricks-sdk` — Model Serving / secrets (§8.2)
- `anthropic` — external-API dual-LLM option, via Databricks Secrets, never hardcoded
- `pytest` — test scaffolding

## `databricks.yml`

Bundle name `postop_dataset`, `dev` and `prod` targets, variables for catalog name and
Model Serving endpoint. Environment-specific values (workspace URL, secret scope)
referenced as vars/secret scopes — never hardcoded (§13).

## Explicitly out of scope for this plan

- Actual Synthea generation, trajectory simulation, Colombia adaptation logic, LLM
  calls, noise injection, edge-case curation logic (each is its own follow-up plan).
- Any connection to a real Databricks workspace or actual `databricks bundle deploy`
  run (no credentials in this environment).

## Verification

- `pytest -q` confirms all stub modules import cleanly and the package is well-formed.
- Manual read-through: DDL columns in `sql/ddl/*.sql` match the `StructType` definitions
  in `src/postop/schemas.py`.
