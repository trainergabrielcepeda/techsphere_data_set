"""Pruebas del cliente OpenRouter, el cliente Anthropic y el checkpointing por cuota
(Componente 4, Plan 06, extendido Plan 07/08).

No cubre ``_openrouter_client``/``_default_client``/``_anthropic_client`` en sí — los tres
importan ``databricks.sdk`` de forma diferida (solo disponible en el cluster) para leer el
secreto real, el mismo límite de testabilidad que ya existía para ``_default_client``
antes de este plan. Lo que sí se prueba sin red ni SDK: el filtro de reanudación, la
lógica de reintento/backoff/fallback contra un doble de la capa HTTP, la extracción del
hint de reintento, el mapeo de la forma de respuesta de Anthropic
(``_parse_anthropic_response``, una función pura), y el despacho de proveedor/parámetros
en ``_build_default_client`` contra dobles inyectados.
"""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from postop import simulate_dual_llm as sdl


def _http_error(status: int, body: dict) -> urllib.error.HTTPError:
    payload = json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(sdl.OPENROUTER_CHAT_URL, status, "error", None, io.BytesIO(payload))


def _caso_fixture():
    return {
        "caso_id": "caso1",
        "paciente_id": "pac1",
        "dia_postop": 3,
        "label": "amarillo",
        "procedimiento": "colecistectomía laparoscópica",
        "perfil_colombia": {"nombre_completo": "María Fernanda Rojas", "edad": 58},
        "vector_sintomas": {
            "dolor_nrs": 6,
            "fiebre_c": 37.8,
            "movilidad": "limitada",
            "herida": "leve enrojecimiento",
            "apetito": "reducido",
            "sueno": "interrumpido",
        },
    }


def test_build_patient_prompt_usa_prompts_dir_absoluto_por_defecto():
    # Regresión de un bug real (Plan 06 Fase 4): el default anterior era la cadena
    # relativa "prompts", que solo funciona si el cwd del proceso es la raíz del repo
    # (cierto para pytest local, falso para un spark_python_task real en Databricks) —
    # lanzaba FileNotFoundError en la primera corrida real de simulate_dual_llm.
    prompt = sdl.build_patient_prompt(_caso_fixture(), "ansioso")
    assert "María Fernanda Rojas" in prompt
    assert "ansioso" in prompt


def test_build_patient_prompt_nunca_incluye_el_label():
    prompt = sdl.build_patient_prompt(_caso_fixture(), "colaborativo")
    assert "amarillo" not in prompt


def test_build_agent_prompt_usa_prompts_dir_absoluto_por_defecto():
    prompt = sdl.build_agent_prompt()
    assert "Dolor" in prompt
    assert "diagnóstico" in prompt


def test_casos_pendientes_excluye_ids_ya_procesados():
    casos = [{"caso_id": "c1"}, {"caso_id": "c2"}, {"caso_id": "c3"}]
    pendientes = sdl._casos_pendientes(casos, {"c1", "c3"})
    assert pendientes == [{"caso_id": "c2"}]


def test_casos_pendientes_devuelve_todo_si_output_table_esta_vacia():
    casos = [{"caso_id": "c1"}, {"caso_id": "c2"}]
    assert sdl._casos_pendientes(casos, set()) == casos


def test_casos_pendientes_devuelve_vacio_si_todo_ya_esta_procesado():
    casos = [{"caso_id": "c1"}, {"caso_id": "c2"}]
    assert sdl._casos_pendientes(casos, {"c1", "c2"}) == []


def test_extract_retry_after_seconds_lee_metadata_del_cuerpo():
    body = json.dumps({"error": {"metadata": {"retry_after_seconds": 23.776}}})
    assert sdl._extract_retry_after_seconds(body) == 23.776


def test_extract_retry_after_seconds_devuelve_none_si_falta_el_campo():
    assert sdl._extract_retry_after_seconds(json.dumps({"error": {"metadata": {}}})) is None


def test_extract_retry_after_seconds_devuelve_none_con_cuerpo_no_json():
    assert sdl._extract_retry_after_seconds("no es json") is None


def test_build_default_client_rechaza_proveedor_invalido():
    with pytest.raises(ValueError):
        sdl._build_default_client("groq", "", "scope", "modelo")


def test_build_default_client_despacha_a_anthropic_client_con_sus_parametros(monkeypatch):
    llamado = {}

    def fake_anthropic_client(model, secret_scope, max_tokens=None):
        llamado["model"] = model
        llamado["secret_scope"] = secret_scope
        llamado["max_tokens"] = max_tokens
        return lambda system_prompt, history: None

    monkeypatch.setattr(sdl, "_anthropic_client", fake_anthropic_client)
    sdl._build_default_client(
        "anthropic", "", "scope", "or-modelo", anthropic_model="claude-sonnet-5", max_tokens=500
    )

    assert llamado == {"model": "claude-sonnet-5", "secret_scope": "scope", "max_tokens": 500}


def test_build_default_client_pasa_max_tokens_a_openrouter_client(monkeypatch):
    llamado = {}

    def fake_openrouter_client(model, secret_scope, max_tokens=None):
        llamado["max_tokens"] = max_tokens
        return lambda system_prompt, history: None

    monkeypatch.setattr(sdl, "_openrouter_client", fake_openrouter_client)
    sdl._build_default_client("openrouter", "", "scope", "or-modelo", max_tokens=250)

    assert llamado["max_tokens"] == 250


def test_parse_anthropic_response_extrae_texto_y_uso():
    respuesta = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Hola, ¿cómo se siente hoy?")],
        usage=SimpleNamespace(input_tokens=42, output_tokens=17),
    )
    resultado = sdl._parse_anthropic_response(respuesta)
    assert resultado.texto == "Hola, ¿cómo se siente hoy?"
    assert resultado.prompt_tokens == 42
    assert resultado.completion_tokens == 17


def test_parse_anthropic_response_ignora_bloques_que_no_son_de_texto():
    # p. ej. un bloque `thinking` (razonamiento oculto del modelo) antes del bloque de
    # texto real — solo el primer bloque `text` es la respuesta visible que debe llegar
    # al diálogo; el razonamiento nunca debe filtrarse a dialogos_capa1_limpia.
    respuesta = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", text=""),
            SimpleNamespace(type="text", text="respuesta real"),
        ],
        usage=SimpleNamespace(input_tokens=5, output_tokens=8),
    )
    resultado = sdl._parse_anthropic_response(respuesta)
    assert resultado.texto == "respuesta real"


def test_openrouter_request_reintenta_429_y_luego_tiene_exito(monkeypatch):
    calls = {"n": 0}
    sleeps = []

    def fake_post(url, headers, payload, timeout=60):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, {"error": {"metadata": {"retry_after_seconds": 5}}})
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    monkeypatch.setattr(sdl.time, "sleep", lambda s: sleeps.append(s))

    pacer = sdl._RequestPacer(0.0)
    data = sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3)

    assert data["choices"][0]["message"]["content"] == "ok"
    assert calls["n"] == 2
    assert sleeps and sleeps[0] >= 5  # honró retry_after_seconds, no el backoff exponencial


def test_openrouter_request_agota_reintentos_y_lanza_excepcion_dedicada(monkeypatch):
    def fake_post(url, headers, payload, timeout=60):
        raise _http_error(429, {"error": {"metadata": {"raw": "temporarily rate-limited upstream"}}})

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    monkeypatch.setattr(sdl.time, "sleep", lambda s: None)

    pacer = sdl._RequestPacer(0.0)
    with pytest.raises(sdl._OpenRouterRetriesExhausted):
        sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3)


def test_openrouter_request_no_reintenta_error_4xx_no_429(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers, payload, timeout=60):
        calls["n"] += 1
        raise _http_error(401, {"error": {"message": "invalid api key"}})

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    monkeypatch.setattr(sdl.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("no debería dormir en un 401")))

    pacer = sdl._RequestPacer(0.0)
    with pytest.raises(RuntimeError):
        sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3)

    assert calls["n"] == 1  # sin reintentos


def test_openrouter_request_reintenta_5xx(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers, payload, timeout=60):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(503, {"error": {"message": "service unavailable"}})
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    monkeypatch.setattr(sdl.time, "sleep", lambda s: None)

    pacer = sdl._RequestPacer(0.0)
    data = sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3)
    assert data["choices"][0]["message"]["content"] == "ok"
    assert calls["n"] == 3


def test_openrouter_request_incluye_max_tokens_en_payload_cuando_se_especifica(monkeypatch):
    payloads = []

    def fake_post(url, headers, payload, timeout=60):
        payloads.append(payload)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    pacer = sdl._RequestPacer(0.0)
    sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3, max_tokens=120)

    assert payloads[0]["max_tokens"] == 120


def test_openrouter_request_omite_max_tokens_si_no_se_especifica(monkeypatch):
    payloads = []

    def fake_post(url, headers, payload, timeout=60):
        payloads.append(payload)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(sdl, "_http_post_json", fake_post)
    pacer = sdl._RequestPacer(0.0)
    sdl._openrouter_request("modelo-x", "system", [], "key", pacer, max_attempts=3)

    assert "max_tokens" not in payloads[0]


def test_request_pacer_respeta_intervalo_minimo(monkeypatch):
    # wait() llama time.monotonic() dos veces por invocación (antes y después de dormir).
    ticks = iter([0.0, 0.0, 0.5, 2.5])  # primer wait() no duerme; segundo wait() debe dormir 1.5s
    monkeypatch.setattr(sdl.time, "monotonic", lambda: next(ticks))
    slept = []
    monkeypatch.setattr(sdl.time, "sleep", lambda s: slept.append(s))

    pacer = sdl._RequestPacer(2.0)
    pacer.wait()
    pacer.wait()

    assert slept == [1.5]
