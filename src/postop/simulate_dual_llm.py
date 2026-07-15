"""Componente 4 — Simulación conversacional dual-LLM (Diseño Técnico §8).

Dos roles, cada uno con su propio system prompt (prompts/patient_system.md,
prompts/agent_system.md), ambos anclados al mismo caso clínico. Ninguno de los dos
LLMs ve el label ground-truth durante la generación (§8.1) — se adjunta como metadata
DESPUÉS de generar la transcripción, para no contaminar el lenguaje generado con la
clasificación (riesgo R4).

Orquestación (§8.2, revisado Plan 06): OpenRouter (API externa vía Databricks Secret
Scopes, riesgo R5) es el camino primario — validado contra el workspace real en Plan 06
Fase 0: el egress desde Free Edition serverless hacia openrouter.ai funciona, y modelos
``:free`` reservan capacidad limitada por proveedor upstream (se satura rápido en modelos
populares — confirmado empíricamente, no solo el límite de cuenta de 20 req/min y
50-o-1000 req/día de OpenRouter). Databricks Model Serving (``_default_client``) queda
como segundo camino, sin validar todavía si Free Edition expone un endpoint foundation-
model consultable — no es el que usa esta implementación. Nunca credenciales
hardcodeadas en ningún caso; la API key de OpenRouter vive en el Secret Scope
(``--secret-scope``, clave ``openrouter-api-key``).

Nota de implementación (Plan 06): ``_openrouter_client`` fija un modelo primario
(``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`` por defecto — el único, junto con
el auto-router, que respondió sin 429 en la Fase 0) y recae en ``openrouter/free`` (el
auto-router de OpenRouter) si el primario agota sus reintentos — el auto-throttling y el
backoff con reintentos se probaron contra fallos 429 reales del proveedor, no solo
simulados. La lógica de orquestación (prompts, turnos, acumulación de tokens,
checkpointing por caso, y ahora el filtro de casos ya procesados para reanudar una corrida
truncada por cuota) es real y se prueba con un cliente falso inyectable
(``patient_client``/``agent_client``) más un doble de la capa HTTP para el cliente real.

Escribe: silver.dialogos_capa1_limpia (schemas.DIALOGOS_CAPA1_LIMPIA_SCHEMA, sql/ddl/20).
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# Databricks ejecuta este archivo como spark_python_task suelto (python_file, sin
# empaquetar como wheel — §11) — src/ no queda en sys.path por su cuenta, confirmado al
# correr el job real en Plan 06 Fase 4 (ModuleNotFoundError: No module named 'postop').
# __file__ tampoco existe en este contexto: Databricks ejecuta el script vía
# exec(compile(source, filename, 'exec')), que no inyecta __file__ en los globals —
# también confirmado contra el workspace real (NameError: name '__file__' is not
# defined). sys._getframe().f_code.co_filename sí lo tiene, vía co_filename del compile().
_this_file = sys._getframe().f_code.co_filename
sys.path.insert(0, str(Path(_this_file).resolve().parents[1]))

# prompts/ resuelto contra la raíz del repo, no relativo al cwd del proceso — el cwd de
# un spark_python_task en Databricks no es la raíz del repo (a diferencia de pytest local,
# que sí corre desde ahí), confirmado contra el workspace real: build_patient_prompt con
# el default anterior ("prompts", relativo) lanzaba FileNotFoundError en la primera
# corrida real de este task (Plan 06 Fase 4).
_DEFAULT_PROMPTS_DIR = str(Path(_this_file).resolve().parents[2] / "prompts")

from postop import config

PATIENT_STYLES = ["colaborativo", "evasivo", "ansioso", "minimizador_sintomas", "confundido"]  # §8.1

# Las 6 áreas del guion de seguimiento (prompts/agent_system.md) — una pregunta por turno.
FOLLOWUP_AREAS = ["dolor", "fiebre", "movilidad", "herida", "apetito", "sueno"]

# Camino primario OpenRouter (§8.2, Plan 06) — elegido en la Fase 0 tras probar 6
# candidatos ":free" contra el catálogo real: fue, junto con OPENROUTER_FALLBACK_MODEL,
# el único que respondió sin 429 de saturación upstream. Este pin es una foto del
# 2026-07-15 — el catálogo ":free" de OpenRouter cambia; re-verificar antes de asumirlo
# vigente en una corrida futura.
OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
# Auto-router de OpenRouter — recae aquí cuando el modelo primario agota sus reintentos.
OPENROUTER_FALLBACK_MODEL = "openrouter/free"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
# Margen bajo el límite de cuenta de 20 req/min de OpenRouter (confirmado en Fase 0) —
# insurance barata incluso cuando el 429 real termina viniendo de saturación del
# proveedor upstream, no de este límite.
OPENROUTER_MIN_INTERVAL_S = 4.0
OPENROUTER_MAX_ATTEMPTS_PER_MODEL = 4


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


def build_patient_prompt(caso: dict, estilo_paciente: str, prompts_dir: str = _DEFAULT_PROMPTS_DIR) -> str:
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


def build_agent_prompt(prompts_dir: str = _DEFAULT_PROMPTS_DIR) -> str:
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


class _OpenRouterRetriesExhausted(RuntimeError):
    """Un modelo agotó sus reintentos ante 429/5xx — señal para que el llamador pruebe el
    modelo de fallback antes de fallar la llamada por completo."""


class _RequestPacer:
    """Autolimita la tasa de llamadas salientes a un intervalo mínimo entre solicitudes —
    insurance barata contra el límite de 20 req/min de cuenta de OpenRouter (Plan 06 Fase
    0), independiente de si el 429 real termina viniendo de ese límite o de saturación del
    proveedor upstream (el caso más común observado en la Fase 0 para modelos populares).
    """

    def __init__(self, min_interval_s: float):
        self._min_interval_s = min_interval_s
        self._last_call_monotonic: Optional[float] = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_call_monotonic is not None:
            remaining = self._min_interval_s - (now - self._last_call_monotonic)
            if remaining > 0:
                time.sleep(remaining)
        self._last_call_monotonic = time.monotonic()


def _extract_retry_after_seconds(error_body: str) -> Optional[float]:
    """OpenRouter no manda el header ``Retry-After`` en los 429 de saturación upstream
    (confirmado empíricamente, Plan 06 Fase 0) — el valor vive en
    ``error.metadata.retry_after_seconds`` dentro del cuerpo JSON de la respuesta.
    """
    try:
        return float(json.loads(error_body)["error"]["metadata"]["retry_after_seconds"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _http_post_json(url: str, headers: dict, payload: dict, timeout: int = 60) -> dict:
    """POST JSON real vía stdlib (sin dependencia extra) — aislado en su propia función
    para poder sustituirlo en pruebas por un doble que levanta ``urllib.error.HTTPError``
    igual que una llamada real, así la lógica de reintento se prueba sin red.
    """
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _openrouter_request(
    model: str,
    system_prompt: str,
    history: list[dict],
    api_key: str,
    pacer: _RequestPacer,
    max_attempts: int,
) -> dict:
    """Llama a OpenRouter con auto-throttling + reintentos con backoff. Confirmado contra
    fallos reales en Plan 06 Fase 0: los 429 "temporarily rate-limited upstream" son la
    norma para modelos ``:free`` populares, no la excepción — se reintentan honrando
    ``retry_after_seconds`` cuando el proveedor lo da, si no con backoff exponencial +
    jitter. Errores 4xx que no son 429 (auth inválida, payload malformado) fallan de
    inmediato: reintentar no los arregla y enmascararía el problema real.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/postop-dataset",
        "X-Title": "postop-dataset-simulate-dual-llm",
    }
    payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}, *history]}

    last_status: Optional[int] = None
    last_body: str = ""
    for attempt in range(max_attempts):
        pacer.wait()
        try:
            return _http_post_json(OPENROUTER_CHAT_URL, headers, payload)
        except urllib.error.HTTPError as e:
            last_status = e.code
            last_body = e.read().decode("utf-8", errors="replace")
            if last_status != 429 and not (500 <= last_status < 600):
                raise RuntimeError(
                    f"OpenRouter rechazó la solicitud (no reintentable), modelo={model}, "
                    f"status={last_status}: {last_body}"
                ) from e
            if attempt == max_attempts - 1:
                break
            retry_after = _extract_retry_after_seconds(last_body)
            sleep_s = retry_after if retry_after is not None else min(5 * (2**attempt), 60)
            time.sleep(sleep_s + random.uniform(0, 1))

    raise _OpenRouterRetriesExhausted(
        f"modelo={model} agotó {max_attempts} intentos, último status={last_status}: {last_body}"
    )


def _openrouter_client(
    model: str,
    secret_scope: str,
    secret_key: str = "openrouter-api-key",
    fallback_model: str = OPENROUTER_FALLBACK_MODEL,
    min_interval_s: float = OPENROUTER_MIN_INTERVAL_S,
    max_attempts_per_model: int = OPENROUTER_MAX_ATTEMPTS_PER_MODEL,
) -> LLMClientFn:
    """Camino externo primario vía OpenRouter (§8.2, riesgo R5 — validado en Plan 06 Fase
    0 contra el workspace real: el egress funciona, modelos ``:free`` populares se saturan
    rápido). Modelo fijo (``model``) por consistencia de calidad del dataset; ante
    agotamiento de reintentos recae en ``fallback_model`` (el auto-router
    ``openrouter/free``) antes de fallar la llamada por completo — la Fase 0 mostró al
    auto-router respondiendo en el mismo momento en que varios modelos fijos daban 429.
    """
    from databricks.sdk import WorkspaceClient  # import diferido — solo en el cluster

    secret = WorkspaceClient().secrets.get_secret(scope=secret_scope, key=secret_key)
    api_key = base64.b64decode(secret.value).decode("utf-8")
    pacer = _RequestPacer(min_interval_s)

    def _call(system_prompt: str, history: list[dict]) -> LLMTurnResult:
        try:
            data = _openrouter_request(model, system_prompt, history, api_key, pacer, max_attempts_per_model)
        except _OpenRouterRetriesExhausted:
            data = _openrouter_request(fallback_model, system_prompt, history, api_key, pacer, max_attempts_per_model)
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return LLMTurnResult(
            texto=choice["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
        )

    return _call


def _build_default_client(
    llm_provider: str,
    model_serving_endpoint: str,
    secret_scope: str,
    openrouter_model: str,
) -> LLMClientFn:
    if llm_provider == "openrouter":
        return _openrouter_client(openrouter_model, secret_scope)
    if llm_provider == "databricks":
        return _default_client(model_serving_endpoint, secret_scope)
    raise ValueError(f"llm_provider inválido: {llm_provider!r} — debe ser 'openrouter' o 'databricks'")


def simulate_conversation(
    caso: dict,
    estilo_paciente: str,
    model_serving_endpoint: str,
    secret_scope: str,
    llm_provider: str = "openrouter",
    openrouter_model: str = OPENROUTER_DEFAULT_MODEL,
    patient_client: Optional[LLMClientFn] = None,
    agent_client: Optional[LLMClientFn] = None,
) -> dict:
    """Orquesta el turno a turno LLM-agente <-> LLM-paciente para un caso clínico,
    cubriendo las 6 áreas de ``FOLLOWUP_AREAS``. Devuelve los turnos de la conversación +
    ``prompt_tokens``/``completion_tokens`` acumulados — el label se adjunta fuera de esta
    función, post-hoc (§8.1).

    ``patient_client``/``agent_client`` son inyectables para pruebas; por defecto ambos
    apuntan al mismo proveedor (``llm_provider`` — ``"openrouter"`` primario desde Plan 06,
    ``"databricks"`` vía Model Serving sin validar en Free Edition, §8.2).
    """
    patient_client = patient_client or _build_default_client(llm_provider, model_serving_endpoint, secret_scope, openrouter_model)
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


def _casos_pendientes(casos_rows: list[dict], caso_ids_ya_procesados: set) -> list[dict]:
    """Filtra los casos cuyo ``caso_id`` ya está en ``output_table`` (Plan 06 Fase 1).

    Sin este filtro, una segunda invocación de ``run_dual_llm_batch`` — necesaria porque
    la cuota diaria de OpenRouter no alcanza para un piloto completo en un solo día,
    ver Plan 06 Fase 4 — vuelve a gastar llamadas LLM ya pagadas en la corrida anterior:
    el ``MERGE`` hace que la tabla de salida no duplique filas, pero no evita
    re-simular. El checkpointing real está aquí, no solo en el MERGE.
    """
    return [caso for caso in casos_rows if caso["caso_id"] not in caso_ids_ya_procesados]


def run_dual_llm_batch(
    spark,
    catalog: str,
    casos_table: str,
    output_table: str,
    model_serving_endpoint: str,
    secret_scope: str,
    llm_provider: str = "openrouter",
    openrouter_model: str = OPENROUTER_DEFAULT_MODEL,
) -> None:
    """Distribuye ``simulate_conversation`` sobre los casos de ``casos_table``, con
    checkpointing por caso (``MERGE`` idempotente por ``caso_id``-derivado ``dialogo_id``,
    §8.2, más el filtro de ``_casos_pendientes`` — Plan 06) — un fallo o corte a mitad de
    batch (incluida una corrida truncada por cuota de OpenRouter) no obliga a re-generar
    ni re-pagar los casos ya escritos.

    ``catalog`` (Plan 06 Fase 4): resuelve ``perfiles_table``/``perfiles_co_table`` contra
    el catálogo real de la corrida, no el default de conf/project.yml — sin esto, esta
    función escribía hacia ``casos_table``/``output_table`` (ya resueltos correctamente
    por el llamador) pero LEÍA perfiles desde el catálogo equivocado, encontrado al correr
    el job real contra ``postop_dataset_dev``.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    cfg = config.load_config()
    perfiles_table = config.table_fqn("silver", "perfiles_pacientes", cfg, catalog_override=catalog)
    perfiles_co_table = config.table_fqn("silver", "perfiles_pacientes_co", cfg, catalog_override=catalog)

    casos_rows = [row.asDict() for row in spark.table(casos_table).collect()]
    caso_ids_ya_procesados = {row["caso_id"] for row in spark.table(output_table).select("caso_id").distinct().collect()}
    casos_rows = _casos_pendientes(casos_rows, caso_ids_ya_procesados)
    perfiles = {row["paciente_id"]: row.asDict() for row in spark.table(perfiles_table).collect()}
    perfiles_co = {row["paciente_id"]: row.asDict() for row in spark.table(perfiles_co_table).collect()}

    rng = random.Random(config.stable_seed("dual_llm_estilo", casos_table))
    # Etiqueta de proveniencia para modelo_paciente/modelo_agente (§16) — el modelo
    # realmente fijado; si _openrouter_client recae en OPENROUTER_FALLBACK_MODEL a mitad
    # de una llamada puntual (Plan 06 Fase 1), esa columna sigue reflejando el primario
    # configurado para la corrida, no el fallback puntual de un turno aislado.
    modelo_configurado = openrouter_model if llm_provider == "openrouter" else model_serving_endpoint

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
        resultado = simulate_conversation(
            caso, estilo_paciente, model_serving_endpoint, secret_scope, llm_provider, openrouter_model
        )

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
                "modelo_paciente": modelo_configurado,
                "modelo_agente": modelo_configurado,
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
    parser.add_argument(
        "--llm-provider",
        choices=["openrouter", "databricks"],
        default="openrouter",
        help="Proveedor LLM — 'openrouter' (Plan 06, validado contra el workspace real en Fase 0) por defecto; 'databricks' vía Model Serving, sin validar en Free Edition",
    )
    parser.add_argument(
        "--openrouter-model",
        default=OPENROUTER_DEFAULT_MODEL,
        help="Modelo ':free' primario en OpenRouter (usado solo si --llm-provider=openrouter) — recae automáticamente en openrouter/free si agota sus reintentos",
    )
    parser.add_argument(
        "--model-serving-endpoint",
        default="",
        help="Endpoint de Databricks Model Serving (§8.2) — usado solo si --llm-provider=databricks",
    )
    parser.add_argument("--secret-scope", required=True, help="Databricks Secret Scope con la credencial del LLM externo (§8.2, §13) — clave 'openrouter-api-key' para el camino OpenRouter")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    casos_table = config.table_fqn("silver", "casos_clinicos_etiquetados", cfg, catalog_override=args.catalog)
    output_table = config.table_fqn("silver", "dialogos_capa1_limpia", cfg, catalog_override=args.catalog)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    run_dual_llm_batch(
        spark=spark,
        catalog=args.catalog,
        casos_table=casos_table,
        output_table=output_table,
        model_serving_endpoint=args.model_serving_endpoint,
        secret_scope=args.secret_scope,
        llm_provider=args.llm_provider,
        openrouter_model=args.openrouter_model,
    )


if __name__ == "__main__":
    main()
