"""Tabla de referencia DANE — departamentos de Colombia por población (Diseño Técnico §6).

Fuente: proyecciones DANE 2025 (dane.gov.co, nota técnica de proyecciones de población,
jul-2025, total nacional 53.057.212 habitantes). Las cifras por departamento se tomaron de
la tabla derivada de DANE consultada el 2026-07-15 (total agregado 53.110.545 — la pequeña
diferencia frente al total oficial es redondeo de la fuente secundaria y no afecta los
pesos relativos usados aquí). Ciudad = capital departamental en todos los casos, salvo
Cundinamarca (se usa Soacha, el municipio más poblado del departamento fuera de Bogotá,
ya que Bogotá D.C. es una entidad territorial separada en esta tabla).

Usado por ``adapt_colombia.adapt_to_colombia`` (§6) para muestrear (departamento, ciudad)
ponderado por población real, en vez de la selección uniforme por defecto de Faker — esto
es lo que hace que la adaptación a Colombia sea representativa de la distribución
geográfica real del país (Plan 05), no solo geográficamente plausible.
"""

from __future__ import annotations

import functools
import random

# (departamento, ciudad_capital, población_2025)
DEPARTAMENTOS = [
    ("Bogotá D.C.", "Bogotá D.C.", 7_937_898),
    ("Antioquia", "Medellín", 6_951_825),
    ("Valle del Cauca", "Cali", 4_652_512),
    ("Cundinamarca", "Soacha", 3_657_407),
    ("Atlántico", "Barranquilla", 2_845_169),
    ("Santander", "Bucaramanga", 2_393_214),
    ("Bolívar", "Cartagena", 2_278_770),
    ("Córdoba", "Montería", 1_929_336),
    ("Nariño", "Pasto", 1_719_281),
    ("Norte de Santander", "Cúcuta", 1_717_992),
    ("Cauca", "Popayán", 1_590_171),
    ("Magdalena", "Santa Marta", 1_529_038),
    ("Cesar", "Valledupar", 1_414_859),
    ("Tolima", "Ibagué", 1_386_826),
    ("Boyacá", "Tunja", 1_324_122),
    ("Huila", "Neiva", 1_205_318),
    ("Meta", "Villavicencio", 1_160_351),
    ("La Guajira", "Riohacha", 1_073_851),
    ("Caldas", "Manizales", 1_051_282),
    ("Sucre", "Sincelejo", 1_016_826),
    ("Risaralda", "Pereira", 974_639),
    ("Chocó", "Quibdó", 615_082),
    ("Quindío", "Armenia", 568_560),
    ("Casanare", "Yopal", 481_938),
    ("Caquetá", "Florencia", 430_884),
    ("Putumayo", "Mocoa", 393_988),
    ("Arauca", "Arauca", 320_723),
    ("Vichada", "Puerto Carreño", 127_467),
    ("Guaviare", "San José del Guaviare", 103_237),
    ("Amazonas", "Leticia", 87_480),
    ("San Andrés y Providencia", "San Andrés", 62_181),
    ("Guainía", "Inírida", 59_240),
    ("Vaupés", "Mitú", 49_142),
]


@functools.lru_cache(maxsize=1)
def department_weights() -> tuple[tuple[str, str, float], ...]:
    """(departamento, ciudad, peso_poblacional) — pesos normalizados, suman 1.0."""
    total = sum(poblacion for _, _, poblacion in DEPARTAMENTOS)
    return tuple((depto, ciudad, poblacion / total) for depto, ciudad, poblacion in DEPARTAMENTOS)


def sample_departamento_ciudad(rng: random.Random) -> tuple[str, str]:
    """Muestrea (departamento, ciudad) ponderado por población real DANE."""
    entries = department_weights()
    nombres = [(depto, ciudad) for depto, ciudad, _ in entries]
    pesos = [peso for _, _, peso in entries]
    return rng.choices(nombres, weights=pesos, k=1)[0]
