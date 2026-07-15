-- silver.dialogos_capa3_limite — Componente 6, casos límite (§10).
-- Mismo esquema que Capa 1 + columnas de curaduría manual. NUNCA pasa por el
-- inyector de ruido ni se expone en gold_participantes. Grant restringido desde el
-- momento de creación (§4, §10) — no depende de un paso manual posterior.

CREATE TABLE IF NOT EXISTS postop_dataset.silver.dialogos_capa3_limite (
  dialogo_id             STRING      NOT NULL COMMENT 'PK',
  caso_id                STRING      NOT NULL COMMENT 'FK a casos_clinicos_etiquetados',
  paciente_id            STRING      NOT NULL COMMENT 'FK a perfiles_pacientes_co',
  dia_postop             INT         NOT NULL,
  turno_idx              INT         NOT NULL,
  hablante               STRING      NOT NULL COMMENT 'paciente | agente',
  texto                  STRING      NOT NULL,
  label_ground_truth     STRING      NOT NULL COMMENT 'verde | amarillo | rojo',
  estilo_paciente        STRING      NOT NULL,
  modelo_paciente        STRING      NOT NULL,
  modelo_agente          STRING      NOT NULL,
  prompt_tokens          INT,
  completion_tokens      INT,
  generado_ts            TIMESTAMP   NOT NULL,

  -- Columnas propias de Capa 3 (§10).
  categoria_caso_limite  STRING      NOT NULL COMMENT 'alarma_real | falso_positivo | solicitud_diagnostico | pii_mezclada',
  validado_por           STRING      COMMENT 'requerido (NOT NULL) antes de publicar a gold_comite — verificado como expectativa de calidad (§12)',
  criterio_clinico_ref   STRING      NOT NULL COMMENT 'referencia al protocolo clínico que justifica el label esperado'
)
USING DELTA
COMMENT 'Componente 6 — Capa 3: casos límite curados a mano, examen objetivo del comité (§10)';

ALTER TABLE postop_dataset.silver.dialogos_capa3_limite
  ADD CONSTRAINT label_valido CHECK (label_ground_truth IN ('verde', 'amarillo', 'rojo'));

ALTER TABLE postop_dataset.silver.dialogos_capa3_limite
  ADD CONSTRAINT categoria_valida CHECK (
    categoria_caso_limite IN ('alarma_real', 'falso_positivo', 'solicitud_diagnostico', 'pii_mezclada')
  );

-- ACL restringido desde la creación de la tabla — nunca un paso manual posterior (§4, §10).
-- Plan 02 (Free Edition): sin grupos de Unity Catalog disponibles (ver
-- sql/ddl/30_publish_gold_grants.sql) — `account users` sustituye a `equipos_participantes`;
-- el comité recibe el grant por email individual (conf/project.yml governance.committee_emails).
REVOKE SELECT ON TABLE postop_dataset.silver.dialogos_capa3_limite FROM `account users`;
-- GRANT SELECT ON TABLE postop_dataset.silver.dialogos_capa3_limite TO `<committee_email>`;
-- un GRANT por entrada de governance.committee_emails, ejecutado en tiempo de publicación.
