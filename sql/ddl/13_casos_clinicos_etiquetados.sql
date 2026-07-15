-- silver.casos_clinicos_etiquetados — Componente 3, motor de ground-truth (§7).
-- El label NO lo asigna el LLM: se calcula aquí, determinísticamente, a partir del
-- vector de síntomas de trayectorias_postop, ANTES de generar cualquier conversación.
-- La regla y el label quedan versionados junto al dato (regla_version), no en un
-- notebook desconectado.

CREATE TABLE IF NOT EXISTS postop_dataset.silver.casos_clinicos_etiquetados (
  caso_id               STRING      NOT NULL COMMENT 'PK',
  paciente_id           STRING      NOT NULL COMMENT 'FK a perfiles_pacientes_co',
  trayectoria_id        STRING      NOT NULL COMMENT 'FK a trayectorias_postop — vector de síntomas de entrada',
  dia_postop            INT         NOT NULL,

  -- Vector de síntomas de entrada, duplicado desde trayectorias_postop para que el
  -- label quede auditable junto a los valores que lo produjeron sin un join adicional.
  dolor_nrs             INT         NOT NULL,
  fiebre_c              DOUBLE      NOT NULL,
  movilidad             STRING      NOT NULL,
  herida                STRING      NOT NULL,
  apetito               STRING      NOT NULL,
  sueno                 STRING      NOT NULL,

  label                 STRING      NOT NULL COMMENT 'verde | amarillo | rojo — calculado por classify_ground_truth.classify() (§7)',
  regla_version         STRING      NOT NULL COMMENT 'versión de la regla clínica aplicada, para reproducibilidad si la regla se recalibra',
  clasificado_ts        TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 3 — clasificación ground-truth determinística, previa a la simulación dual-LLM (§7)';

ALTER TABLE postop_dataset.silver.casos_clinicos_etiquetados
  ADD CONSTRAINT label_valido CHECK (label IN ('verde', 'amarillo', 'rojo'));
