-- Modelo de catálogo (Unity Catalog) — Diseño Técnico §4.
-- Un catálogo dedicado al reto, tres esquemas medallion + dos esquemas gold separados
-- por audiencia. La separación gold_participantes / gold_comite es lo que resuelve el
-- requisito "ocultar Capa 3 a participantes" de forma nativa, sin lógica de aplicación.
--
-- Nota: el nombre de catálogo aquí (postop_dataset) es el valor por defecto de
-- conf/project.yml / la variable de bundle catalog_name. Los scripts en src/postop/
-- parametrizan el catálogo en tiempo de ejecución; estos DDL documentan el contrato
-- con el nombre por defecto.

CREATE CATALOG IF NOT EXISTS postop_dataset;

CREATE SCHEMA IF NOT EXISTS postop_dataset.bronze;
CREATE SCHEMA IF NOT EXISTS postop_dataset.silver;
CREATE SCHEMA IF NOT EXISTS postop_dataset.gold_participantes;
CREATE SCHEMA IF NOT EXISTS postop_dataset.gold_comite;

-- Volume para el JSON/FHIR crudo producido por PySynthea (Componente 1, §5).
CREATE VOLUME IF NOT EXISTS postop_dataset.bronze.raw_synthea_bundles;
