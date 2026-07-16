-- silver.alertas_calidad — Plan 09: alertas de calidad NO bloqueantes de §12.
-- check_casos_clinicos_etiquetados_balance (antes check_casos_clinicos_etiquetados) dejó
-- de bloquear publish_gold — con corridas de muestra pequeña (10-40 pacientes) el balance
-- exacto de labels es difícil de alcanzar sin forzar el generador, y el objetivo actual
-- es alimentar un modelo posterior con datos reales, no una publicación "perfectamente
-- balanceada". Sus mensajes quedan registrados aquí en vez de abortar la publicación —
-- append-only: cada corrida agrega sus propias alertas, no reemplaza las anteriores.
--
-- Visible para cualquier consumidor del dataset, no solo el equipo de ingeniería — grants
-- explícitos en sql/ddl/30_publish_gold_grants.sql (silver está oculto por defecto para
-- account users; esta tabla es la excepción declarada, mismo patrón que
-- silver.dialogos_capa3_limite para el comité).

CREATE TABLE IF NOT EXISTS postop_dataset.silver.alertas_calidad (
  alerta_id     STRING     NOT NULL COMMENT 'PK',
  check_nombre  STRING     NOT NULL COMMENT 'expectativa de §12 que generó la alerta',
  detalle       STRING     NOT NULL COMMENT 'mensaje descriptivo — el mismo texto que antes solo se imprimía en el log de publish_gold',
  severidad     STRING     NOT NULL COMMENT 'advertencia — única severidad hoy (las expectativas críticas siguen bloqueando publish_gold y nunca llegan aquí)',
  catalog_run   STRING     NOT NULL COMMENT 'catálogo de la corrida que generó la alerta',
  generado_ts   TIMESTAMP  NOT NULL
)
USING DELTA
COMMENT 'Alertas de calidad no bloqueantes (Plan 09) — expectativas de §12 que no impiden publicar pero deben quedar visibles para quien consuma el dataset';

ALTER TABLE postop_dataset.silver.alertas_calidad
  ADD CONSTRAINT severidad_valida CHECK (severidad IN ('advertencia'));
