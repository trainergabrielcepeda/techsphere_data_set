-- silver.perfiles_pacientes — Componente 1 (Diseño Técnico §5).
-- Perfil de paciente parseado desde bronze.raw_synthea_bundles (JSON/FHIR de
-- PySynthea o, si el spike de §5.2 lo requiere, del Synthea .jar original vía
-- Job Task tipo JAR — mismo esquema, misma tabla, columna synthea_runtime distingue el origen).

CREATE TABLE IF NOT EXISTS postop_dataset.silver.perfiles_pacientes (
  paciente_id           STRING      NOT NULL COMMENT 'PK — patient id original de Synthea/PySynthea',
  bundle_id             STRING      NOT NULL COMMENT 'FK a bronze.raw_synthea_bundles',
  synthea_runtime       STRING      COMMENT 'pysynthea | synthea_jar (§5.2)',
  modulo_synthea        STRING      NOT NULL COMMENT 'módulo de la allowlist §5.1: appendicitis | cholecystitis | colorectal_cancer | total_joint_replacement | breast_cancer',
  procedimiento         STRING      NOT NULL COMMENT 'procedimiento quirúrgico asociado al módulo',
  fecha_cirugia         DATE        NOT NULL,
  edad                  INT         NOT NULL,
  genero                STRING,
  comorbilidades        ARRAY<STRING> COMMENT 'condiciones preexistentes relevantes del bundle Synthea',
  complicacion_encounter BOOLEAN    NOT NULL COMMENT 'TRUE si Synthea generó una readmisión/complicación en el encounter posterior — insumo obligatorio de consistencia para simulate_postop_trajectories (§5.3)',
  generado_ts           TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 1 — perfiles de paciente base (demografía US, intacta antes de adapt_colombia)';
