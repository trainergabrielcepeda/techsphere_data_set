"""Componente 5 — Inyector de ruido, Capa 2 (Diseño Técnico §9).

UDF de Spark parametrizable por ``intensidad`` (1-5), aplicada sobre
``silver.dialogos_capa1_limpia`` — NUNCA in-place, Capa 1 es inmutable una vez
generada. Cada transformación de ruido escribe una fila de trazabilidad en
``silver.noise_mapping_log`` (§9.2) — entregable obligatorio de la ficha (§6):
"Documentación de mapeo Capa 1 → Capa 2".

``label_ground_truth`` se hereda sin cambios desde Capa 1: el ruido afecta la
conversación, nunca el label.

Nota de implementación (Plan 05) — split de la taxonomía §9.1: la firma de
``inject_noise_udf`` (texto-en / texto-en, fijada por el diseño) no puede añadir o quitar
filas. Por eso 5 de los 6 tipos de ruido mutan el texto del turno tal cual llega
(incluyendo ``informacion_faltante``, implementado aquí como el turno "vaciándose" en una
muletilla/silencio en vez de contener la respuesta real — más fiel a cómo se ve la
información faltante en una transcripción real que borrar la fila) y solo
``cambio_interlocutor`` es estructural: inserta una fila adicional con
``hablante='tercero'``, manejado directamente en ``inject_noise_batch``/
``inject_noise_into_turnos``, no dentro de la UDF.

Escribe:
  - silver.dialogos_capa2_ruidosa (schemas.DIALOGOS_CAPA2_RUIDOSA_SCHEMA, sql/ddl/21)
  - silver.noise_mapping_log      (schemas.NOISE_MAPPING_LOG_SCHEMA, sql/ddl/22)
"""

from __future__ import annotations

import argparse
import random
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

# Taxonomía de ruido (§9.1)
NOISE_TYPES = [
    "ruido_stt",
    "modismo_regional",
    "respuesta_ambigua",
    "contradiccion",
    "informacion_faltante",
    "cambio_interlocutor",
]

TEXT_MUTATING_NOISE_TYPES = ["ruido_stt", "modismo_regional", "respuesta_ambigua", "contradiccion", "informacion_faltante"]
STRUCTURAL_NOISE_TYPES = ["cambio_interlocutor"]

# Nivel típico por tipo de ruido (§9.1, tabla de taxonomía) — usado para no aplicar un
# tipo de ruido fuera de su rango de intensidad esperado.
NOISE_TYPE_INTENSITY_RANGE = {
    "ruido_stt": (1, 5),
    "modismo_regional": (1, 3),
    "respuesta_ambigua": (2, 4),
    "contradiccion": (3, 5),
    "informacion_faltante": (2, 5),
    "cambio_interlocutor": (3, 5),
}

MODISMO_MAP = {
    "mucho dolor": "durísimo",
    "dolor intenso": "un dolor verraco",
    "estoy bien": "estoy bacano",
    "no sé": "no le sé decir",
    "muy mal": "muy jodido",
}

AMBIGUOUS_POOL = [
    "Pues no sé, más o menos.",
    "Ahí vamos, no le podría decir con seguridad.",
    "Digamos que sí, pero no tanto.",
    "No me acuerdo bien, la verdad.",
    "Puede ser, no estoy seguro.",
]

CONTRADICTION_POOL = [
    "Espere, en realidad no, creo que sí me duele bastante.",
    "Bueno, eso dije, pero ayer le dije lo contrario.",
    "No, olvide lo que dije, es al revés.",
]

MISSING_INFO_FILLERS = [
    "...",
    "Ay, no sé, se me olvidó lo que iba a decir.",
    "Este... no, nada, siga con la otra pregunta.",
    "[silencio]",
]

THIRD_PARTY_INTERJECTIONS = [
    "Perdón, soy la hija, él no escucha muy bien, ¿le puedo ayudar a responder?",
    "Disculpe, soy el cuidador, permítame contarle cómo lo he visto estos días.",
    "Hola, habla la esposa, él está descansando, yo le cuento.",
]


def _eligible_noise_types(intensidad: int) -> list[str]:
    return [t for t, (lo, hi) in NOISE_TYPE_INTENSITY_RANGE.items() if lo <= intensidad <= hi]


def _stt_corrupt(texto: str, intensidad: int, rng: random.Random) -> str:
    palabras = texto.split(" ")
    p = min(0.9, 0.06 * intensidad)
    out = []
    for palabra in palabras:
        if palabra and rng.random() < p:
            if len(palabra) > 3 and rng.random() < 0.5:
                corte = rng.randint(2, len(palabra) - 1)
                out.append(palabra[:corte] + "-")
            else:
                out.append("[inaudible]")
        else:
            out.append(palabra)
    return " ".join(out)


def _modismo(texto: str, intensidad: int, rng: random.Random) -> str:
    resultado = texto
    aplicados = 0
    max_aplicados = min(len(MODISMO_MAP), 1 + intensidad // 2)
    for original, modismo in MODISMO_MAP.items():
        if aplicados >= max_aplicados:
            break
        if original in resultado.lower() and rng.random() < 0.5 + 0.1 * intensidad:
            resultado = resultado.replace(original, modismo)
            aplicados += 1
    if aplicados == 0:
        resultado = f"{resultado} {rng.choice(['parcero', 'pues', 'ome'])}"
    return resultado


def _ambigua(texto: str, intensidad: int, rng: random.Random) -> str:
    frase = rng.choice(AMBIGUOUS_POOL)
    if intensidad >= 4:
        return frase
    return f"{texto} ... {frase}"


def _contradiccion(texto: str, intensidad: int, rng: random.Random) -> str:
    return f"{texto} {rng.choice(CONTRADICTION_POOL)}"


def _informacion_faltante(texto: str, intensidad: int, rng: random.Random) -> str:
    return rng.choice(MISSING_INFO_FILLERS)


_TEXT_MUTATORS = {
    "ruido_stt": _stt_corrupt,
    "modismo_regional": _modismo,
    "respuesta_ambigua": _ambigua,
    "contradiccion": _contradiccion,
    "informacion_faltante": _informacion_faltante,
}


def inject_noise_udf(texto: str, tipo_ruido: str, intensidad: int, seed: int) -> str:
    """Aplica una transformación de ``tipo_ruido`` (uno de ``TEXT_MUTATING_NOISE_TYPES``)
    a ``intensidad`` (1-5) sobre un turno de diálogo. Determinística por ``seed`` para
    reproducibilidad (§9.1, §9.2).
    """
    if tipo_ruido not in TEXT_MUTATING_NOISE_TYPES:
        raise ValueError(
            f"{tipo_ruido!r} no es un tipo de ruido a nivel de texto — ver STRUCTURAL_NOISE_TYPES"
        )
    if not 1 <= intensidad <= 5:
        raise ValueError("intensidad debe estar entre 1 y 5")

    rng = random.Random(config.stable_seed("inject_noise_udf", texto, tipo_ruido, intensidad, seed))
    return _TEXT_MUTATORS[tipo_ruido](texto, intensidad, rng)


def _mapping_row(
    dialogo_id_capa1: str,
    dialogo_id_capa2: str,
    turno_idx_afectado: int,
    tipo_ruido: str,
    intensidad: int,
    texto_original: str,
    texto_ruidoso: str,
    seed: int,
    aplicado_ts: datetime,
) -> dict:
    return {
        "mapping_id": f"map_{dialogo_id_capa2}_{turno_idx_afectado}_{tipo_ruido}",
        "dialogo_id_capa1": dialogo_id_capa1,
        "dialogo_id_capa2": dialogo_id_capa2,
        "turno_idx_afectado": turno_idx_afectado,
        "tipo_ruido": tipo_ruido,
        "intensidad": intensidad,
        "texto_original": texto_original,
        "texto_ruidoso": texto_ruidoso,
        "seed": seed,
        "aplicado_ts": aplicado_ts,
    }


def inject_noise_into_turnos(turnos: list[dict], intensidad: int, seed: int) -> tuple[list[dict], list[dict]]:
    """Aplica ruido a los turnos de UN caso/día (``dialogos_capa1_limpia`` agrupado por
    ``caso_id`` + ``dia_postop``, ya ordenados por ``turno_idx``).

    Devuelve ``(turnos_capa2, mapping_log_rows)``. Nunca in-place — ``turnos`` (Capa 1)
    no se modifica. Cada turno afectado por una transformación de ruido produce
    exactamente una fila en ``mapping_log_rows`` (§9.2); los turnos no afectados se
    copian sin cambios, con ``intensidad_ruido = None``.
    """
    tipos_elegibles = _eligible_noise_types(intensidad)
    aplicado_ts = datetime.now(timezone.utc)

    salida: list[dict] = []
    mapping_rows: list[dict] = []

    for turno in turnos:
        dialogo_id_capa1 = turno["dialogo_id"]
        dialogo_id_capa2 = f"{dialogo_id_capa1}_c2"
        base = {
            "dialogo_id": dialogo_id_capa2,
            "dialogo_id_capa1": dialogo_id_capa1,
            "caso_id": turno["caso_id"],
            "paciente_id": turno["paciente_id"],
            "dia_postop": turno["dia_postop"],
            "turno_idx": turno["turno_idx"],
            "hablante": turno["hablante"],
            "texto": turno["texto"],
            "label_ground_truth": turno["label_ground_truth"],
            "estilo_paciente": turno["estilo_paciente"],
            "modelo_paciente": turno["modelo_paciente"],
            "modelo_agente": turno["modelo_agente"],
            "intensidad_ruido": None,
            "generado_ts": datetime.now(timezone.utc),
        }

        rng_seleccion = random.Random(config.stable_seed("inject_noise_seleccion", dialogo_id_capa1, seed))
        p_afectado = min(0.9, 0.15 * intensidad)
        if not tipos_elegibles or rng_seleccion.random() >= p_afectado:
            salida.append(base)
            continue

        tipo_ruido = rng_seleccion.choice(tipos_elegibles)
        texto_original = turno["texto"]

        if tipo_ruido == "cambio_interlocutor":
            # El turno original queda intacto (su texto no cambia); lo que se marca como
            # afectado es la fila insertada del tercero, que es la que representa el ruido.
            salida.append(base)
            tercero_texto = rng_seleccion.choice(THIRD_PARTY_INTERJECTIONS)
            dialogo_id_tercero = f"{dialogo_id_capa1}_c2_tercero"
            salida.append(
                {
                    **base,
                    "dialogo_id": dialogo_id_tercero,
                    "hablante": "tercero",
                    "texto": tercero_texto,
                    "intensidad_ruido": intensidad,
                }
            )
            mapping_rows.append(
                _mapping_row(
                    dialogo_id_capa1, dialogo_id_tercero, turno["turno_idx"], tipo_ruido, intensidad,
                    texto_original, tercero_texto, seed, aplicado_ts,
                )
            )
            continue

        texto_ruidoso = inject_noise_udf(texto_original, tipo_ruido, intensidad, seed)
        salida.append({**base, "texto": texto_ruidoso, "intensidad_ruido": intensidad})
        mapping_rows.append(
            _mapping_row(
                dialogo_id_capa1, dialogo_id_capa2, turno["turno_idx"], tipo_ruido, intensidad,
                texto_original, texto_ruidoso, seed, aplicado_ts,
            )
        )

    for nuevo_idx, fila in enumerate(salida):
        fila["turno_idx"] = nuevo_idx

    return salida, mapping_rows


def inject_noise_batch(
    spark,
    capa1_table: str,
    output_table: str,
    mapping_log_table: str,
    intensidad: int,
    seed: int,
) -> None:
    """Aplica ``inject_noise_into_turnos`` sobre ``capa1_table`` (nunca in-place),
    agrupando por (``caso_id``, ``dia_postop``); escribe ``output_table`` (Capa 2) y
    ``mapping_log_table``.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    capa1_rows = [
        row.asDict()
        for row in spark.table(capa1_table).orderBy("caso_id", "dia_postop", "turno_idx").collect()
    ]

    agrupado: dict[tuple, list[dict]] = {}
    for row in capa1_rows:
        clave = (row["caso_id"], row["dia_postop"])
        agrupado.setdefault(clave, []).append(row)

    capa2_rows: list[dict] = []
    mapping_rows: list[dict] = []
    for turnos in agrupado.values():
        salida, mapeos = inject_noise_into_turnos(turnos, intensidad, seed)
        capa2_rows.extend(salida)
        mapping_rows.extend(mapeos)

    df_capa2 = spark.createDataFrame(capa2_rows, schema=schemas.DIALOGOS_CAPA2_RUIDOSA_SCHEMA)
    df_capa2.write.format("delta").mode("overwrite").saveAsTable(output_table)

    df_mapping = spark.createDataFrame(mapping_rows, schema=schemas.NOISE_MAPPING_LOG_SCHEMA)
    df_mapping.write.format("delta").mode("overwrite").saveAsTable(mapping_log_table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 5 — inyector de ruido parametrizable")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    parser.add_argument("--intensidad", type=int, default=3, choices=range(1, 6), help="Intensidad de ruido 1-5 (§9.1)")
    parser.add_argument("--seed", type=int, default=42, help="Seed para reproducibilidad determinística (§9.2)")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    capa1_table = config.table_fqn("silver", "dialogos_capa1_limpia", cfg, catalog_override=args.catalog)
    output_table = config.table_fqn("silver", "dialogos_capa2_ruidosa", cfg, catalog_override=args.catalog)
    mapping_log_table = config.table_fqn("silver", "noise_mapping_log", cfg, catalog_override=args.catalog)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    inject_noise_batch(
        spark=spark,
        capa1_table=capa1_table,
        output_table=output_table,
        mapping_log_table=mapping_log_table,
        intensidad=args.intensidad,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
