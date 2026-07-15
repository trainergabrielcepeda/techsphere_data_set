"""Componente 1 (extensión) — Simulador de trayectorias post-operatorias (§5.3).

Cubre la brecha de granularidad temporal identificada en el diseño técnico: la fuente
clínica base (Componente 1, ver ``generate_synthea_profiles.py``) no genera por defecto
una serie diaria de síntomas de seguimiento con la granularidad que exige el reto. Este
simulador probabilístico complementario toma como entrada ``silver.perfiles_pacientes`` y
genera N llamadas (día 1, 3, 7, 14 — configurable en ``conf/project.yml`` bajo
``trajectories.call_days``) con un vector de 6 síntomas por llamada, siguiendo uno de 3
arquetipos calibrados en ``clinical_domains``.

El arquetipo elegido para cada paciente es consistente con
``perfiles_pacientes.complicacion_encounter``: nunca puede contradecir lo que se decidió
a nivel macro para ese paciente (``choose_archetype``, §5.3).

Escribe: silver.trayectorias_postop (schemas.TRAYECTORIAS_POSTOP_SCHEMA, sql/ddl/11).
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timezone
from typing import Optional

from postop import clinical_domains, config


def choose_archetype(complicacion_encounter: bool, archetypes: list[str], rng: random.Random) -> str:
    """Elige el arquetipo de trayectoria, consistente con
    ``perfiles_pacientes.complicacion_encounter`` (§5.3): si se marcó una complicación en
    el encounter posterior, la trayectoria SIEMPRE converge a ``complicacion_real`` — nunca
    puede contradecir lo que ya se decidió a nivel macro para ese paciente.
    """
    if complicacion_encounter:
        return "complicacion_real" if "complicacion_real" in archetypes else archetypes[-1]

    candidatos = [a for a in archetypes if a != "complicacion_real"] or list(archetypes)
    # 50/50 en vez de un reparto más sesgado a "normal": deja suficiente peso en
    # complicacion_leve_vigilancia para que la distribución agregada de labels satisfaga
    # la expectativa de calidad §12 (ningún label <10%/>70%) sin necesitar tasas de
    # complicación real poco realistas (Plan 05, calibrado con margen contra la seed por
    # defecto de conf/project.yml population.seed).
    pesos = [0.50 if a == "recuperacion_normal" else 0.50 for a in candidatos]
    return rng.choices(candidatos, weights=pesos, k=1)[0]


def simulate_trajectory(
    paciente_profile: dict,
    call_days: list[int],
    archetypes: list[str],
    seed: int,
) -> list[dict]:
    """Genera la serie de llamadas de seguimiento para un paciente.

    Devuelve una lista de filas con forma compatible con
    ``schemas.TRAYECTORIAS_POSTOP_SCHEMA`` (menos ``trayectoria_id``/``generado_ts``, que
    se agregan al persistir).
    """
    paciente_id = paciente_profile["paciente_id"]
    complicacion_encounter = bool(paciente_profile["complicacion_encounter"])

    rng_arquetipo = random.Random(config.stable_seed("trayectoria_arquetipo", paciente_id, seed))
    archetype = choose_archetype(complicacion_encounter, archetypes, rng_arquetipo)

    n = len(call_days)
    rows = []
    for idx, dia in enumerate(call_days):
        progress = idx / (n - 1) if n > 1 else 1.0
        rng_dia = random.Random(config.stable_seed("trayectoria_dia", paciente_id, dia, seed))
        vector = clinical_domains.sample_symptom_vector(archetype, progress, rng_dia)
        rows.append(
            {
                "paciente_id": paciente_id,
                "dia_postop": dia,
                "arquetipo_trayectoria": archetype,
                "seed": seed,
                **vector,
            }
        )
    return rows


def build_trayectorias_postop(spark, perfiles_pacientes_table: str, output_table: str, call_days: list[int]) -> None:
    """Aplica ``simulate_trajectory`` a todos los pacientes de
    ``perfiles_pacientes_table`` y escribe ``output_table``.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    cfg = config.load_config()
    archetypes = cfg["trajectories"]["archetypes"]
    seed = cfg["population"]["seed"]

    perfiles = [row.asDict() for row in spark.table(perfiles_pacientes_table).collect()]

    rows = []
    for perfil in perfiles:
        for fila in simulate_trajectory(perfil, call_days, archetypes, seed):
            rows.append(
                {
                    "trayectoria_id": f"tray_{fila['paciente_id']}_{fila['dia_postop']}",
                    "generado_ts": datetime.now(timezone.utc),
                    **fila,
                }
            )

    df = spark.createDataFrame(rows, schema=schemas.TRAYECTORIAS_POSTOP_SCHEMA)
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 1 §5.3 — simulador de trayectorias post-operatorias")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    call_days = cfg["trajectories"]["call_days"]

    perfiles_pacientes_table = config.table_fqn("silver", "perfiles_pacientes", cfg)
    output_table = config.table_fqn("silver", "trayectorias_postop", cfg)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    build_trayectorias_postop(
        spark=spark, perfiles_pacientes_table=perfiles_pacientes_table, output_table=output_table, call_days=call_days
    )


if __name__ == "__main__":
    main()
