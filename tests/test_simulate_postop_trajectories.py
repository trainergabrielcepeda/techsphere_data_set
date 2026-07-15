"""Pruebas del simulador de trayectorias post-operatorias (Componente 1 §5.3, Plan 05)."""

from postop import classify_ground_truth
from postop.simulate_postop_trajectories import choose_archetype, simulate_trajectory

CALL_DAYS = [1, 3, 7, 14]
ARCHETYPES = ["recuperacion_normal", "complicacion_leve_vigilancia", "complicacion_real"]


def _perfil(paciente_id: str, complicacion_encounter: bool) -> dict:
    return {"paciente_id": paciente_id, "complicacion_encounter": complicacion_encounter}


def test_complicacion_encounter_true_siempre_fuerza_complicacion_real():
    for i in range(30):
        perfil = _perfil(f"pac_{i}", complicacion_encounter=True)
        filas = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=i)
        assert all(f["arquetipo_trayectoria"] == "complicacion_real" for f in filas)


def test_complicacion_encounter_true_converge_a_rojo_en_la_ultima_llamada():
    for i in range(30):
        perfil = _perfil(f"pac_{i}", complicacion_encounter=True)
        filas = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=i)
        ultima = max(filas, key=lambda f: f["dia_postop"])
        sintomas = {k: ultima[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")}
        assert classify_ground_truth.classify(sintomas) == "rojo"


def test_complicacion_real_es_rojo_desde_el_umbral_de_convergencia_no_solo_al_final():
    from postop.clinical_domains import COMPLICACION_REAL_ROJO_THRESHOLD

    for i in range(30):
        perfil = _perfil(f"pac_{i}", complicacion_encounter=True)
        filas = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=i)
        n = len(filas)
        for idx, fila in enumerate(filas):
            progress = idx / (n - 1)
            if progress < COMPLICACION_REAL_ROJO_THRESHOLD:
                continue
            sintomas = {k: fila[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")}
            assert classify_ground_truth.classify(sintomas) == "rojo"


def test_recuperacion_normal_nunca_clasifica_rojo_en_la_ultima_llamada():
    for i in range(50):
        perfil = _perfil(f"pac_{i}", complicacion_encounter=False)
        rng_seed = i * 997  # variedad de seeds sin depender de complicacion_encounter=True
        filas = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=rng_seed)
        if filas[0]["arquetipo_trayectoria"] != "recuperacion_normal":
            continue
        ultima = max(filas, key=lambda f: f["dia_postop"])
        sintomas = {k: ultima[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")}
        assert classify_ground_truth.classify(sintomas) == "verde"


def test_complicacion_leve_vigilancia_nunca_clasifica_rojo():
    # Fuerza el arquetipo directamente vía choose_archetype con complicacion_encounter=False
    # y verifica sobre muchas seeds que ningún día individual cruza el umbral rojo.
    import random

    encontrado_leve = False
    for i in range(200):
        rng = random.Random(i)
        arquetipo = choose_archetype(False, ARCHETYPES, rng)
        if arquetipo != "complicacion_leve_vigilancia":
            continue
        encontrado_leve = True
        perfil = _perfil(f"pac_{i}", complicacion_encounter=False)
        filas = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=i)
        for fila in filas:
            sintomas = {k: fila[k] for k in ("dolor_nrs", "fiebre_c", "movilidad", "herida", "apetito", "sueno")}
            assert classify_ground_truth.classify(sintomas) != "rojo"
    assert encontrado_leve, "ninguna de las 200 seeds produjo complicacion_leve_vigilancia — revisar pesos de choose_archetype"


def test_determinismo_por_seed():
    perfil = _perfil("pac_x", complicacion_encounter=False)
    filas_a = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=99)
    filas_b = simulate_trajectory(perfil, CALL_DAYS, ARCHETYPES, seed=99)
    assert filas_a == filas_b
