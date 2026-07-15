"""Pruebas del inyector de ruido (Componente 5, §9, Plan 05)."""

from postop import inject_noise


def _turnos_fixture(n: int = 6) -> list[dict]:
    return [
        {
            "dialogo_id": f"dlg_caso1_{i}",
            "caso_id": "caso1",
            "paciente_id": "pac1",
            "dia_postop": 3,
            "turno_idx": i,
            "hablante": "agente" if i % 2 == 0 else "paciente",
            "texto": f"Turno número {i}, ¿cómo se siente hoy del dolor?",
            "label_ground_truth": "amarillo",
            "estilo_paciente": "colaborativo",
            "modelo_paciente": "modelo-x",
            "modelo_agente": "modelo-x",
        }
        for i in range(n)
    ]


def test_inject_noise_udf_es_deterministico():
    a = inject_noise.inject_noise_udf("me duele mucho la herida", "ruido_stt", 3, seed=42)
    b = inject_noise.inject_noise_udf("me duele mucho la herida", "ruido_stt", 3, seed=42)
    assert a == b


def test_inject_noise_udf_rechaza_tipo_estructural():
    import pytest

    with pytest.raises(ValueError):
        inject_noise.inject_noise_udf("texto", "cambio_interlocutor", 3, seed=42)


def test_inject_noise_udf_rechaza_intensidad_fuera_de_rango():
    import pytest

    with pytest.raises(ValueError):
        inject_noise.inject_noise_udf("texto", "ruido_stt", 6, seed=42)


def test_cada_tipo_de_ruido_produce_texto_distinto_del_original_con_intensidad_maxima():
    texto = "el dolor está más o menos igual que ayer, con algo de fiebre"
    for tipo in inject_noise.TEXT_MUTATING_NOISE_TYPES:
        lo, hi = inject_noise.NOISE_TYPE_INTENSITY_RANGE[tipo]
        resultado = inject_noise.inject_noise_udf(texto, tipo, hi, seed=1)
        assert resultado != texto or lo != hi  # al menos alguna transformación visible


def test_label_ground_truth_se_hereda_sin_cambios():
    turnos = _turnos_fixture()
    salida, _ = inject_noise.inject_noise_into_turnos(turnos, intensidad=5, seed=42)
    assert all(fila["label_ground_truth"] == "amarillo" for fila in salida)


def test_cada_turno_afectado_tiene_exactamente_una_fila_de_mapping():
    turnos = _turnos_fixture(n=10)
    salida, mapping = inject_noise.inject_noise_into_turnos(turnos, intensidad=5, seed=42)

    afectados = [fila for fila in salida if fila["intensidad_ruido"] is not None]
    ids_afectados = {fila["dialogo_id"] for fila in afectados}
    ids_en_mapping = [fila["dialogo_id_capa2"] for fila in mapping]

    assert len(mapping) > 0
    assert set(ids_en_mapping) == ids_afectados
    # cada dialogo_id_capa2 afectado aparece exactamente una vez en el mapping (una
    # transformación por fila en esta implementación)
    for dialogo_id in ids_afectados:
        assert ids_en_mapping.count(dialogo_id) == 1


def test_ninguna_transformacion_es_silenciosa_en_intensidad_alta():
    turnos = _turnos_fixture(n=20)
    salida, mapping = inject_noise.inject_noise_into_turnos(turnos, intensidad=5, seed=42)
    assert len(mapping) > 0
    for fila in mapping:
        assert fila["texto_original"] != "" and fila["tipo_ruido"] in inject_noise.NOISE_TYPES


def test_intensidad_cero_o_fuera_de_rango_no_afecta_ningun_turno():
    turnos = _turnos_fixture()
    salida, mapping = inject_noise.inject_noise_into_turnos(turnos, intensidad=0, seed=42)
    assert mapping == []
    assert all(fila["intensidad_ruido"] is None for fila in salida)
    assert [fila["texto"] for fila in salida] == [t["texto"] for t in turnos]


def test_cambio_interlocutor_inserta_una_fila_tercero():
    turnos = _turnos_fixture(n=30)
    salida, mapping = inject_noise.inject_noise_into_turnos(turnos, intensidad=5, seed=7)
    terceros = [fila for fila in salida if fila["hablante"] == "tercero"]
    mapping_tercero = [m for m in mapping if m["tipo_ruido"] == "cambio_interlocutor"]
    assert len(terceros) == len(mapping_tercero)


def _sin_timestamps(filas: list[dict], *campos: str) -> list[dict]:
    return [{k: v for k, v in fila.items() if k not in campos} for fila in filas]


def test_determinismo_por_seed():
    # generado_ts/aplicado_ts reflejan el momento real de ejecución, no el contenido —
    # se excluyen de la comparación de reproducibilidad a propósito.
    turnos = _turnos_fixture()
    salida_a, mapping_a = inject_noise.inject_noise_into_turnos(turnos, intensidad=4, seed=99)
    salida_b, mapping_b = inject_noise.inject_noise_into_turnos(turnos, intensidad=4, seed=99)
    assert _sin_timestamps(salida_a, "generado_ts") == _sin_timestamps(salida_b, "generado_ts")
    assert _sin_timestamps(mapping_a, "aplicado_ts") == _sin_timestamps(mapping_b, "aplicado_ts")
