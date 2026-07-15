"""Pruebas del cliente OpenRouter y del checkpointing por cuota (Componente 4, Plan 06).

No cubre ``_openrouter_client``/``_default_client`` en sí — ambos importan
``databricks.sdk`` de forma diferida (solo disponible en el cluster), el mismo límite de
testabilidad que ya existía para ``_default_client`` antes de este plan. Lo que sí se
prueba sin red ni SDK: el filtro de reanudación, la lógica de reintento/backoff/fallback
contra un doble de la capa HTTP, y la extracción del hint de reintento.
"""

import io
import json
import urllib.error

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
