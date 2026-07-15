"""Carga de configuración del proyecto y resolución de nombres de tres niveles
(catalog.schema.table) para Unity Catalog — Diseño Técnico §4.

Los valores de negocio (nombre de catálogo, allowlist de módulos Synthea, días de
llamada de seguimiento, etc.) viven en conf/project.yml, no hardcodeados en el
código del pipeline.
"""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "conf" / "project.yml"


@functools.lru_cache(maxsize=None)
def load_config(path: Optional[str] = None) -> dict[str, Any]:
    """Lee conf/project.yml (o la ruta dada) y lo devuelve como dict. Cacheado por proceso."""
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def catalog_name(config: Optional[dict[str, Any]] = None) -> str:
    """Nombre del catálogo Unity Catalog.

    En Databricks, este valor puede venir sobrescrito por la variable de bundle
    ``catalog_name`` (ver databricks.yml, target dev vs. prod) — el config.py
    resuelve el default declarado en conf/project.yml cuando no se pasa override.
    """
    config = config or load_config()
    return config["catalog"]["name"]


def schema_fqn(schema_key: str, config: Optional[dict[str, Any]] = None) -> str:
    """``catalog.schema`` para una clave declarada en conf/project.yml (catalog.schemas).

    Ej.: ``schema_fqn("silver")`` -> ``"postop_dataset.silver"``.
    """
    config = config or load_config()
    schema = config["catalog"]["schemas"][schema_key]
    return f"{catalog_name(config)}.{schema}"


def table_fqn(schema_key: str, table_name: str, config: Optional[dict[str, Any]] = None) -> str:
    """``catalog.schema.table`` de tres niveles, listo para ``spark.table()``/``spark.sql()``."""
    return f"{schema_fqn(schema_key, config)}.{table_name}"


def stable_seed(*parts: object) -> int:
    """Seed determinística e independiente del proceso (a diferencia de ``hash()``, que
    Python aleatoriza por proceso para strings vía ``PYTHONHASHSEED``).

    Usado en todo el pipeline (Plan 05) para derivar un ``random.Random`` reproducible por
    entidad (p. ej. ``random.Random(stable_seed("adapt_colombia", paciente_id, seed))``) —
    misma entrada, mismo generador de números aleatorios en cualquier re-ejecución.
    """
    joined = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
