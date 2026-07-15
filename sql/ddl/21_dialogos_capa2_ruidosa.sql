-- silver.dialogos_capa2_ruidosa — Componente 5, inyector de ruido (§9).
-- Generada por UDF parametrizable por intensidad (1-5) aplicada sobre
-- dialogos_capa1_limpia — NUNCA in-place, Capa 1 es inmutable una vez generada.
-- label_ground_truth se hereda sin cambios desde Capa 1: el ruido afecta la
-- conversación, nunca el label (auditado también por noise_mapping_log, §9.2).

CREATE TABLE IF NOT EXISTS postop_dataset.silver.dialogos_capa2_ruidosa (
  dialogo_id            STRING      NOT NULL COMMENT 'PK (capa 2, distinto del dialogo_id de capa 1)',
  dialogo_id_capa1      STRING      NOT NULL COMMENT 'FK a dialogos_capa1_limpia — mismo diálogo antes de ruido',
  caso_id               STRING      NOT NULL,
  paciente_id           STRING      NOT NULL,
  dia_postop            INT         NOT NULL,
  turno_idx             INT         NOT NULL,
  hablante              STRING      NOT NULL COMMENT 'paciente | agente | tercero (cambio de interlocutor, §9.1)',
  texto                 STRING      NOT NULL COMMENT 'texto con ruido aplicado (o idéntico a capa 1 si el turno no fue afectado)',
  label_ground_truth    STRING      NOT NULL COMMENT 'heredado sin cambios desde Capa 1 — nunca recalculado (§9.2)',
  estilo_paciente       STRING      NOT NULL,
  modelo_paciente       STRING      NOT NULL,
  modelo_agente         STRING      NOT NULL,
  intensidad_ruido      INT         COMMENT 'nivel 1-5 aplicado a esta fila, NULL si el turno no fue afectado',
  generado_ts           TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 5 — Capa 2: ruidosa, para medir degradación de clasificación por tipo de ruido (§9)';

ALTER TABLE postop_dataset.silver.dialogos_capa2_ruidosa
  ADD CONSTRAINT label_valido CHECK (label_ground_truth IN ('verde', 'amarillo', 'rojo'));

ALTER TABLE postop_dataset.silver.dialogos_capa2_ruidosa
  ADD CONSTRAINT intensidad_valida CHECK (intensidad_ruido IS NULL OR intensidad_ruido BETWEEN 1 AND 5);
