-- silver.perfiles_pacientes_co — Componente 2, adaptación geográfica Colombia (§6).
-- Salida de adapt_to_colombia(df): reemplaza la capa demográfica de perfiles_pacientes,
-- con la sustitución DECLARADA en columnas de auditoría (no oculta) — responde
-- directamente al criterio de rechazo §7 de la ficha ("sesgo geográfico no declarado").

CREATE TABLE IF NOT EXISTS postop_dataset.silver.perfiles_pacientes_co (
  paciente_id           STRING      NOT NULL COMMENT 'PK — mismo paciente_id que perfiles_pacientes',
  nombre_completo       STRING      NOT NULL COMMENT 'Faker(locale="es_CO")',
  direccion             STRING      NOT NULL COMMENT 'Faker(locale="es_CO")',
  ciudad                STRING      NOT NULL COMMENT 'tabla de referencia DANE (municipios)',
  departamento          STRING      NOT NULL COMMENT 'tabla de referencia DANE (departamentos)',
  documento_cc          STRING      NOT NULL COMMENT 'cédula sintética, formato válido, rango no colisionable con cédulas reales',
  eps                   STRING      NOT NULL COMMENT 'lista curada estática: Sura, Sanitas, Compensar, Nueva EPS, etc.',

  -- Columnas de auditoría obligatorias (§6) — la declaración vive en el dato.
  source_country        STRING      NOT NULL COMMENT 'valor original antes de adaptar, siempre US',
  adapted_country       STRING      NOT NULL COMMENT 'siempre CO',
  adaptation_fields     ARRAY<STRING> NOT NULL COMMENT 'columnas efectivamente reemplazadas en esta fila',
  adaptation_ts         TIMESTAMP   NOT NULL
)
USING DELTA
COMMENT 'Componente 2 — adaptación geográfica Colombia, determinística por seed de paciente (§6)';
