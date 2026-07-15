"""Componente 4 — Simulación conversacional dual-LLM (Diseño Técnico §8).

Dos roles, cada uno con su propio system prompt (prompts/patient_system.md,
prompts/agent_system.md), ambos anclados al mismo caso clínico. Ninguno de los dos
LLMs ve el label ground-truth durante la generación (§8.1) — se adjunta como metadata
DESPUÉS de generar la transcripción, para no contaminar el lenguaje generado con la
clasificación (riesgo R4).

Orquestación (§8.2): Databricks Model Serving (``ai_query()``/``WorkspaceClient``) es el
camino primario — Databricks Free Edition restringe el egress de red a "un conjunto
limitado de dominios de confianza", así que llamadas directas a una API externa pueden
estar bloqueadas. La API externa vía Databricks Secret Scopes queda como fallback, sin
validar todavía contra un workspace real (riesgo R5, Plan 02) — nunca credenciales
hardcodeadas en ningún caso.

Nota de implementación (Plan 05): el cliente LLM real (``_default_client``) importa el
SDK de Databricks de forma diferida — no existe endpoint de Model Serving desplegado
todavía, así que ejecutar una llamada real queda fuera de alcance de este cambio (ver
Plan 05, "Explícitamente fuera de alcance"). La lógica de orquestación (prompts,
turnos, acumulación de tokens, checkpointing por caso) es real y se prueba con un
cliente falso inyectable (``patient_client``/``agent_client``).

Escribe: silver.dialogos_capa1_limpia (schemas.DIALOGOS_CAPA1_LIMPIA_SCHEMA, sql/ddl/20).
"""

from __future__ import annotations

import argparse
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from postop import config

PATIENT_STYLES = ["colaborativo", "evasivo", "ansioso", "minimizador_sintomas", "confundido"]  # §8.1

# Las 6 áreas del guion de seguimiento (prompts/agent_system.md) — una pregunta por turno.
FOLLOWUP_AREAS = ["dolor", "fiebre", "movilidad", "herida", "apetito", "sueno"]


@dataclass
class LLMTurnResult:
    texto: str
    prompt_tokens: int
    completion_tokens: int


LLMClientFn = Callable[[str, list[dict]], LLMTurnResult]


def _extract_template_block(markdown: str) -> str:
    """Extrae el primer bloque ```...``` de un prompt en prompts/*.md — la plantilla
    documentada es la fuente única de verdad (entregable §16: "prompts documentados").
    """
    match = re.search(r"```\n(.*?)\n```", markdown, re.DOTALL)
    if not match:
        raise ValueError("No se encontró un bloque de plantilla ``` ``` en el prompt")
    return match.group(1)


def _render_template(template: str, context: dict) -> str:
    def resolver(match: re.Match) -> str:
        value: object = context
        for part in match.group(1).strip().split("."):
            value = value[part]
        return str(value)

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", resolver, template)


def build_patient_prompt(caso: dict, estilo_paciente: str, prompts_dir: str = "prompts") -> str:
    """Construye el prompt del LLM-paciente a partir de ``prompts/patient_system.md``
    + el vector de síntomas del caso + el perfil colombiano + ``estilo_paciente``.
    El LLM-paciente NUNCA recibe el label (§8.1).
    """
    if estilo_paciente not in PATIENT_STYLES:
        raise ValueError(f"estilo_paciente inválido: {estilo_paciente!r} — debe ser uno de {PATIENT_STYLES}")

    template = _extract_template_block(Path(prompts_dir, "patient_system.md").read_text(encoding="utf-8"))
    context = {
        "perfil_colombia": caso["perfil_colombia"],
        "procedimiento": caso["procedimiento"],
        "dia_postop": caso["dia_postop"],
        "vector_sintomas": caso["vector_sintomas"],
        "estilo_paciente": estilo_paciente,
    }
    return _render_template(template, context)


def build_agent_prompt(prompts_dir: str = "prompts") -> str:
    """Construye el prompt del LLM-agente a partir de ``prompts/agent_system.md``.
    El LLM-agente solo recibe el guion de preguntas de seguimiento; tampoco conoce
    el label (§8.1).
    """
    return _extract_template_block(Path(prompts_dir, "agent_system.md").read_text(encoding="utf-8"))


def _default_client(model_serving_endpoint: str, secret_scope: str) -> LLMClientFn:
    def _call(system_prompt: str, history: list[dict]) -> LLMTurnResult:
        from databricks.sdk import WorkspaceClient  # import diferido — solo en el cluster

        client = WorkspaceClient()
        response = client.serving_endpoints.query(
            name=model_serving_endpoint,
            messages=[{"role": "system", "content": system_prompt}, *history],
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMTurnResult(
            texto=choice.message.content,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    return _call


def simulate_conversation(
    caso: dict,
    estilo_paciente: str,
    model_serving_endpoint: str,
    secret_scope: str,
    patient_client: Optional[LLMClientFn] = None,
    agent_client: Optional[LLMClientFn] = None,
) -> dict:
    """Orquesta el turno a turno LLM-agente <-> LLM-paciente para un caso clínico,
    cubriendo las 6 áreas de ``FOLLOWUP_AREAS``. Devuelve los turnos de la conversación +
    ``prompt_tokens``/``completion_tokens`` acumulados — el label se adjunta fuera de esta
    función, post-hoc (§8.1).

    ``patient_client``/``agent_client`` son inyectables para pruebas; por defecto ambos
    apuntan al mismo endpoint de Model Serving (``_default_client``, §8.2).
    """
    patient_client = patient_client or _default_client(model_serving_endpoint, secret_scope)
    agent_client = agent_client or patient_client

    patient_prompt = build_patient_prompt(caso, estilo_paciente)
    agent_prompt = build_agent_prompt()

    agent_history: list[dict] = []
    patient_history: list[dict] = []
    turnos: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for area in FOLLOWUP_AREAS:
        agent_history.append({"role": "user", "content": f"Pregunta de seguimiento sobre: {area}"})
        agent_result = agent_client(agent_prompt, agent_history)
        agent_history.append({"role": "assistant", "content": agent_result.texto})
        turnos.append({"turno_idx": len(turnos), "hablante": "agente", "texto": agent_result.texto})
        total_prompt_tokens += agent_result.prompt_tokens
        total_completion_tokens += agent_result.completion_tokens

        patient_history.append({"role": "user", "content": agent_result.texto})
        patient_result = patient_client(patient_prompt, patient_history)
        patient_history.append({"role": "assistant", "content": patient_result.texto})
        turnos.append({"turno_idx": len(turnos), "hablante": "paciente", "texto": patient_result.texto})
        total_prompt_tokens += patient_result.prompt_tokens
        total_completion_tokens += patient_result.completion_tokens

    return {"turnos": turnos, "prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens}


def run_dual_llm_batch(
    spark,
    casos_table: str,
    output_table: str,
    model_serving_endpoint: str,
    secret_scope: str,
) -> None:
    """Distribuye ``simulate_conversation`` sobre los casos de ``casos_table``, con
    checkpointing por caso (``MERGE`` idempotente por ``caso_id``-derivado ``dialogo_id``,
    §8.2) — un fallo a mitad de batch no obliga a re-generar los casos ya escritos.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    cfg = config.load_config()
    perfiles_table = config.table_fqn("silver", "perfiles_pacientes", cfg)
    perfiles_co_table = config.table_fqn("silver", "perfiles_pacientes_co", cfg)

    casos_rows = [row.asDict() for row in spark.table(casos_table).collect()]
    perfiles = {row["paciente_id"]: row.asDict() for row in spark.table(perfiles_table).collect()}
    perfiles_co = {row["paciente_id"]: row.asDict() for row in spark.table(perfiles_co_table).collect()}

    rng = random.Random(config.stable_seed("dual_llm_estilo", casos_table))

    for caso_row in casos_rows:
        paciente_id = caso_row["paciente_id"]
        # perfil_colombia combina la geografía/identidad de perfiles_pacientes_co (§6) con
        # la edad, que solo vive en perfiles_pacientes (§5) — ambas hacen falta en el
        # prompt del LLM-paciente (prompts/patient_system.md: nombre_completo, edad).
        caso = {
            "caso_id": caso_row["caso_id"],
            "paciente_id": paciente_id,
            "dia_postop": caso_row["dia_postop"],
            "label": caso_row["label"],
            "procedimiento": perfiles[paciente_id]["procedimiento"],
            "perfil_colombia": {**perfiles_co[paciente_id], "edad": perfiles[paciente_id]["edad"]},
            "vector_sintomas": {k: caso_row[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")},
        }
        estilo_paciente = rng.choice(PATIENT_STYLES)
        resultado = simulate_conversation(caso, estilo_paciente, model_serving_endpoint, secret_scope)

        rows = [
            {
                "dialogo_id": f"dlg_{caso['caso_id']}_{turno['turno_idx']}",
                "caso_id": caso["caso_id"],
                "paciente_id": caso["paciente_id"],
                "dia_postop": caso["dia_postop"],
                "turno_idx": turno["turno_idx"],
                "hablante": turno["hablante"],
                "texto": turno["texto"],
                "label_ground_truth": caso["label"],
                "estilo_paciente": estilo_paciente,
                "modelo_paciente": model_serving_endpoint,
                "modelo_agente": model_serving_endpoint,
                "prompt_tokens": resultado["prompt_tokens"] if turno["hablante"] == "paciente" else None,
                "completion_tokens": resultado["completion_tokens"] if turno["hablante"] == "paciente" else None,
                "generado_ts": datetime.now(timezone.utc),
            }
            for turno in resultado["turnos"]
        ]

        df_nuevo = spark.createDataFrame(rows, schema=schemas.DIALOGOS_CAPA1_LIMPIA_SCHEMA)
        df_nuevo.createOrReplaceTempView("_staging_dialogo")
        spark.sql(
            f"""
            MERGE INTO {output_table} AS destino
            USING _staging_dialogo AS origen
            ON destino.dialogo_id = origen.dialogo_id
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
            """
        )


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 4 — simulación conversacional dual-LLM")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    parser.add_argument("--model-serving-endpoint", required=True, help="Endpoint de Databricks Model Serving (§8.2) — camino primario en Free Edition")
    parser.add_argument("--secret-scope", required=True, help="Databricks Secret Scope con credenciales del LLM externo (§8.2, §13) — fallback sin validar en Free Edition, riesgo R5")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    casos_table = config.table_fqn("silver", "casos_clinicos_etiquetados", cfg)
    output_table = config.table_fqn("silver", "dialogos_capa1_limpia", cfg)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    run_dual_llm_batch(
        spark=spark,
        casos_table=casos_table,
        output_table=output_table,
        model_serving_endpoint=args.model_serving_endpoint,
        secret_scope=args.secret_scope,
    )


if __name__ == "__main__":
    main()
