"""Componente 3 — Motor de clasificación ground-truth (Diseño Técnico §7).

Principio de diseño clave: el ground-truth NO lo asigna el LLM. Se asigna con un motor de
reglas clínicas determinístico ANTES de generar la conversación; el LLM (Componente 4)
solo tiene la tarea de verbalizar un caso ya etiquetado. Si el label lo decidiera el LLM,
o se infiriera de la transcripción después, el dataset no serviría como referencia
objetiva — sería circular.

La regla vive junto al dato en silver.casos_clinicos_etiquetados
(schemas.CASOS_CLINICOS_ETIQUETADOS_SCHEMA, sql/ddl/13), versionada por
``REGLA_VERSION`` — no en un notebook desconectado.

``REGLA_VERSION`` se mantiene como "sin validación clínica" (Plan 05): las reglas de
abajo son exactamente las documentadas en el diseño (§7), suficientes para desbloquear el
resto del pipeline, pero — igual que ``clinical_domains`` — pendientes de calibración con
el comité antes de congelarse (§17).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Databricks ejecuta este archivo como spark_python_task suelto (python_file, sin
# empaquetar como wheel — §11) — src/ no queda en sys.path por su cuenta, confirmado al
# correr el job real en Plan 06 Fase 4 (ModuleNotFoundError: No module named 'postop').
# __file__ tampoco existe en este contexto: Databricks ejecuta el script vía
# exec(compile(source, filename, 'exec')), que no inyecta __file__ en los globals —
# también confirmado contra el workspace real (NameError: name '__file__' is not
# defined). sys._getframe().f_code.co_filename sí lo tiene, vía co_filename del compile().
_this_file = sys._getframe().f_code.co_filename
sys.path.insert(0, str(Path(_this_file).resolve().parents[1]))

from postop import config

REGLA_VERSION = "v1-implementada-sin-validacion-clinica"


def classify(sintomas: dict) -> str:
    """Clasifica un vector de síntomas en 'verde' | 'amarillo' | 'rojo' (§7).

    ``sintomas`` debe traer las claves: dolor_nrs, fiebre_c, herida, movilidad,
    apetito, sueno (ver schemas.CASOS_CLINICOS_ETIQUETADOS_SCHEMA /
    TRAYECTORIAS_POSTOP_SCHEMA / clinical_domains).
    """
    fiebre_c = sintomas["fiebre_c"]
    herida = sintomas["herida"]
    dolor_nrs = sintomas["dolor_nrs"]
    movilidad = sintomas["movilidad"]
    apetito = sintomas["apetito"]
    sueno = sintomas["sueno"]

    # 🔴 escalar — cualquier bandera roja individual basta.
    if (
        fiebre_c >= 38.5
        or herida in ("dehiscencia", "secrecion_purulenta")
        or dolor_nrs >= 8
        or movilidad == "incapacitante_nueva"
    ):
        return "rojo"

    # 🟡 vigilar — combinación de señales moderadas.
    senales_amarillas = sum(
        [
            fiebre_c >= 37.8,
            dolor_nrs >= 5,
            herida == "eritema_leve",
            apetito == "muy_disminuido",
            sueno == "muy_alterado",
        ]
    )
    if senales_amarillas >= 2:
        return "amarillo"

    return "verde"


def classify_casos_clinicos(spark, trayectorias_table: str, output_table: str, regla_version: str) -> None:
    """Aplica ``classify`` sobre todas las filas de ``trayectorias_table`` y escribe
    ``output_table`` con el vector de síntomas de entrada + label + ``regla_version``.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    trayectorias = [row.asDict() for row in spark.table(trayectorias_table).collect()]

    rows = []
    for t in trayectorias:
        sintomas = {k: t[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")}
        rows.append(
            {
                "caso_id": f"caso_{t['trayectoria_id']}",
                "paciente_id": t["paciente_id"],
                "trayectoria_id": t["trayectoria_id"],
                "dia_postop": t["dia_postop"],
                **sintomas,
                "label": classify(sintomas),
                "regla_version": regla_version,
                "clasificado_ts": datetime.now(timezone.utc),
            }
        )

    df = spark.createDataFrame(rows, schema=schemas.CASOS_CLINICOS_ETIQUETADOS_SCHEMA)
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 3 — motor de clasificación ground-truth")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    trayectorias_table = config.table_fqn("silver", "trayectorias_postop", cfg, catalog_override=args.catalog)
    output_table = config.table_fqn("silver", "casos_clinicos_etiquetados", cfg, catalog_override=args.catalog)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    classify_casos_clinicos(
        spark=spark, trayectorias_table=trayectorias_table, output_table=output_table, regla_version=REGLA_VERSION
    )


if __name__ == "__main__":
    main()
