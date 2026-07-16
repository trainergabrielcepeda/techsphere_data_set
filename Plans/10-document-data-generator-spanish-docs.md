# 10 — Document the data generator (Spanish `docs/`) + README quickstart hint

**Status:** awaiting approval
**Author:** Claude (Data Engineer role), for Gabriel Cepeda
**Date:** 2026-07-15
**Based on:** `specs/Diseño Técnico — Dataset Seguimiento Post-Operatorio.md` (existing
technical design, already in Spanish) and the current state of `src/postop/*.py`,
`conf/project.yml`, `databricks.yml`, `resources/postop_pipeline.job.yml` (all 6
components implemented, no stubs left — per Plans 05-09).

## Goal

Add user-facing documentation of the data generator's architecture under a new `docs/`
folder, **in Spanish**, and add a short pointer/quickstart hint to the root `README.md`
so someone who wants to replicate a run for testing knows where to start. This is a
**documentation-only** change — no code, schema, or pipeline logic changes.

Note on scope vs. `specs/Diseño Técnico...md`: that document is the original design
rationale (why each decision was made, written 2026-07-15 before implementation). The new
`docs/` content is the **as-built, user-facing** reference — it describes what actually
exists in `src/postop/` today (including deviations already called out in code comments:
`pysynthea` PyPI reality, Free Edition serverless-only constraints, Anthropic vs.
OpenRouter provider paths, `REGLA_VERSION` clinical-validation caveat) and how to set it
up and run it. It will cross-reference the technical design doc rather than duplicate it.

## Deliverables

### 1. `docs/generador-datos.md` (new file, new `docs/` folder)

Single comprehensive document, in Spanish, with these sections:

1. **Resumen** — qué genera el pipeline (dataset sintético de seguimiento
   post-operatorio, 3 capas) y para qué (Reto Tech Sphere 2026).
2. **Arquitectura** — los 6 componentes + DAG de Databricks Workflows, diagrama
   (reutilizando/adaptando el mermaid de `specs/Diseño Técnico...md` §3), modelo de
   catálogo Unity Catalog (bronze/silver/gold_participantes/gold_comite), y estado real
   de implementación de cada componente (todos implementados, ver `src/postop/`).
3. **Criterios de diseño** — por qué el ground-truth lo asigna un motor de reglas y no
   el LLM (evita circularidad), por qué la adaptación geográfica es post-proceso
   declarado en columnas de auditoría (no oculta), por qué el muestreo geográfico usa
   pesos DANE en vez de uniforme, por qué Capa 3 nunca pasa por el inyector de ruido ni
   se expone a participantes.
4. **Referencias** — proyecciones DANE 2025 (`dane_reference.py`), criterios CDC de
   infección de sitio quirúrgico/SIRS y de dehiscencia de herida (`clinical_domains.py`),
   el propio `specs/Diseño Técnico — Dataset Seguimiento Post-Operatorio.md`, y los planes
   de implementación relevantes en `Plans/05`-`09`.
5. **Guía de instalación / puesta en marcha** — pasos concretos: clonar el repo, crear
   entorno virtual, `pip install -r requirements.txt`, configurar perfil de
   `databricks configure` o variables `DATABRICKS_HOST`/`DATABRICKS_TOKEN`, crear el
   Secret Scope con la API key del proveedor LLM elegido (`openrouter-api-key` o
   `anthropic-api-key`), `databricks bundle validate/deploy/run -t dev`, correr
   `pytest -q` localmente antes de desplegar.
6. **Prerrequisitos** — Python (versión usada por el proyecto), cuenta de Databricks
   (Free Edition es suficiente pero serverless-only), CLI de Databricks instalado, una
   API key de LLM externo (OpenRouter o Anthropic) para el Componente 4, acceso de
   red saliente desde el workspace hacia el proveedor elegido.
7. **Advertencias / Limitaciones (caveats)** — explícito y sin suavizar:
   - `pysynthea` de PyPI no es un generador de pacientes (es un downloader/query-tool
     OMOP); el Componente 1 usa un generador sintético propio calibrado, no Synthea real.
   - Las reglas clínicas (`classify_ground_truth.REGLA_VERSION`) y la calibración de
     `clinical_domains.py` son aproximaciones de ingeniería **sin validación clínica del
     comité** todavía.
   - Databricks Free Edition es serverless-only (sin job_clusters/autoscale
     configurable) y de un solo workspace/metastore por cuenta.
   - El nivel gratuito de OpenRouter tiene cuota diaria dura (confirmado empíricamente);
     el proveedor Anthropic evita la cuota pero factura por token desde la primera llamada.
   - El gate de calidad §12 (balance de labels) es no-bloqueante para corridas pequeñas
     desde Plan 09 — dataset desbalanceado puede publicarse igual, documentado como
     decisión deliberada, no bug.
   - Capa 3 (casos límite) requiere curaduría humana manual (`notebooks/curate_edge_cases.py`)
     — nunca se genera ni se publica automáticamente.
   - Todos los datos son sintéticos; ninguna capa contiene PII real.

Diagram reused from the technical design will be adapted (not copied verbatim) to focus
on the generator's runtime view (what a user deploying/running it needs to know) rather
than the original design-rationale framing.

### 2. `README.md` (root) — quickstart hint

Add a short new section (in Spanish, matching the existing README's language) pointing
readers who want to replicate/test the dataset generation to `docs/generador-datos.md`,
positioned near the top (after the current intro, before "Estado"). Keep the existing
"Desplegar el bundle" / "Correr las pruebas" sections as-is — this is an additional
pointer/hint, not a rewrite of the existing quickstart commands. Also add
`docs/generador-datos.md` to the "Estructura del proyecto" file tree listing.

## Out of scope

- No changes to `src/postop/*.py`, `conf/project.yml`, `databricks.yml`,
  `resources/*.yml`, or `sql/ddl/*.sql`.
- No changes to `specs/Diseño Técnico...md` (left as the historical design record).
- Not addressing the in-progress uncommitted work already in the working tree
  (`Plans/09-nonblocking-balance-gate-and-40-patients.md`,
  `sql/ddl/14_alertas_calidad.sql`, and the modified `databricks.yml` / `publish_gold.py`
  / `schemas.py` / grants / tests) — those are a separate, already-started thread and
  won't be touched or referenced as "done" in the new docs.

## Open question before implementing

Whether the new architecture doc should be a single file (`docs/generador-datos.md`) or
split into multiple files (e.g. `docs/arquitectura.md`, `docs/instalacion.md`,
`docs/referencias.md`) inside the new `docs/` folder. Defaulting to **one file** unless
told otherwise, since the content, while covering several sections, is not large enough
to justify fragmenting navigation across files.
