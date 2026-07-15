"""Pruebas de la adaptación geográfica a Colombia (Componente 2, §6, Plan 05)."""

from collections import Counter

from postop import adapt_colombia, dane_reference


def test_determinismo_por_paciente_id_y_seed():
    filas_a = adapt_colombia.adapt_to_colombia([{"paciente_id": "pac_1"}], seed=42)
    filas_b = adapt_colombia.adapt_to_colombia([{"paciente_id": "pac_1"}], seed=42)
    fila_a, fila_b = filas_a[0], filas_b[0]
    for campo in ("nombre_completo", "direccion", "ciudad", "departamento", "documento_cc", "eps"):
        assert fila_a[campo] == fila_b[campo]


def test_seeds_distintas_dan_datos_distintos():
    fila_42 = adapt_colombia.adapt_to_colombia([{"paciente_id": "pac_1"}], seed=42)[0]
    fila_7 = adapt_colombia.adapt_to_colombia([{"paciente_id": "pac_1"}], seed=7)[0]
    assert (fila_42["nombre_completo"], fila_42["documento_cc"]) != (fila_7["nombre_completo"], fila_7["documento_cc"])


def test_columnas_de_auditoria_declaran_la_sustitucion():
    fila = adapt_colombia.adapt_to_colombia([{"paciente_id": "pac_1"}], seed=42)[0]
    assert fila["source_country"] == "US"
    assert fila["adapted_country"] == "CO"
    assert set(fila["adaptation_fields"]) == set(adapt_colombia.ADAPTATION_FIELDS)


def test_documento_cc_no_colisiona_con_rango_de_cedula_real():
    filas = adapt_colombia.adapt_to_colombia([{"paciente_id": f"pac_{i}"} for i in range(20)], seed=42)
    for fila in filas:
        assert int(fila["documento_cc"]) >= adapt_colombia.CEDULA_OFFSET


def test_eps_viene_de_la_lista_curada():
    filas = adapt_colombia.adapt_to_colombia([{"paciente_id": f"pac_{i}"} for i in range(20)], seed=42)
    for fila in filas:
        assert fila["eps"] in adapt_colombia.EPS_COLOMBIA


def test_distribucion_geografica_no_se_concentra_en_uno_o_dos_departamentos():
    pacientes = [{"paciente_id": f"pac_{i}"} for i in range(500)]
    filas = adapt_colombia.adapt_to_colombia(pacientes, seed=42)
    conteo = Counter(fila["departamento"] for fila in filas)

    # Bogotá D.C. es el departamento con más peso (~14.9%) — sobre 500 muestras no debería
    # dominar el dataset entero, y debe aparecer más de un puñado de departamentos.
    peso_bogota = dict((d, p) for d, _, p in dane_reference.department_weights())["Bogotá D.C."]
    assert conteo["Bogotá D.C."] / len(filas) < peso_bogota * 2.5
    assert len(conteo) >= 10
