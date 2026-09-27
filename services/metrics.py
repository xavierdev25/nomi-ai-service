"""Métricas Prometheus del pipeline de recomendaciones (se exponen en `/metrics`).

Las del instrumentador de FastAPI solo miden HTTP: no dicen si falla el modelo, cuánto
tarda cada proveedor o cuántos datos se descartan. Estas sí, y son las que hay que
vigilar al cambiar de prompt o de modelo.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

LLM_CALLS = Counter(
    "nomi_ai_llm_calls_total",
    "Llamadas a un proveedor LLM, por resultado",
    ["provider", "outcome"],  # outcome: success, invalid_output, error
)

LLM_LATENCY = Histogram(
    "nomi_ai_llm_latency_seconds",
    "Duración de la llamada a un proveedor LLM (incluye el reintento)",
    ["provider"],
    buckets=(0.5, 1, 1.5, 2, 3, 5, 8, 13),
)

LLM_RETRIES = Counter(
    "nomi_ai_llm_retries_total",
    "Reintentos por salida inservible del modelo",
    ["provider"],
)

DEADLINE_EXCEEDED = Counter(
    "nomi_ai_deadline_exceeded_total",
    "Peticiones en las que se agotó el plazo antes de probar otro proveedor",
)

INPUTS_DROPPED = Counter(
    "nomi_ai_inputs_dropped_total",
    "Productos o preferencias descartados por texto no admitido",
    ["kind"],  # kind: product, preference
)

CACHE_LOOKUPS = Counter(
    "nomi_ai_cache_lookups_total",
    "Consultas a la caché de recomendaciones",
    ["result"],  # result: hit, miss
)

RECOMMENDATIONS_RETURNED = Histogram(
    "nomi_ai_recommendations_returned",
    "Recomendaciones devueltas por petición",
    buckets=(0, 1, 2, 3, 5, 10, 20),
)
