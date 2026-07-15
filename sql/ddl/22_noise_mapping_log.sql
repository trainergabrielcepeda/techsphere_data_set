-- silver.noise_mapping_log — trazabilidad Capa 1 → Capa 2 (§9.2).
-- Entregable obligatorio de la ficha (§6): "Documentación de mapeo Capa 1 → Capa 2".
-- Cada transformación de ruido aplicada escribe una fila aquí; ninguna transformación
-- es "silenciosa" (validado como expectativa de calidad, §12).

CREATE TABLE IF NOT EXISTS postop_dataset.silver.noise_mapping_log (
  mapping_id            STRING      NOT NULL COMMENT 'PK',
  dialogo_id_capa1      STRING      NOT NULL COMMENT 'FK a dialogos_capa1_limpia',
  dialogo_id_capa2      STRING      NOT NULL COMMENT 'FK a dialogos_capa2_ruidosa',
  turno_idx_afectado    INT         NOT NULL,
  tipo_ruido            STRING      NOT NULL COMMENT 'ruido_stt | modismo_regional | respuesta_ambigua | contradiccion | informacion_faltante | cambio_interlocutor (§9.1)',
  intensidad            INT         NOT NULL COMMENT '1-5',
  texto_original        STRING      NOT NULL,
  texto_ruidoso         STRING      NOT NULL,
  seed                  INT         NOT NULL COMMENT 'reproducibilidad determinística de la fila de Capa 2 a partir de Capa 1 + seed',
  aplicado_ts           TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Trazabilidad Capa 1 → Capa 2 (§9.2) — permite medir degradación por tipo de ruido y auditar que el label nunca se recalculó';

ALTER TABLE postop_dataset.silver.noise_mapping_log
  ADD CONSTRAINT intensidad_valida CHECK (intensidad BETWEEN 1 AND 5);
