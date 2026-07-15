"""Pruebas de resolución catalog.schema.table (Plan 06 Fase 4).

Regresión de un bug real: antes de Fase 4, catalog_name()/schema_fqn()/table_fqn()
ignoraban por completo cualquier override y siempre resolvían el catálogo de
conf/project.yml — cada script pasaba --catalog en la CLI pero ese valor nunca llegaba a
afectar qué tabla se leía/escribía. Encontrado solo al correr el job real contra
postop_dataset_dev (SCHEMA_NOT_FOUND: postop_dataset.silver, catálogo que ni siquiera
existe en el workspace).
"""

from postop import config

_CFG = {"catalog": {"name": "postop_dataset", "schemas": {"silver": "silver"}}}


def test_catalog_name_usa_el_default_de_conf_sin_override():
    assert config.catalog_name(_CFG) == "postop_dataset"


def test_catalog_name_respeta_el_override():
    assert config.catalog_name(_CFG, catalog_override="postop_dataset_dev") == "postop_dataset_dev"


def test_catalog_name_ignora_override_vacio():
    assert config.catalog_name(_CFG, catalog_override="") == "postop_dataset"


def test_schema_fqn_propaga_el_override():
    assert config.schema_fqn("silver", _CFG, catalog_override="postop_dataset_dev") == "postop_dataset_dev.silver"


def test_table_fqn_propaga_el_override():
    assert (
        config.table_fqn("silver", "perfiles_pacientes", _CFG, catalog_override="postop_dataset_dev")
        == "postop_dataset_dev.silver.perfiles_pacientes"
    )


def test_table_fqn_sin_override_usa_default():
    assert config.table_fqn("silver", "perfiles_pacientes", _CFG) == "postop_dataset.silver.perfiles_pacientes"
