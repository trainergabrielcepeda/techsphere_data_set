"""Componente 2 — Adaptación geográfica a Colombia (Diseño Técnico §6).

Resuelve el sesgo geográfico de la fuente clínica base (demografía/nombres/direcciones
calibrados con datos de EE. UU., ficha §3) reemplazando la capa demográfica en
post-proceso — los módulos clínicos/de procedimiento se mantienen intactos, porque la
progresión clínica post-operatoria no depende de la nacionalidad del paciente.

La sustitución se declara explícitamente en columnas de auditoría (nunca oculta):
source_country, adapted_country, adaptation_fields, adaptation_ts.

Representatividad poblacional (Plan 05): el (departamento, ciudad) de cada paciente se
muestrea ponderado por población real de DANE (``dane_reference``), no de forma uniforme
— así la distribución geográfica agregada de la población generada se parece a la
distribución real de Colombia, no a un reparto plano entre ciudades.

Escribe: silver.perfiles_pacientes_co (schemas.PERFILES_PACIENTES_CO_SCHEMA, sql/ddl/12).
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from faker import Faker

# Databricks ejecuta este archivo como spark_python_task suelto (python_file, sin
# empaquetar como wheel — §11) — src/ no queda en sys.path por su cuenta, confirmado al
# correr el job real en Plan 06 Fase 4 (ModuleNotFoundError: No module named 'postop').
# __file__ tampoco existe en este contexto: Databricks ejecuta el script vía
# exec(compile(source, filename, 'exec')), que no inyecta __file__ en los globals —
# también confirmado contra el workspace real (NameError: name '__file__' is not
# defined). sys._getframe().f_code.co_filename sí lo tiene, vía co_filename del compile().
_this_file = sys._getframe().f_code.co_filename
sys.path.insert(0, str(Path(_this_file).resolve().parents[1]))

from postop import config, dane_reference

# Lista curada estática — EPS colombianas con mayor participación de mercado (§6).
EPS_COLOMBIA = [
    "Nueva EPS",
    "Sura EPS",
    "Sanitas EPS",
    "Compensar EPS",
    "Famisanar EPS",
    "Salud Total EPS",
    "Coosalud EPS",
    "Aliansalud EPS",
]

# Offset que evita colisión con rangos de cédula de ciudadanía real colombiana vigentes.
CEDULA_OFFSET = 900_000_000

ADAPTATION_FIELDS = ["nombre_completo", "direccion", "ciudad", "departamento", "documento_cc", "eps"]


def _adapt_one(paciente_id: str, seed: int) -> dict:
    rng = random.Random(config.stable_seed("adapt_colombia", paciente_id, seed))
    faker = Faker("es_CO")
    faker.seed_instance(config.stable_seed("adapt_colombia_faker", paciente_id, seed))

    departamento, ciudad = dane_reference.sample_departamento_ciudad(rng)
    documento_cc = str(CEDULA_OFFSET + rng.randint(0, 99_999_999))

    return {
        "paciente_id": paciente_id,
        "nombre_completo": faker.name(),
        "direccion": faker.street_address(),
        "ciudad": ciudad,
        "departamento": departamento,
        "documento_cc": documento_cc,
        "eps": rng.choice(EPS_COLOMBIA),
        "source_country": "US",
        "adapted_country": "CO",
        "adaptation_fields": list(ADAPTATION_FIELDS),
        "adaptation_ts": datetime.now(timezone.utc),
    }


def adapt_to_colombia(rows: list[dict], seed_column: str = "paciente_id", seed: int = 42) -> list[dict]:
    """Función pura: recibe filas de ``silver.perfiles_pacientes`` (list[dict]) y
    devuelve filas con esquema ``schemas.PERFILES_PACIENTES_CO_SCHEMA``.

    Determinística por ``seed_column`` + ``seed`` (§6) — mismo ``paciente_id``, mismos
    datos colombianos sintéticos en cualquier re-ejecución.
    """
    return [_adapt_one(row[seed_column], seed) for row in rows]


def build_perfiles_pacientes_co(spark, perfiles_pacientes_table: str, output_table: str, seed: int) -> None:
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    paciente_ids = [
        row["paciente_id"] for row in spark.table(perfiles_pacientes_table).select("paciente_id").collect()
    ]
    rows = adapt_to_colombia([{"paciente_id": pid} for pid in paciente_ids], seed=seed)

    df = spark.createDataFrame(rows, schema=schemas.PERFILES_PACIENTES_CO_SCHEMA)
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 2 — adaptación geográfica Colombia")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    input_table = config.table_fqn("silver", "perfiles_pacientes", cfg, catalog_override=args.catalog)
    output_table = config.table_fqn("silver", "perfiles_pacientes_co", cfg, catalog_override=args.catalog)
    seed = cfg["population"]["seed"]

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    build_perfiles_pacientes_co(spark=spark, perfiles_pacientes_table=input_table, output_table=output_table, seed=seed)


if __name__ == "__main__":
    main()
