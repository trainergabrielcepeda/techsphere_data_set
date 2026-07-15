-- silver.dialogos_capa1_limpia — Componente 4, simulación conversacional dual-LLM (§8.3).
-- Esquema exacto especificado en el diseño técnico. Ningún LLM ve label_ground_truth
-- durante la generación (§8.1) — se adjunta post-hoc para no contaminar el lenguaje.

CREATE TABLE IF NOT EXISTS postop_dataset.silver.dialogos_capa1_limpia (
  dialogo_id            STRING      NOT NULL COMMENT 'PK',
  caso_id               STRING      NOT NULL COMMENT 'FK a casos_clinicos_etiquetados',
  paciente_id           STRING      NOT NULL COMMENT 'FK a perfiles_pacientes_co',
  dia_postop            INT         NOT NULL,
  turno_idx             INT         NOT NULL COMMENT 'orden dentro de la conversación',
  hablante              STRING      NOT NULL COMMENT 'paciente | agente',
  texto                 STRING      NOT NULL,
  label_ground_truth    STRING      NOT NULL COMMENT 'verde | amarillo | rojo — a nivel de caso, no de turno',
  estilo_paciente       STRING      NOT NULL COMMENT 'colaborativo | evasivo | ansioso | minimizador_sintomas | confundido (§8.1)',
  modelo_paciente       STRING      NOT NULL COMMENT 'id del modelo LLM usado para el rol paciente',
  modelo_agente         STRING      NOT NULL COMMENT 'id del modelo LLM usado para el rol agente',
  prompt_tokens         INT         COMMENT 'control de costo (§8.2)',
  completion_tokens     INT,
  generado_ts           TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 4 — Capa 1: base limpia + ground-truth, entregable de referencia (§8.3)';

ALTER TABLE postop_dataset.silver.dialogos_capa1_limpia
  ADD CONSTRAINT label_valido CHECK (label_ground_truth IN ('verde', 'amarillo', 'rojo'));

ALTER TABLE postop_dataset.silver.dialogos_capa1_limpia
  ADD CONSTRAINT hablante_valido CHECK (hablante IN ('paciente', 'agente'));
