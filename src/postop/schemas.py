"""Esquemas Spark explícitos para cada tabla silver — deben mantenerse en paridad
1:1 con los DDL de sql/ddl/*.sql (nombre de columna, tipo, nullability).

Explicit schemas > inferencia: cualquier drift entre esta paridad y los DDL es un
bug de contrato de datos, no un detalle de implementación (ver skill de data
engineering: "Schema explicitness").
"""

from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# sql/ddl/10_perfiles_pacientes.sql
PERFILES_PACIENTES_SCHEMA = StructType(
    [
        StructField("paciente_id", StringType(), nullable=False),
        StructField("bundle_id", StringType(), nullable=False),
        StructField("synthea_runtime", StringType(), nullable=True),
        StructField("modulo_synthea", StringType(), nullable=False),
        StructField("procedimiento", StringType(), nullable=False),
        StructField("fecha_cirugia", DateType(), nullable=False),
        StructField("edad", IntegerType(), nullable=False),
        StructField("genero", StringType(), nullable=True),
        StructField("comorbilidades", ArrayType(StringType()), nullable=True),
        StructField("complicacion_encounter", BooleanType(), nullable=False),
        StructField("generado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/11_trayectorias_postop.sql
TRAYECTORIAS_POSTOP_SCHEMA = StructType(
    [
        StructField("trayectoria_id", StringType(), nullable=False),
        StructField("paciente_id", StringType(), nullable=False),
        StructField("dia_postop", IntegerType(), nullable=False),
        StructField("arquetipo_trayectoria", StringType(), nullable=False),
        StructField("dolor_nrs", IntegerType(), nullable=False),
        StructField("fiebre_c", DoubleType(), nullable=False),
        StructField("movilidad", StringType(), nullable=False),
        StructField("herida", StringType(), nullable=False),
        StructField("apetito", StringType(), nullable=False),
        StructField("sueno", StringType(), nullable=False),
        StructField("seed", IntegerType(), nullable=False),
        StructField("generado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/12_perfiles_pacientes_co.sql
PERFILES_PACIENTES_CO_SCHEMA = StructType(
    [
        StructField("paciente_id", StringType(), nullable=False),
        StructField("nombre_completo", StringType(), nullable=False),
        StructField("direccion", StringType(), nullable=False),
        StructField("ciudad", StringType(), nullable=False),
        StructField("departamento", StringType(), nullable=False),
        StructField("documento_cc", StringType(), nullable=False),
        StructField("eps", StringType(), nullable=False),
        StructField("source_country", StringType(), nullable=False),
        StructField("adapted_country", StringType(), nullable=False),
        StructField("adaptation_fields", ArrayType(StringType()), nullable=False),
        StructField("adaptation_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/13_casos_clinicos_etiquetados.sql
CASOS_CLINICOS_ETIQUETADOS_SCHEMA = StructType(
    [
        StructField("caso_id", StringType(), nullable=False),
        StructField("paciente_id", StringType(), nullable=False),
        StructField("trayectoria_id", StringType(), nullable=False),
        StructField("dia_postop", IntegerType(), nullable=False),
        StructField("dolor_nrs", IntegerType(), nullable=False),
        StructField("fiebre_c", DoubleType(), nullable=False),
        StructField("movilidad", StringType(), nullable=False),
        StructField("herida", StringType(), nullable=False),
        StructField("apetito", StringType(), nullable=False),
        StructField("sueno", StringType(), nullable=False),
        StructField("label", StringType(), nullable=False),
        StructField("regla_version", StringType(), nullable=False),
        StructField("clasificado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/20_dialogos_capa1_limpia.sql
DIALOGOS_CAPA1_LIMPIA_SCHEMA = StructType(
    [
        StructField("dialogo_id", StringType(), nullable=False),
        StructField("caso_id", StringType(), nullable=False),
        StructField("paciente_id", StringType(), nullable=False),
        StructField("dia_postop", IntegerType(), nullable=False),
        StructField("turno_idx", IntegerType(), nullable=False),
        StructField("hablante", StringType(), nullable=False),
        StructField("texto", StringType(), nullable=False),
        StructField("label_ground_truth", StringType(), nullable=False),
        StructField("estilo_paciente", StringType(), nullable=False),
        StructField("modelo_paciente", StringType(), nullable=False),
        StructField("modelo_agente", StringType(), nullable=False),
        StructField("prompt_tokens", IntegerType(), nullable=True),
        StructField("completion_tokens", IntegerType(), nullable=True),
        StructField("generado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/21_dialogos_capa2_ruidosa.sql
DIALOGOS_CAPA2_RUIDOSA_SCHEMA = StructType(
    [
        StructField("dialogo_id", StringType(), nullable=False),
        StructField("dialogo_id_capa1", StringType(), nullable=False),
        StructField("caso_id", StringType(), nullable=False),
        StructField("paciente_id", StringType(), nullable=False),
        StructField("dia_postop", IntegerType(), nullable=False),
        StructField("turno_idx", IntegerType(), nullable=False),
        StructField("hablante", StringType(), nullable=False),
        StructField("texto", StringType(), nullable=False),
        StructField("label_ground_truth", StringType(), nullable=False),
        StructField("estilo_paciente", StringType(), nullable=False),
        StructField("modelo_paciente", StringType(), nullable=False),
        StructField("modelo_agente", StringType(), nullable=False),
        StructField("intensidad_ruido", IntegerType(), nullable=True),
        StructField("generado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/22_noise_mapping_log.sql
NOISE_MAPPING_LOG_SCHEMA = StructType(
    [
        StructField("mapping_id", StringType(), nullable=False),
        StructField("dialogo_id_capa1", StringType(), nullable=False),
        StructField("dialogo_id_capa2", StringType(), nullable=False),
        StructField("turno_idx_afectado", IntegerType(), nullable=False),
        StructField("tipo_ruido", StringType(), nullable=False),
        StructField("intensidad", IntegerType(), nullable=False),
        StructField("texto_original", StringType(), nullable=False),
        StructField("texto_ruidoso", StringType(), nullable=False),
        StructField("seed", IntegerType(), nullable=False),
        StructField("aplicado_ts", TimestampType(), nullable=False),
    ]
)

# sql/ddl/23_dialogos_capa3_limite.sql
DIALOGOS_CAPA3_LIMITE_SCHEMA = StructType(
    [
        StructField("dialogo_id", StringType(), nullable=False),
        StructField("caso_id", StringType(), nullable=False),
        StructField("paciente_id", StringType(), nullable=False),
        StructField("dia_postop", IntegerType(), nullable=False),
        StructField("turno_idx", IntegerType(), nullable=False),
        StructField("hablante", StringType(), nullable=False),
        StructField("texto", StringType(), nullable=False),
        StructField("label_ground_truth", StringType(), nullable=False),
        StructField("estilo_paciente", StringType(), nullable=False),
        StructField("modelo_paciente", StringType(), nullable=False),
        StructField("modelo_agente", StringType(), nullable=False),
        StructField("prompt_tokens", IntegerType(), nullable=True),
        StructField("completion_tokens", IntegerType(), nullable=True),
        StructField("generado_ts", TimestampType(), nullable=False),
        StructField("categoria_caso_limite", StringType(), nullable=False),
        StructField("validado_por", StringType(), nullable=True),
        StructField("criterio_clinico_ref", StringType(), nullable=False),
    ]
)
