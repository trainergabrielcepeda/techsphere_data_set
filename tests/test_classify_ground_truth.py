"""Pruebas del motor de clasificación ground-truth (Componente 3, §7, Plan 05)."""

from postop import classify_ground_truth


def _sintomas(**overrides):
    base = {
        "dolor_nrs": 0,
        "fiebre_c": 36.5,
        "herida": "normal",
        "movilidad": "normal",
        "apetito": "normal",
        "sueno": "normal",
    }
    base.update(overrides)
    return base


def test_verde_por_defecto():
    assert classify_ground_truth.classify(_sintomas()) == "verde"


def test_cada_bandera_roja_individual_basta():
    assert classify_ground_truth.classify(_sintomas(fiebre_c=38.5)) == "rojo"
    assert classify_ground_truth.classify(_sintomas(herida="dehiscencia")) == "rojo"
    assert classify_ground_truth.classify(_sintomas(herida="secrecion_purulenta")) == "rojo"
    assert classify_ground_truth.classify(_sintomas(dolor_nrs=8)) == "rojo"
    assert classify_ground_truth.classify(_sintomas(movilidad="incapacitante_nueva")) == "rojo"


def test_umbral_rojo_es_inclusive():
    assert classify_ground_truth.classify(_sintomas(fiebre_c=38.49)) != "rojo"
    assert classify_ground_truth.classify(_sintomas(dolor_nrs=7)) != "rojo"


def test_una_sola_senal_amarilla_no_alcanza():
    assert classify_ground_truth.classify(_sintomas(fiebre_c=37.8)) == "verde"
    assert classify_ground_truth.classify(_sintomas(dolor_nrs=5)) == "verde"
    assert classify_ground_truth.classify(_sintomas(herida="eritema_leve")) == "verde"


def test_dos_senales_amarillas_clasifican_amarillo():
    assert classify_ground_truth.classify(_sintomas(fiebre_c=37.8, dolor_nrs=5)) == "amarillo"
    assert classify_ground_truth.classify(_sintomas(apetito="muy_disminuido", sueno="muy_alterado")) == "amarillo"


def test_rojo_tiene_prioridad_sobre_amarillo():
    # 3 señales amarillas + 1 bandera roja -> sigue siendo rojo, no amarillo.
    sintomas = _sintomas(fiebre_c=38.5, dolor_nrs=5, herida="eritema_leve")
    assert classify_ground_truth.classify(sintomas) == "rojo"


def test_regla_version_declara_estado_provisional():
    assert "sin_validacion" in classify_ground_truth.REGLA_VERSION.replace("-", "_")
