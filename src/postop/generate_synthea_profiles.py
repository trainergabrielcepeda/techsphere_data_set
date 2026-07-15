"""Componente 1 — Generación clínica base (Diseño Técnico §5).

Resultado del spike de validación de riesgo R1 (§5.2, ejecutado como parte de Plan 05):
el paquete `pysynthea` real (PyPI, v1.0.0) NO es un generador de pacientes — es un
downloader/query-tool para una base OMOP de Synthea ya generada y fija (el dataset
pequeño `Synthea27Nj` de OHDSI/EunomiaDatasets, o el export completo desde Zenodo), sin
parámetro de allowlist de módulos ni de seed. El fallback documentado en §5.2 (Synthea
`.jar` como Job Task tipo JAR) tampoco es viable: Databricks Free Edition es
serverless-only (Plan 02), y las tasks de tipo JAR requieren un cluster JVM igual que las
clásicas. Ambos caminos de §5.2 quedan cerrados.

Resolución (Plan 05): generador sintético propio, determinístico, sin dependencia de
runtime externo, calibrado contra los mismos 5 módulos de la allowlist
(conf/project.yml synthea.module_allowlist, §5.1) con parámetros clínicos aproximados
(``clinical_domains.PROCEDURE_CALIBRATION``) — no sustituye validación clínica del
comité, mismo estado provisional que ``classify_ground_truth.REGLA_VERSION``. La
desviación queda declarada en el dato, no oculta: ``perfiles_pacientes.synthea_runtime =
'synthetic_fallback_sin_pysynthea'``.

Escribe:
  - bronze.raw_synthea_bundles (Volume, JSON — un archivo por paciente)
  - silver.perfiles_pacientes  (schemas.PERFILES_PACIENTES_SCHEMA, sql/ddl/10)
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from postop import clinical_domains, config

SYNTHEA_RUNTIME = "synthetic_fallback_sin_pysynthea"

_BASE_FECHA_CIRUGIA = date(2026, 1, 5)


def generate_synthetic_profiles(
    module_allowlist: list[str],
    n_pacientes: int,
    seed: int,
) -> list[dict]:
    """Genera ``n_pacientes`` perfiles sintéticos, repartidos de forma uniforme entre los
    módulos de ``module_allowlist`` (§5.1) para que los 5 procedimientos queden
    representados en la población. Determinístico por ``seed`` — misma entrada, misma
    salida en cualquier re-ejecución (no depende de PySynthea/Synthea, ver docstring del
    módulo).
    """
    if not module_allowlist:
        raise ValueError("module_allowlist no puede estar vacío")

    unknown = sorted(set(module_allowlist) - set(clinical_domains.PROCEDURE_CALIBRATION))
    if unknown:
        raise ValueError(f"módulos sin calibración en clinical_domains.PROCEDURE_CALIBRATION: {unknown}")

    profiles = []
    for i in range(n_pacientes):
        paciente_id = f"pac_{seed}_{i:05d}"
        modulo = module_allowlist[i % len(module_allowlist)]
        calib = clinical_domains.PROCEDURE_CALIBRATION[modulo]
        rng = random.Random(config.stable_seed("perfil_paciente", paciente_id, seed))

        edad = rng.randint(calib["edad_min"], calib["edad_max"])
        genero = rng.choice(["F", "M"])
        comorbilidades = [
            c for c in calib["comorbilidades_pool"] if rng.random() < clinical_domains.COMORBIDITY_INCLUSION_PROB
        ]
        complicacion_encounter = rng.random() < calib["complicacion_prob"]
        fecha_cirugia = _BASE_FECHA_CIRUGIA + timedelta(days=rng.randint(0, 180))

        profiles.append(
            {
                "paciente_id": paciente_id,
                "bundle_id": f"bundle_{paciente_id}",
                "synthea_runtime": SYNTHEA_RUNTIME,
                "modulo_synthea": modulo,
                "procedimiento": calib["procedimiento"],
                "fecha_cirugia": fecha_cirugia.isoformat(),
                "edad": edad,
                "genero": genero,
                "comorbilidades": comorbilidades,
                "complicacion_encounter": complicacion_encounter,
                "generado_ts": datetime.now(timezone.utc).isoformat(),
            }
        )
    return profiles


def write_bundles_to_volume(profiles: list[dict], bronze_volume_path: str) -> None:
    """Escribe un JSON por paciente en ``bronze_volume_path``.

    Los Volumes de Databricks están montados como filesystem POSIX estándar
    (``/Volumes/<catalog>/<schema>/<volume>``) — escribir aquí no requiere Spark.
    """
    out_dir = Path(bronze_volume_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        out_path = out_dir / f"{profile['bundle_id']}.json"
        out_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")


def parse_bundles_to_perfiles_pacientes(spark, bronze_volume_path: str, output_table: str) -> None:
    """Lee los bundles JSON de ``bronze_volume_path`` y escribe
    ``silver.perfiles_pacientes`` con el esquema ``schemas.PERFILES_PACIENTES_SCHEMA``.
    """
    from postop import schemas  # import diferido — pyspark solo existe en el cluster

    bundles = []
    for path in sorted(Path(bronze_volume_path).glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["fecha_cirugia"] = date.fromisoformat(raw["fecha_cirugia"])
        raw["generado_ts"] = datetime.fromisoformat(raw["generado_ts"])
        bundles.append(raw)

    df = spark.createDataFrame(bundles, schema=schemas.PERFILES_PACIENTES_SCHEMA)
    df.write.format("delta").mode("overwrite").saveAsTable(output_table)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Componente 1 — generación de perfiles sintéticos (allowlist §5.1)")
    parser.add_argument("--catalog", required=True, help="Nombre del catálogo Unity Catalog")
    parser.add_argument(
        "--n-pacientes",
        type=int,
        default=None,
        help="Tamaño de la población a generar (default: conf/project.yml population.n_pacientes_representativos)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Seed determinística (default: population.seed)")
    args = parser.parse_args(argv)

    cfg = config.load_config()
    module_allowlist = cfg["synthea"]["module_allowlist"]
    n_pacientes = args.n_pacientes if args.n_pacientes is not None else cfg["population"]["n_pacientes_representativos"]
    seed = args.seed if args.seed is not None else cfg["population"]["seed"]

    bronze_volume_path = f"/Volumes/{args.catalog}/bronze/raw_synthea_bundles"
    output_table = config.table_fqn("silver", "perfiles_pacientes", cfg)

    profiles = generate_synthetic_profiles(module_allowlist, n_pacientes, seed)
    write_bundles_to_volume(profiles, bronze_volume_path)

    from pyspark.sql import SparkSession  # import diferido — solo disponible en el cluster

    spark = SparkSession.builder.getOrCreate()
    parse_bundles_to_perfiles_pacientes(spark=spark, bronze_volume_path=bronze_volume_path, output_table=output_table)


if __name__ == "__main__":
    main()
