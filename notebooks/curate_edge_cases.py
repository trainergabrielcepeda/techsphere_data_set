# Databricks notebook source
# MAGIC %md
# MAGIC # Componente 6 — Curaduría de casos límite (Capa 3)
# MAGIC
# MAGIC Diseño Técnico §10. Curaduría **manual**, no generación automática — este notebook
# MAGIC es el formulario/checklist de validación clínica por caso que un revisor humano
# MAGIC completa antes de escribir a `silver.dialogos_capa3_limite`.
# MAGIC
# MAGIC Categorías mínimas (ficha §6, Diseño Técnico §10):
# MAGIC - `alarma_real` — alarma real inequívoca
# MAGIC - `falso_positivo` — falso positivo / paciente ansioso
# MAGIC - `solicitud_diagnostico` — solicitud de diagnóstico directo
# MAGIC - `pii_mezclada` — PII sensible (sintética) mezclada en el discurso del paciente
# MAGIC
# MAGIC **Nunca** pasa por el inyector de ruido de Capa 2 ni se expone en `gold_participantes`.
# MAGIC El ACL restringido ya vive en la tabla desde su creación (`sql/ddl/23_dialogos_capa3_limite.sql`).
# MAGIC
# MAGIC `submit_edge_case` (Plan 05) es lógica real — valida y hace MERGE. Sigue sin haber
# MAGIC casos curados todavía: la curaduría es human-in-the-loop por diseño (§10), no algo que
# MAGIC se pueda fabricar aquí.

# COMMAND ----------

from datetime import datetime, timezone

from postop import classify_ground_truth, config

CATEGORIAS_CASO_LIMITE = [
    "alarma_real",
    "falso_positivo",
    "solicitud_diagnostico",
    "pii_mezclada",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Formulario de curaduría por caso
# MAGIC
# MAGIC Por cada caso límite curado a mano, el revisor completa esta estructura antes de
# MAGIC llamar a `submit_edge_case`:
# MAGIC
# MAGIC ```python
# MAGIC caso_limite = {
# MAGIC     "dialogo_id": "...",
# MAGIC     "categoria_caso_limite": "alarma_real",       # una de CATEGORIAS_CASO_LIMITE
# MAGIC     "validado_por": "nombre.apellido@comite",     # NOT NULL antes de publicar a gold_comite (§12)
# MAGIC     "criterio_clinico_ref": "referencia al protocolo que justifica el label esperado",
# MAGIC     "turnos": [...],                              # mismo esquema que dialogos_capa1_limpia
# MAGIC     "label_ground_truth": "rojo",
# MAGIC }
# MAGIC ```

# COMMAND ----------


def submit_edge_case(spark, caso_limite: dict, output_table: str) -> None:
    """Valida `caso_limite` contra `CATEGORIAS_CASO_LIMITE` y contra el motor de
    reglas (`postop.classify_ground_truth.classify`) — un caso "normal" que caiga
    fuera de toda justificación clínica es una señal de mala curaduría (§7) — y
    luego hace MERGE en `silver.dialogos_capa3_limite`.

    La comprobación contra el motor de reglas es solo un AVISO, no bloquea el envío:
    por diseño, varios casos límite existen justamente para poner a prueba los bordes
    de la regla (§7) — solo un caso "normal" sin ninguna justificación clínica sería
    una señal real de mala curaduría, y eso lo decide el revisor humano, no este código.
    """
    categoria = caso_limite.get("categoria_caso_limite")
    if categoria not in CATEGORIAS_CASO_LIMITE:
        raise ValueError(f"categoria_caso_limite inválida: {categoria!r} — debe ser una de {CATEGORIAS_CASO_LIMITE}")
    if not caso_limite.get("validado_por"):
        raise ValueError("validado_por es obligatorio antes de publicar a gold_comite (§12)")
    if not caso_limite.get("criterio_clinico_ref"):
        raise ValueError("criterio_clinico_ref es obligatorio (§10)")

    sintomas = caso_limite.get("sintomas")
    if sintomas:
        regla_label = classify_ground_truth.classify(sintomas)
        if regla_label != caso_limite.get("label_ground_truth"):
            print(
                f"[curate_edge_cases] aviso: el motor de reglas clasificaría este caso como "
                f"'{regla_label}', no '{caso_limite.get('label_ground_truth')}' — revisar si es "
                f"intencional antes de aprobarlo (§7)"
            )

    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    generado_ts = datetime.now(timezone.utc)
    rows = [
        {
            "dialogo_id": turno["dialogo_id"],
            "caso_id": caso_limite["caso_id"],
            "paciente_id": caso_limite["paciente_id"],
            "dia_postop": caso_limite["dia_postop"],
            "turno_idx": turno["turno_idx"],
            "hablante": turno["hablante"],
            "texto": turno["texto"],
            "label_ground_truth": caso_limite["label_ground_truth"],
            "estilo_paciente": caso_limite.get("estilo_paciente", "n/a"),
            "modelo_paciente": caso_limite.get("modelo_paciente", "curado_manual"),
            "modelo_agente": caso_limite.get("modelo_agente", "curado_manual"),
            "prompt_tokens": None,
            "completion_tokens": None,
            "generado_ts": generado_ts,
            "categoria_caso_limite": categoria,
            "validado_por": caso_limite["validado_por"],
            "criterio_clinico_ref": caso_limite["criterio_clinico_ref"],
        }
        for turno in caso_limite["turnos"]
    ]

    df_nuevo = spark.createDataFrame(rows, schema=schemas.DIALOGOS_CAPA3_LIMITE_SCHEMA)
    df_nuevo.createOrReplaceTempView("_staging_caso_limite")
    spark.sql(
        f"""
        MERGE INTO {output_table} AS destino
        USING _staging_caso_limite AS origen
        ON destino.dialogo_id = origen.dialogo_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Uso
# MAGIC
# MAGIC ```python
# MAGIC cfg = config.load_config()
# MAGIC output_table = config.table_fqn("silver", "dialogos_capa3_limite", cfg)
# MAGIC submit_edge_case(spark, caso_limite, output_table)
# MAGIC ```
