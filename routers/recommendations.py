"""Endpoints de recomendaciones (`/api/ai`).

Los errores inesperados nunca exponen el mensaje interno: se devuelve un `error_id` que
aparece en los logs para correlacionarlos.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from opentelemetry import trace
from pydantic import ValidationError

from config import RATE_LIMIT_RECOMMENDATIONS
from models.schemas import (
    OllamaHealthResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from services.cache_service import CacheService, get_cache_service
from services.exceptions import AIServiceError
from services.logging_filter import hash_user_id
from services.metrics import CACHE_LOOKUPS, RECOMMENDATIONS_RETURNED
from services.ollama_service import check_ollama_health
from services.orchestrator import LLMOrchestrator
from services.rate_limit import limiter
from services.tracing import current_trace_id

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
router = APIRouter()


def get_orchestrator(request: Request) -> LLMOrchestrator:
    """Orquestador creado al arrancar; `503` si todavía no existe."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Service unavailable")
    return orchestrator


@router.post("/recommendations", response_model=RecommendationResponse)
@limiter.limit(RATE_LIMIT_RECOMMENDATIONS)
async def recommend(
    request: Request,
    body: RecommendationRequest,
    orchestrator: LLMOrchestrator = Depends(get_orchestrator),
    cache: CacheService = Depends(get_cache_service),
) -> RecommendationResponse:
    """Genera recomendaciones, con caché en Redis por combinación exacta de entradas.

    La clave de caché incluye usuario, productos, restricciones, preferencias y
    cantidad: un cambio en cualquiera invalida el resultado. Las llamadas bloqueantes
    (Redis, LLM) corren en el threadpool para no bloquear el bucle de eventos.
    """
    err_id = uuid4().hex[:12]
    uid_hash = hash_user_id(body.user_id)

    try:
        logger.info(
            "Recomendaciones request trace_id=%s uid=%s products=%d max=%d",
            current_trace_id(),
            uid_hash,
            len(body.available_products),
            body.max_recommendations,
        )

        cache_key = cache.make_key(
            user_id=body.user_id,
            product_ids=[p.id for p in body.available_products],
            restrictions=[r.value for r in body.restrictions],
            preferences=body.preferences,
            max_recommendations=body.max_recommendations,
        )

        cached = await run_in_threadpool(cache.get, cache_key)
        if cached:
            try:
                hit = RecommendationResponse(**cached)
                CACHE_LOOKUPS.labels("hit").inc()
                RECOMMENDATIONS_RETURNED.observe(len(hit.recommendations))
                logger.info("Cache HIT uid=%s", uid_hash)
                return hit
            except ValidationError:
                logger.warning("Cache corrupto para key=%s, regenerando", cache_key)
        CACHE_LOOKUPS.labels("miss").inc()

        with tracer.start_as_current_span("llm.recommendation"):
            result = await run_in_threadpool(orchestrator.execute, body)

        await run_in_threadpool(cache.set, cache_key, result.model_dump())
        RECOMMENDATIONS_RETURNED.observe(len(result.recommendations))

        logger.info(
            "Recomendaciones generadas trace_id=%s uid=%s count=%d source=%s",
            current_trace_id(),
            uid_hash,
            len(result.recommendations),
            result.generated_by,
        )
        return result

    except AIServiceError:
        logger.error("[%s] Servicio IA no disponible uid=%s", err_id, uid_hash)
        raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[%s] Error inesperado uid=%s: %s", err_id, uid_hash, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail={"error_id": err_id, "message": "Error interno"},
        )


@router.get("/health/ollama", response_model=OllamaHealthResponse)
async def ollama_health() -> OllamaHealthResponse:
    """Estado de Ollama; requiere API key."""
    try:
        result = await run_in_threadpool(check_ollama_health)
    except RuntimeError as exc:
        logger.warning("Health Ollama DOWN: %s", exc)
        raise HTTPException(status_code=503, detail="Ollama no disponible")
    return OllamaHealthResponse(ollama="ok", model=result["model"], available=True)
