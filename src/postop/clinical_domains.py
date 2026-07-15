"""Dominios clínicos compartidos — vector de 6 síntomas del reto (Diseño Técnico §5.3, §7).

Centraliza los valores enumerados de herida/movilidad/apetito/sueño y los parámetros de
distribución por arquetipo de trayectoria (§5.3) y por módulo Synthea/procedimiento (§5.1),
para que ``simulate_postop_trajectories``, ``classify_ground_truth`` y
``generate_synthea_profiles`` no puedan divergir silenciosamente sobre qué valores son
válidos.

Los rangos/probabilidades aquí son aproximaciones de ingeniería ancladas en criterios
clínicos de referencia mencionados en el diseño (vigilancia post-quirúrgica estándar,
criterios CDC de infección de sitio quirúrgico / SIRS para fiebre, criterios de
dehiscencia de herida — §5.3) pero NO sustituyen la validación clínica del comité prevista
en §17 — mismo estado provisional que ``classify_ground_truth.REGLA_VERSION``.
"""

from __future__ import annotations

import random

HERIDA_STATES = ["normal", "eritema_leve", "dehiscencia", "secrecion_purulenta"]
MOVILIDAD_STATES = ["normal", "limitada_esperada", "incapacitante_nueva"]
APETITO_STATES = ["normal", "levemente_disminuido", "muy_disminuido"]
SUENO_STATES = ["normal", "levemente_alterado", "muy_alterado"]

ARCHETYPES = ["recuperacion_normal", "complicacion_leve_vigilancia", "complicacion_real"]

# Calibración por módulo Synthea/procedimiento — allowlist §5.1. Aproximada, pendiente de
# validación clínica (ver docstring del módulo).
#
# complicacion_prob (Plan 05): calibrado no solo contra literatura de referencia sino
# también contra la expectativa de calidad §12 ("ningún label con <10% ni >70%") — con
# el mecanismo de convergencia de sample_symptom_vector de abajo (últimas dos llamadas de
# complicacion_real forzadas a 🔴), un promedio de complicacion_prob ~0.10 (más realista
# clínicamente pero más bajo) deja 🔴 por debajo del piso del 12%. Se sube el promedio a
# ~0.24 a propósito para que una corrida real del pipeline satisfaga §12 sin desbalancear
# artificialmente el resto — sigue siendo una aproximación de ingeniería, no una tasa
# clínica validada (ver docstring del módulo).
PROCEDURE_CALIBRATION = {
    "appendicitis": {
        "procedimiento": "Apendicectomía",
        "edad_min": 15,
        "edad_max": 45,
        "comorbilidades_pool": [],
        "complicacion_prob": 0.25,
    },
    "cholecystitis": {
        "procedimiento": "Colecistectomía",
        "edad_min": 30,
        "edad_max": 70,
        "comorbilidades_pool": ["obesidad", "diabetes_tipo_2", "hipertension"],
        "complicacion_prob": 0.22,
    },
    "colorectal_cancer": {
        "procedimiento": "Colectomía",
        "edad_min": 50,
        "edad_max": 80,
        "comorbilidades_pool": ["hipertension", "diabetes_tipo_2", "enfermedad_cardiovascular", "epoc"],
        "complicacion_prob": 0.50,
    },
    "total_joint_replacement": {
        "procedimiento": "Reemplazo de cadera/rodilla",
        "edad_min": 55,
        "edad_max": 85,
        "comorbilidades_pool": ["osteoartritis", "obesidad", "hipertension", "diabetes_tipo_2"],
        "complicacion_prob": 0.20,
    },
    "breast_cancer": {
        "procedimiento": "Mastectomía",
        "edad_min": 35,
        "edad_max": 75,
        "comorbilidades_pool": ["ansiedad", "hipertension", "diabetes_tipo_2"],
        "complicacion_prob": 0.30,
    },
}

COMORBIDITY_INCLUSION_PROB = 0.25  # probabilidad independiente por item del pool de comorbilidades

# A partir de qué fracción de la trayectoria (0-1) una complicación real se muestra como
# bandera roja garantizada en cada llamada — no solo en la última (§5.3, Plan 05).
COMPLICACION_REAL_ROJO_THRESHOLD = 0.5


def sample_symptom_vector(archetype: str, progress: float, rng: random.Random) -> dict:
    """Muestrea el vector de 6 síntomas para un punto de la trayectoria.

    ``progress`` en [0, 1]: 0 = primera llamada de seguimiento, 1 = última.

    Garantías estructurales por arquetipo (no solo probables — verificadas en tests):
      - ``recuperacion_normal``: en ``progress == 1.0`` el vector siempre queda limpio
        (0 señales amarillas/rojas) — la última llamada nunca puede clasificar distinto
        de verde.
      - ``complicacion_leve_vigilancia``: nunca alcanza un umbral 🔴 individual, en ningún
        punto de la trayectoria (vigilancia por definición, no escalamiento real).
      - ``complicacion_real``: desde ``progress >= COMPLICACION_REAL_ROJO_THRESHOLD`` en
        adelante (las últimas llamadas de la serie, no solo la final) queda garantizada
        al menos una bandera 🔴 — converge a rojo y se mantiene ahí, consistente con
        ``perfiles_pacientes.complicacion_encounter`` (§5.3) y con el criterio clínico de
        que una complicación real identificada normalmente sigue presentándose en los
        controles siguientes hasta resolverse, no en un único punto aislado.
    """
    if archetype not in ARCHETYPES:
        raise ValueError(f"arquetipo desconocido: {archetype!r}")

    if archetype == "recuperacion_normal":
        if progress >= 1.0:
            return {
                "dolor_nrs": rng.randint(0, 2),
                "fiebre_c": round(rng.uniform(36.0, 36.9), 1),
                "movilidad": "normal",
                "herida": "normal",
                "apetito": "normal",
                "sueno": "normal",
            }
        dolor_max = max(2, round(6 - 5 * progress))
        return {
            "dolor_nrs": rng.randint(0, dolor_max),
            "fiebre_c": round(rng.uniform(36.2, 37.4 - 0.3 * progress), 1),
            "movilidad": "normal" if progress >= 0.6 else rng.choice(["limitada_esperada", "limitada_esperada", "normal"]),
            "herida": "normal" if progress >= 0.4 else rng.choice(["normal", "normal", "normal", "eritema_leve"]),
            "apetito": "normal" if progress >= 0.5 else rng.choice(["levemente_disminuido", "normal"]),
            "sueno": "normal" if progress >= 0.5 else rng.choice(["levemente_alterado", "normal"]),
        }

    if archetype == "complicacion_leve_vigilancia":
        # Pico de severidad a mitad de trayectoria (progress ~0.5); nunca cruza umbral rojo.
        peak = 1 - abs(progress - 0.5) * 2  # 0 en los extremos, 1 en progress == 0.5
        return {
            "dolor_nrs": min(7, rng.randint(2, 4 + round(3 * peak))),
            "fiebre_c": round(min(38.2, rng.uniform(36.8, 37.6 + 0.5 * peak)), 1),
            "movilidad": rng.choice(["normal", "limitada_esperada"]),
            "herida": rng.choice(["normal", "eritema_leve"]) if peak > 0.3 else "normal",
            "apetito": rng.choice(["normal", "levemente_disminuido", "muy_disminuido"]) if peak > 0.4 else "normal",
            "sueno": rng.choice(["normal", "levemente_alterado", "muy_alterado"]) if peak > 0.4 else "normal",
        }

    # complicacion_real — escala y se mantiene en una bandera roja garantizada desde
    # COMPLICACION_REAL_ROJO_THRESHOLD en adelante (§5.3, ver docstring de la función).
    if progress >= COMPLICACION_REAL_ROJO_THRESHOLD:
        bandera = rng.choice(["fiebre", "dolor", "herida", "movilidad"])
        return {
            "dolor_nrs": 9 if bandera == "dolor" else rng.randint(5, 7),
            "fiebre_c": round(rng.uniform(38.5, 39.5), 1) if bandera == "fiebre" else round(rng.uniform(37.8, 38.4), 1),
            "movilidad": "incapacitante_nueva" if bandera == "movilidad" else rng.choice(["limitada_esperada", "normal"]),
            "herida": rng.choice(["dehiscencia", "secrecion_purulenta"]) if bandera == "herida" else "eritema_leve",
            "apetito": "muy_disminuido",
            "sueno": "muy_alterado",
        }
    return {
        "dolor_nrs": rng.randint(3, 4 + round(4 * progress)),
        "fiebre_c": round(rng.uniform(37.0, 37.5 + 1.0 * progress), 1),
        "movilidad": rng.choice(["limitada_esperada", "normal"]),
        "herida": rng.choice(["normal", "eritema_leve"]),
        "apetito": rng.choice(["levemente_disminuido", "muy_disminuido"]),
        "sueno": rng.choice(["levemente_alterado", "muy_alterado"]),
    }
