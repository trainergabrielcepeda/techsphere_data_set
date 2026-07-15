"""Pruebas de la tabla de referencia DANE (Plan 05)."""

import random

from postop import dane_reference


def test_pesos_suman_uno():
    pesos = [peso for _, _, peso in dane_reference.department_weights()]
    assert abs(sum(pesos) - 1.0) < 1e-9


def test_los_33_departamentos_estan_presentes():
    assert len(dane_reference.DEPARTAMENTOS) == 33
    nombres = {depto for depto, _, _ in dane_reference.DEPARTAMENTOS}
    assert len(nombres) == 33  # sin duplicados


def test_bogota_es_el_departamento_mas_poblado():
    entries = sorted(dane_reference.department_weights(), key=lambda e: e[2], reverse=True)
    assert entries[0][0] == "Bogotá D.C."


def test_muestreo_es_deterministico_para_una_seed_fija():
    r1 = dane_reference.sample_departamento_ciudad(random.Random(123))
    r2 = dane_reference.sample_departamento_ciudad(random.Random(123))
    assert r1 == r2


def test_muestreo_solo_devuelve_pares_conocidos():
    pares_validos = {(depto, ciudad) for depto, ciudad, _ in dane_reference.DEPARTAMENTOS}
    rng = random.Random(7)
    for _ in range(200):
        assert dane_reference.sample_departamento_ciudad(rng) in pares_validos
