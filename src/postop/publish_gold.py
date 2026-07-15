"""Publicación gold — grants + vistas finales por audiencia (Diseño Técnico §4, §16).

Ejecuta, como parte del mismo job (nunca como paso manual posterior, riesgo R6):
  1. Expectativas de calidad de §12 (el job falla y NO publica si alguna expectativa
     crítica no se cumple — evita que un dataset roto llegue a gold_participantes).
  2. Los GRANT/REVOKE de sql/ddl/30_publish_gold_grants.sql — separa lo que reciben
     los equipos participantes (gold_participantes.dataset_final, Capas 1+2) de lo
     reservado al comité (gold_comite.dataset_final_completo, Capas 1+2+3).

Nota sobre la expectativa de ``noise_mapping_log`` (§12): el diseño la redacta como "cada
fila de dialogos_capa2_ruidosa tiene al menos una fila de mapping asociada", pero el
propio esquema de dialogos_capa2_ruidosa permite ``intensidad_ruido IS NULL`` para turnos
no afectados por el ruido (sql/ddl/21, CHECK ``intensidad_valida``) — un turno no afectado
nunca genera fila de mapping por diseño (inject_noise.py). La lectura no contradictoria,
implementada aquí: toda fila de Capa 2 con ``intensidad_ruido IS NOT NULL`` (es decir, que
sí fue tocada por el inyector) debe tener ≥1 fila de mapping asociada — "ninguna
transformación silenciosa", no "ningún turno sin mapping".
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Databricks ejecuta este archivo como spark_python_task suelto (python_file, sin
# empaquetar como wheel — §11) — src/ no queda en sys.path por su cuenta, confirmado al
# correr el job real en Plan 06 Fase 4 (ModuleNotFoundError: No module named 'postop').
# __file__ tampoco existe en este contexto: Databricks ejecuta el script vía
# exec(compile(source, filename, 'exec')), que no inyecta __file__ en los globals —
# también confirmado contra el workspace real (NameError: name '__file__' is not
# defined). sys._getframe().f_code.co_filename sí lo tiene, vía co_filename del compile().
_this_file = sys._getframe().f_code.co_filename
sys.path.insert(0, str(Path(_this_file).resolve().parents[1]))

from postop import config

_SQL_DDL_ROOT = Path(_this_file).resolve().parents[2] / "sql" / "ddl"


def check_perfiles_pacientes_co(rows: list[dict]) -> list[str]:
    if not rows:
        return ["perfiles_pacientes_co: la tabla está vacía"]
    problems = []
    campos_clave = ["nombre_completo", "direccion", "ciudad", "departamento", "documento_cc", "eps"]
    for row in rows:
        if any(row.get(campo) in (None, "") for campo in campos_clave):
            problems.append(f"perfiles_pacientes_co: nulos en campos demográficos clave para {row.get('paciente_id')}")
        if row.get("adapted_country") != "CO":
            problems.append(f"perfiles_pacientes_co: adapted_country != 'CO' para {row.get('paciente_id')}")
    return problems


def check_casos_clinicos_etiquetados(rows: list[dict]) -> list[str]:
    if not rows:
        return ["casos_clinicos_etiquetados: la tabla está vacía"]
    total = len(rows)
    conteos = Counter(row["label"] for row in rows)
    problems = []
    for label in ("verde", "amarillo", "rojo"):
        pct = conteos.get(label, 0) / total
        if pct < 0.10 or pct > 0.70:
            problems.append(f"casos_clinicos_etiquetados: label '{label}' fuera de rango [10%,70%] ({pct:.1%})")
    return problems


def check_dialogos_capa1_limpia(rows: list[dict]) -> list[str]:
    problems = []
    por_caso: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        por_caso[row["caso_id"]].append(row)
        if not (row.get("texto") or "").strip():
            problems.append(f"dialogos_capa1_limpia: turno vacío en {row.get('dialogo_id')}")
    for caso_id, turnos in por_caso.items():
        hablantes = {t["hablante"] for t in turnos}
        if "paciente" not in hablantes or "agente" not in hablantes:
            problems.append(f"dialogos_capa1_limpia: caso {caso_id} no tiene turnos de ambos hablantes")
    return problems


def check_noise_mapping_log(capa2_rows: list[dict], mapping_rows: list[dict]) -> list[str]:
    afectados = {row["dialogo_id"] for row in capa2_rows if row.get("intensidad_ruido") is not None}
    con_mapping = {row["dialogo_id_capa2"] for row in mapping_rows}
    faltantes = afectados - con_mapping
    if faltantes:
        return [f"noise_mapping_log: {len(faltantes)} filas de capa2 con ruido sin mapping asociado (transformación silenciosa)"]
    return []


def check_dialogos_capa3_limite(rows: list[dict]) -> list[str]:
    return [f"dialogos_capa3_limite: validado_por nulo en {row.get('dialogo_id')}" for row in rows if not row.get("validado_por")]


def run_quality_expectations(spark, catalog: str) -> bool:
    """Corre las expectativas de calidad de §12 sobre cada tabla silver/gold. Devuelve
    False si alguna expectativa crítica no se cumple (el job debe abortar sin publicar).
    """
    tablas = {
        "perfiles_pacientes_co": f"{catalog}.silver.perfiles_pacientes_co",
        "casos_clinicos_etiquetados": f"{catalog}.silver.casos_clinicos_etiquetados",
        "dialogos_capa1_limpia": f"{catalog}.silver.dialogos_capa1_limpia",
        "dialogos_capa2_ruidosa": f"{catalog}.silver.dialogos_capa2_ruidosa",
        "noise_mapping_log": f"{catalog}.silver.noise_mapping_log",
        "dialogos_capa3_limite": f"{catalog}.silver.dialogos_capa3_limite",
    }
    datos = {nombre: [row.asDict() for row in spark.table(tabla).collect()] for nombre, tabla in tablas.items()}

    problems: list[str] = []
    problems += check_perfiles_pacientes_co(datos["perfiles_pacientes_co"])
    problems += check_casos_clinicos_etiquetados(datos["casos_clinicos_etiquetados"])
    problems += check_dialogos_capa1_limpia(datos["dialogos_capa1_limpia"])
    problems += check_noise_mapping_log(datos["dialogos_capa2_ruidosa"], datos["noise_mapping_log"])
    problems += check_dialogos_capa3_limite(datos["dialogos_capa3_limite"])

    for problem in problems:
        print(f"[publish_gold] expectativa fallida: {problem}")
    return not problems


_REPO_ROOT = _SQL_DDL_ROOT.parent.parent


def _load_sql_statements(relative_path: str, catalog: str) -> list[str]:
    """Lee un archivo .sql relativo a la raíz del repo, lo separa en statements
    individuales (por ``;``), y sustituye el catálogo por defecto (``postop_dataset``)
    por ``catalog``.

    Las líneas de comentario se descartan ANTES de partir por ``;`` (no después) —
    varios comentarios en sql/ddl/*.sql contienen un ``;`` dentro del texto (p. ej. una
    oración con punto y coma, o un GRANT de ejemplo documentado en un comentario). Partir
    primero por ``;`` y filtrar comentarios después dejaba pasar el resto de esa línea de
    comentario pegado al statement real siguiente — encontrado al ejecutar esta función a
    mano en el bootstrap de Plan 06 Fase 2 contra el catálogo real: corrompía el primer
    ``CREATE CATALOG`` de 00_catalog_schemas.sql, y en 30_publish_gold_grants.sql hacía que
    ``GRANT USE CATALOG ON CATALOG ... TO account users`` quedara con texto de comentario
    al inicio, dejara de empezar con ``GRANT`` y ``apply_grants`` lo descartara en
    silencio — el grant de acceso al catálogo para participantes nunca se ejecutaba.
    """
    raw = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
    sql_only = "\n".join(linea for linea in raw.splitlines() if linea.strip() and not linea.strip().startswith("--"))
    statements = []
    for chunk in sql_only.split(";"):
        stmt = chunk.strip()
        if stmt:
            statements.append(stmt.replace("postop_dataset", catalog))
    return statements


def apply_grants(spark, catalog: str, committee_emails: list[str]) -> None:
    """Ejecuta los GRANT/REVOKE de ``sql/ddl/30_publish_gold_grants.sql`` — separación
    de audiencias por Unity Catalog nativo (§4, riesgo R6).

    Plan 02 (Free Edition): sin grupos de Unity Catalog disponibles, los participantes
    se cubren con el principal ``account users`` (hardcodeado en el DDL) y el comité se
    otorga por email individual — un GRANT por entrada de ``committee_emails``.
    """
    for stmt in _load_sql_statements("sql/ddl/30_publish_gold_grants.sql", catalog):
        if stmt.upper().startswith(("GRANT", "REVOKE")):
            spark.sql(stmt)

    for email in committee_emails:
        spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {catalog}.gold_comite TO `{email}`")
        spark.sql(f"GRANT SELECT ON TABLE {catalog}.silver.dialogos_capa3_limite TO `{email}`")


def publish_gold_views(spark, catalog: str) -> None:
    """Crea/reemplaza ``gold_participantes.dataset_final`` (Capas 1+2) y
    ``gold_comite.dataset_final_completo`` (Capas 1+2+3) — ver
    ``sql/ddl/30_publish_gold_grants.sql``.
    """
    for stmt in _load_sql_statements("sql/ddl/30_publish_gold_grants.sql", catalog):
        if stmt.upper().startswith("CREATE OR REPLACE VIEW"):
            spark.sql(stmt)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Publicación gold — grants + vistas finales por audiencia")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    committee_emails = cfg["governance"]["committee_emails"]

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()

    if not run_quality_expectations(spark=spark, catalog=args.catalog):
        raise RuntimeError("Expectativas de calidad (§12) no satisfechas — publicación abortada")

    apply_grants(spark=spark, catalog=args.catalog, committee_emails=committee_emails)
    publish_gold_views(spark=spark, catalog=args.catalog)


if __name__ == "__main__":
    main()
