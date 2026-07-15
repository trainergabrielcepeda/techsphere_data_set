-- publish_gold — grants + vistas finales por audiencia (§4, §16).
-- Ejecutado como parte del job de publicación (publish_gold.py), no manualmente.
-- Esto es lo que resuelve, con gobierno nativo de Unity Catalog, el requisito
-- "ocultar Capa 3 al resto de participantes" — y da lineage automático entre
-- dialogos_capa1_limpia → dialogos_capa2_ruidosa como evidencia complementaria
-- del entregable "documentación de mapeo Capa 1 → Capa 2".
--
-- Nota (Plan 02, Free Edition): el diseño original otorga estos grants a grupos de
-- Unity Catalog (`equipos_participantes`, `comite_academico`). Databricks Free Edition
-- no tiene account console ni SSO/SCIM, así que no hay forma de crear esos grupos.
-- Sustituto: `account users` (principal nativo de Unity Catalog para todo usuario del
-- metastore) cubre a los participantes; el comité se enumera por email, tomado de
-- conf/project.yml (governance.committee_emails). En un workspace pagado, revertir a
-- grupos nombrados.

GRANT USE CATALOG ON CATALOG postop_dataset TO `account users`;

GRANT USE SCHEMA, SELECT ON SCHEMA postop_dataset.gold_participantes TO `account users`;
-- El comité se otorga por email individual (ver publish_gold.py / conf/project.yml
-- governance.committee_emails) porque no existe el grupo `comite_academico` en Free
-- Edition; cada email listado ahí recibe el mismo GRANT que este placeholder documenta:
--   GRANT USE SCHEMA, SELECT ON SCHEMA postop_dataset.gold_comite TO `<committee_email>`;

-- Explícito: nadie fuera del comité puede ver silver.dialogos_capa3_limite ni gold_comite.
REVOKE SELECT ON SCHEMA postop_dataset.silver FROM `account users`;
REVOKE SELECT ON SCHEMA postop_dataset.gold_comite FROM `account users`;

-- gold_participantes.dataset_final — Capas 1+2 solamente (§4).
CREATE OR REPLACE VIEW postop_dataset.gold_participantes.dataset_final AS
SELECT
  dialogo_id, caso_id, paciente_id, dia_postop, turno_idx, hablante, texto,
  label_ground_truth, estilo_paciente, modelo_paciente, modelo_agente,
  'capa1_limpia' AS capa, generado_ts
FROM postop_dataset.silver.dialogos_capa1_limpia
UNION ALL
SELECT
  dialogo_id, caso_id, paciente_id, dia_postop, turno_idx, hablante, texto,
  label_ground_truth, estilo_paciente, modelo_paciente, modelo_agente,
  'capa2_ruidosa' AS capa, generado_ts
FROM postop_dataset.silver.dialogos_capa2_ruidosa;

-- gold_comite.dataset_final_completo — Capas 1+2+3, para evaluación objetiva (§4).
CREATE OR REPLACE VIEW postop_dataset.gold_comite.dataset_final_completo AS
SELECT
  dialogo_id, caso_id, paciente_id, dia_postop, turno_idx, hablante, texto,
  label_ground_truth, estilo_paciente, modelo_paciente, modelo_agente,
  'capa1_limpia' AS capa, generado_ts
FROM postop_dataset.silver.dialogos_capa1_limpia
UNION ALL
SELECT
  dialogo_id, caso_id, paciente_id, dia_postop, turno_idx, hablante, texto,
  label_ground_truth, estilo_paciente, modelo_paciente, modelo_agente,
  'capa2_ruidosa' AS capa, generado_ts
FROM postop_dataset.silver.dialogos_capa2_ruidosa
UNION ALL
SELECT
  dialogo_id, caso_id, paciente_id, dia_postop, turno_idx, hablante, texto,
  label_ground_truth, estilo_paciente, modelo_paciente, modelo_agente,
  'capa3_limite' AS capa, generado_ts
FROM postop_dataset.silver.dialogos_capa3_limite;
