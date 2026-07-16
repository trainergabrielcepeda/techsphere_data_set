"""Pruebas de las expectativas de calidad de publicación (§12, Componente publish_gold,
Plan 05, extendido Plan 09) — cada check corre como función pura sobre list[dict], sin
Spark."""

from datetime import datetime, timezone

from postop import publish_gold


def _perfil_co(paciente_id="pac1", **overrides):
    base = {
        "paciente_id": paciente_id,
        "nombre_completo": "Ana Ramírez",
        "direccion": "Calle 10 # 20-30",
        "ciudad": "Medellín",
        "departamento": "Antioquia",
        "documento_cc": "900000001",
        "eps": "Sura EPS",
        "adapted_country": "CO",
    }
    base.update(overrides)
    return base


def test_perfiles_pacientes_co_pasa_con_datos_limpios():
    assert publish_gold.check_perfiles_pacientes_co([_perfil_co()]) == []


def test_perfiles_pacientes_co_detecta_campo_nulo():
    problems = publish_gold.check_perfiles_pacientes_co([_perfil_co(eps=None)])
    assert any("nulos en campos demográficos" in p for p in problems)


def test_perfiles_pacientes_co_detecta_adapted_country_incorrecto():
    problems = publish_gold.check_perfiles_pacientes_co([_perfil_co(adapted_country="US")])
    assert any("adapted_country" in p for p in problems)


def test_perfiles_pacientes_co_vacio_es_un_problema():
    assert publish_gold.check_perfiles_pacientes_co([]) != []


def _caso(label):
    return {"label": label}


def test_casos_clinicos_etiquetados_pasa_con_distribucion_balanceada():
    casos = [_caso("verde")] * 40 + [_caso("amarillo")] * 30 + [_caso("rojo")] * 30
    assert publish_gold.check_casos_clinicos_etiquetados_balance(casos) == []


def test_casos_clinicos_etiquetados_detecta_label_subrepresentado():
    casos = [_caso("verde")] * 95 + [_caso("amarillo")] * 3 + [_caso("rojo")] * 2
    problems = publish_gold.check_casos_clinicos_etiquetados_balance(casos)
    assert any("amarillo" in p for p in problems)
    assert any("rojo" in p for p in problems)


def test_casos_clinicos_etiquetados_banda_ampliada_5_75_pasa_en_el_borde():
    # Plan 07: banda ampliada de [10%,70%] a [5%,75%] — un label al 6% (antes fallaba)
    # ahora pasa, y uno al 74% (antes fallaba) también pasa.
    casos = [_caso("verde")] * 74 + [_caso("amarillo")] * 20 + [_caso("rojo")] * 6
    assert publish_gold.check_casos_clinicos_etiquetados_balance(casos) == []


def test_casos_clinicos_etiquetados_banda_ampliada_sigue_fallando_fuera_del_5_75():
    # 3% y 76% siguen fuera de [5%,75%] — la banda se amplió, no se eliminó.
    casos = [_caso("verde")] * 76 + [_caso("amarillo")] * 21 + [_caso("rojo")] * 3
    problems = publish_gold.check_casos_clinicos_etiquetados_balance(casos)
    assert any("verde" in p for p in problems)
    assert any("rojo" in p for p in problems)


def test_casos_clinicos_etiquetados_no_vacio_detecta_tabla_vacia():
    # Plan 09: separado del balance de labels — una tabla vacía es una falla real de las
    # tasks anteriores, no una cuestión de distribución, y sigue bloqueando la publicación.
    assert publish_gold.check_casos_clinicos_etiquetados_no_vacio([]) != []


def test_casos_clinicos_etiquetados_no_vacio_pasa_sin_importar_el_balance():
    # No le importa el balance de labels — eso es responsabilidad exclusiva de
    # check_casos_clinicos_etiquetados_balance, que ahora es no bloqueante.
    casos = [_caso("verde")] * 100
    assert publish_gold.check_casos_clinicos_etiquetados_no_vacio(casos) == []


def test_casos_clinicos_etiquetados_balance_no_marca_tabla_vacia():
    # La tabla vacía ya la cubre check_casos_clinicos_etiquetados_no_vacio — el chequeo
    # de balance no debe fallar (ni lanzar ZeroDivisionError) sobre una lista vacía.
    assert publish_gold.check_casos_clinicos_etiquetados_balance([]) == []


def test_build_alertas_rows_arma_una_fila_por_alerta():
    ts = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    filas = publish_gold._build_alertas_rows(["problema A", "problema B"], "postop_dataset_dev", ts)

    assert len(filas) == 2
    assert filas[0]["check_nombre"] == "casos_clinicos_etiquetados_balance"
    assert filas[0]["detalle"] == "problema A"
    assert filas[0]["severidad"] == "advertencia"
    assert filas[0]["catalog_run"] == "postop_dataset_dev"
    assert filas[0]["generado_ts"] == ts
    assert filas[0]["alerta_id"] != filas[1]["alerta_id"]  # IDs únicos por fila


def test_build_alertas_rows_vacio_si_no_hay_alertas():
    assert publish_gold._build_alertas_rows([], "postop_dataset_dev", datetime.now(timezone.utc)) == []


def _turno(dialogo_id, caso_id, hablante, texto="algo"):
    return {"dialogo_id": dialogo_id, "caso_id": caso_id, "hablante": hablante, "texto": texto}


def test_dialogos_capa1_pasa_con_ambos_hablantes_y_sin_turnos_vacios():
    turnos = [_turno("d1", "c1", "agente"), _turno("d2", "c1", "paciente")]
    assert publish_gold.check_dialogos_capa1_limpia(turnos) == []


def test_dialogos_capa1_detecta_caso_sin_paciente():
    turnos = [_turno("d1", "c1", "agente"), _turno("d2", "c1", "agente")]
    problems = publish_gold.check_dialogos_capa1_limpia(turnos)
    assert any("no tiene turnos de ambos hablantes" in p for p in problems)


def test_dialogos_capa1_detecta_turno_vacio():
    turnos = [_turno("d1", "c1", "agente"), _turno("d2", "c1", "paciente", texto="  ")]
    problems = publish_gold.check_dialogos_capa1_limpia(turnos)
    assert any("turno vacío" in p for p in problems)


def test_noise_mapping_log_pasa_cuando_todo_turno_con_ruido_tiene_mapping():
    capa2 = [{"dialogo_id": "d1", "intensidad_ruido": 3}, {"dialogo_id": "d2", "intensidad_ruido": None}]
    mapping = [{"dialogo_id_capa2": "d1"}]
    assert publish_gold.check_noise_mapping_log(capa2, mapping) == []


def test_noise_mapping_log_detecta_transformacion_silenciosa():
    capa2 = [{"dialogo_id": "d1", "intensidad_ruido": 3}]
    mapping = []
    problems = publish_gold.check_noise_mapping_log(capa2, mapping)
    assert any("transformación silenciosa" in p for p in problems)


def test_dialogos_capa3_pasa_cuando_todo_esta_validado():
    filas = [{"dialogo_id": "d1", "validado_por": "comite@ejemplo.com"}]
    assert publish_gold.check_dialogos_capa3_limite(filas) == []


def test_dialogos_capa3_detecta_validado_por_nulo():
    filas = [{"dialogo_id": "d1", "validado_por": None}]
    problems = publish_gold.check_dialogos_capa3_limite(filas)
    assert any("validado_por nulo" in p for p in problems)


def test_load_sql_statements_no_corrompe_statement_tras_comentario_con_punto_y_coma():
    # sql/ddl/00_catalog_schemas.sql tiene un comentario con ';' en medio de la oración
    # justo antes del primer CREATE CATALOG (Plan 06 Fase 2) — un split(";") ingenuo antes
    # de filtrar comentarios deja el resto de esa línea de comentario pegado al statement.
    statements = publish_gold._load_sql_statements("sql/ddl/00_catalog_schemas.sql", "postop_dataset_dev")
    assert statements[0] == "CREATE CATALOG IF NOT EXISTS postop_dataset_dev"


def test_load_sql_statements_grant_use_catalog_sobrevive_intacto():
    # Regresión del bug real: este GRANT, en producción, quedaba con texto de comentario
    # pegado al inicio y dejaba de empezar con 'GRANT' — apply_grants lo descartaba en
    # silencio, participantes nunca recibían USE CATALOG.
    statements = publish_gold._load_sql_statements("sql/ddl/30_publish_gold_grants.sql", "postop_dataset_dev")
    assert "GRANT USE CATALOG ON CATALOG postop_dataset_dev TO `account users`" in statements


def test_load_sql_statements_sustituye_catalogo_en_todos_los_statements():
    statements = publish_gold._load_sql_statements("sql/ddl/13_casos_clinicos_etiquetados.sql", "postop_dataset_dev")
    assert all("postop_dataset_dev" in s for s in statements)
    assert all("postop_dataset." not in s for s in statements)
