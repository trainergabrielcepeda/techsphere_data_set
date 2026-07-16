# techsphere_data_set

Dataset — Reto Tech Sphere 2026: agente de voz para seguimiento post-operatorio de
pacientes.

- **Ficha de especificación:** `specs/Ficha Técnica — Dataset Seguimiento Post-Operatorio.pdf`
- **Diseño técnico:** `specs/Diseño Técnico — Dataset Seguimiento Post-Operatorio.md`
- **Documentación del generador (arquitectura, guía de instalación, prerrequisitos y
  advertencias):** `docs/generador-datos.md`
- **Plan de implementación (scaffold):** `Plans/01-scaffold-databricks-asset-bundle.md`

## ¿Quieres replicar el dataset o correrlo tú mismo?

Si quieres desplegar el pipeline en tu propio workspace de Databricks (por ejemplo para
probar o extender el generador), empieza por `docs/generador-datos.md` — tiene la
arquitectura completa, una guía de instalación paso a paso, los prerrequisitos
(Databricks CLI, API key de un proveedor LLM, etc.) y las advertencias importantes
(Free Edition es serverless-only, las reglas clínicas no están validadas por un comité
todavía, todos los datos son sintéticos). Los comandos de despliegue rápido están más
abajo, en "Desplegar el bundle".

## Estado

Scaffold inicial del Databricks Asset Bundle (Plan 01): estructura, contratos de
datos (DDL), Workflow y stubs de los 6 componentes del pipeline. **Ningún
componente tiene lógica de negocio implementada todavía** — cada `src/postop/*.py`
declara su firma, su esquema Spark explícito y levanta `NotImplementedError`. La
implementación real de cada componente es un plan de seguimiento independiente
(ver Diseño Técnico §17, próximos pasos).

## Estructura del proyecto

```
databricks.yml                  # Databricks Asset Bundle: targets dev/prod, variables
requirements.txt                 # stack: pyspark, delta-spark, pysynthea, faker, databricks-sdk, anthropic
conf/project.yml                 # catálogo/esquemas, allowlist de módulos Synthea, días de llamada, piloto
resources/postop_pipeline.job.yml  # Databricks Workflow — DAG de 7 tasks (§11)
sql/ddl/                         # contratos de datos versionados, un .sql por tabla (§4, §8.3, §9.2, §10)
src/postop/                      # paquete Python del pipeline (config, schemas, 6 componentes)
prompts/                         # system prompts del LLM-paciente / LLM-agente, documentados (§8.1)
notebooks/curate_edge_cases.py   # curaduría manual de Capa 3 (Componente 6, human-in-the-loop)
docs/generador-datos.md          # documentación del generador: arquitectura, guía de instalación, caveats
tests/                           # pruebas del paquete postop
```

## Catálogo Unity Catalog

Un catálogo (`postop_dataset`), tres esquemas medallion (`bronze`, `silver`) y dos
esquemas gold separados por audiencia (`gold_participantes`, `gold_comite`) — esto
oculta la Capa 3 (casos límite) al resto de participantes de forma nativa (Diseño
Técnico §4).

## Desplegar el bundle

```bash
pip install -r requirements.txt

databricks bundle validate -t dev
databricks bundle deploy   -t dev
databricks bundle run postop_pipeline -t dev
```

El host y las credenciales del workspace se resuelven vía perfil de
`databricks configure` o las variables de entorno `DATABRICKS_HOST` /
`DATABRICKS_TOKEN` — nunca se fijan en `databricks.yml` ni en el repo (§13).

## Correr las pruebas

```bash
pytest -q
```
