---
name: data-engineering-databricks
description: Use this skill when working on data engineering tasks in this workspace, especially anything involving Databricks — building or reviewing PySpark/Spark SQL pipelines, Delta Lake tables, Unity Catalog objects, Databricks Jobs/Workflows, notebooks, DLT (Delta Live Tables) pipelines, or medallion-architecture (bronze/silver/gold) data models. Also applies to general ETL/ELT design, data quality checks, and dataset schema work (e.g. the specs under specs/).
---

# Data Engineering & Databricks

## Scope

Apply this skill to tasks such as:
- Designing or reviewing bronze/silver/gold (medallion) data pipelines
- Writing PySpark or Spark SQL transformations
- Delta Lake table design: partitioning, Z-ORDER, OPTIMIZE, VACUUM, merge/upsert (`MERGE INTO`) logic, schema evolution
- Unity Catalog: catalogs, schemas, managed vs. external tables, grants, lineage
- Databricks Jobs/Workflows and Delta Live Tables (DLT) pipeline definitions
- Notebook-based development (`.py`/`.ipynb` with `# Databricks notebook source` markers, `%sql`/`%md` magic cells)
- Data quality/validation logic (expectations, constraints, null/duplicate checks)
- Translating a data spec or data dictionary (e.g. PDFs under `specs/`) into a concrete schema or ingestion pipeline

## Working principles

- **Prefer Spark-native idioms.** Use DataFrame transformations and Spark SQL over row-by-row Python loops or pandas UDFs unless the data genuinely needs to fit in driver memory.
- **Delta over generic Parquet** for anything mutable, versioned, or requiring ACID guarantees. Use `MERGE INTO` for upserts rather than delete+insert unless there's a reason not to.
- **Idempotency matters.** Pipelines should be safe to re-run (e.g. `MERGE`, `INSERT OVERWRITE` on a partition, or checkpointed structured streaming) rather than blindly appending.
- **Schema explicitness.** Define schemas explicitly for ingestion (`StructType` or DDL string) rather than relying on inference, especially for production pipelines — this catches upstream schema drift early.
- **Medallion layering.** Bronze = raw/as-landed (minimal transformation, preserves source fidelity). Silver = cleaned/conformed/deduplicated. Gold = business-level aggregates/marts. Don't skip layers or mix responsibilities across them.
- **Unity Catalog naming**: `catalog.schema.table` three-level namespace — don't assume a default `hive_metastore` catalog.
- **Cost/performance awareness**: flag obvious issues like unnecessary `.collect()`/`.toPandas()` on large DataFrames, missing partition pruning predicates, or shuffles caused by avoidable wide transformations.
- When a spec document (PDF, data dictionary) defines the source-of-truth schema for a dataset, read it directly rather than guessing field names/types.

## When touching files in this repo

- Treat documents under `specs/` as the authoritative data dictionary/schema reference — read them before writing ingestion or transformation code that depends on field definitions.
- If Databricks CLI/SDK config (`databricks.yml`, Asset Bundles) or cluster configs are added later, keep environment-specific values (workspace URLs, cluster IDs, secrets) out of source and out of notebooks — reference secret scopes instead.
