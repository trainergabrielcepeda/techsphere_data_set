-- silver.trayectorias_postop — Componente 1 / brecha de granularidad temporal (§5.3).
-- Simulador probabilístico complementario: una fila por (paciente, día de llamada),
-- con el vector de 6 síntomas del reto. El arquetipo elegido debe ser consistente con
-- perfiles_pacientes.complicacion_encounter (nunca puede contradecir lo que Synthea
-- ya decidió a nivel macro para ese paciente).

CREATE TABLE IF NOT EXISTS postop_dataset.silver.trayectorias_postop (
  trayectoria_id        STRING      NOT NULL COMMENT 'PK',
  paciente_id           STRING      NOT NULL COMMENT 'FK a perfiles_pacientes',
  dia_postop            INT         NOT NULL COMMENT 'día post-operatorio de la llamada: 1, 3, 7, 14 (configurable, conf/project.yml trajectories.call_days)',
  arquetipo_trayectoria STRING      NOT NULL COMMENT 'recuperacion_normal | complicacion_leve_vigilancia | complicacion_real (§5.3)',
  dolor_nrs             INT         NOT NULL COMMENT 'escala numérica de dolor 0-10',
  fiebre_c              DOUBLE      NOT NULL COMMENT 'temperatura corporal en °C',
  movilidad             STRING      NOT NULL,
  herida                STRING      NOT NULL COMMENT 'estado de la herida quirúrgica, p.ej. normal | eritema_leve | dehiscencia | secrecion_purulenta',
  apetito               STRING      NOT NULL,
  sueno                 STRING      NOT NULL,
  seed                  INT         NOT NULL COMMENT 'reproducibilidad determinística por paciente',
  generado_ts           TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 1 §5.3 — serie diaria de síntomas de seguimiento, complementa (no reemplaza) el módulo clínico Synthea';
