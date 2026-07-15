"""Pruebas del generador sintético de perfiles (Componente 1, §5, Plan 05).

No depende de pysynthea/Synthea — ver el docstring de generate_synthea_profiles.py para
el resultado del spike de §5.2 que motivó este generador propio.
"""

from collections import Counter

from postop import clinical_domains
from postop.generate_synthea_profiles import SYNTHEA_RUNTIME, generate_synthetic_profiles, write_bundles_to_volume

MODULE_ALLOWLIST = [
    "appendicitis",
    "cholecystitis",
    "colorectal_cancer",
    "total_joint_replacement",
    "breast_cancer",
]


def _sin_timestamp(perfil: dict) -> dict:
    return {k: v for k, v in perfil.items() if k != "generado_ts"}


def test_reproducibilidad_por_seed():
    # generado_ts refleja el momento real de generación, no el contenido — se excluye de
    # la comparación de reproducibilidad a propósito.
    perfiles_a = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=50, seed=42)
    perfiles_b = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=50, seed=42)
    assert [_sin_timestamp(p) for p in perfiles_a] == [_sin_timestamp(p) for p in perfiles_b]


def test_todos_los_modulos_de_la_allowlist_aparecen():
    perfiles = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=100, seed=42)
    modulos_generados = {p["modulo_synthea"] for p in perfiles}
    assert modulos_generados == set(MODULE_ALLOWLIST)


def test_synthea_runtime_declara_la_desviacion():
    perfiles = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=5, seed=42)
    assert all(p["synthea_runtime"] == SYNTHEA_RUNTIME for p in perfiles)
    assert all(p["synthea_runtime"] != "pysynthea" for p in perfiles)


def test_edad_dentro_del_rango_calibrado_por_modulo():
    perfiles = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=200, seed=42)
    for perfil in perfiles:
        calib = clinical_domains.PROCEDURE_CALIBRATION[perfil["modulo_synthea"]]
        assert calib["edad_min"] <= perfil["edad"] <= calib["edad_max"]


def test_modulo_desconocido_lanza_error():
    import pytest

    with pytest.raises(ValueError):
        generate_synthetic_profiles(["modulo_inexistente"], n_pacientes=1, seed=42)


def test_tasa_de_complicacion_aproxima_la_calibracion():
    n = 2000
    perfiles = generate_synthetic_profiles(["colorectal_cancer"], n_pacientes=n, seed=42)
    tasa_observada = sum(p["complicacion_encounter"] for p in perfiles) / n
    tasa_esperada = clinical_domains.PROCEDURE_CALIBRATION["colorectal_cancer"]["complicacion_prob"]
    assert abs(tasa_observada - tasa_esperada) < 0.04


def test_ids_de_paciente_son_unicos():
    perfiles = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=300, seed=42)
    ids = [p["paciente_id"] for p in perfiles]
    assert len(ids) == len(set(ids))


def test_write_bundles_to_volume_limpia_bundles_de_una_corrida_anterior(tmp_path):
    # Regresión de un bug real (Plan 06 Fase 4): una corrida con n_pacientes grande
    # seguida de una corrida con n_pacientes chico dejaba archivos huérfanos en el
    # volumen — parse_bundles_to_perfiles_pacientes los releía todos, produciendo de
    # nuevo el conteo de la corrida anterior en vez del de la corrida actual.
    perfiles_grandes = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=25, seed=42)
    write_bundles_to_volume(perfiles_grandes, str(tmp_path))
    assert len(list(tmp_path.glob("*.json"))) == 25

    perfiles_chicos = generate_synthetic_profiles(MODULE_ALLOWLIST, n_pacientes=1, seed=42)
    write_bundles_to_volume(perfiles_chicos, str(tmp_path))
    assert len(list(tmp_path.glob("*.json"))) == 1
