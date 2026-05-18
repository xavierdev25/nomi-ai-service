"""Orquestador de proveedores LLM con fallback en cascada.

Itera por la lista de proveedores en orden. Si uno falla, intenta el
siguiente. Si todos fallan, lanza `RuntimeError` con mensaje genérico
(el detalle queda solo en logs).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from models.schemas import RecommendationRequest, RecommendationResponse
from services.exceptions import AIServiceError
from services.llm_provider import LLMProvider
from services.tracing import current_trace_id

logger = logging.getLogger(__name__)


class AllProvidersFailedError(AIServiceError):
    """Indica que todos los proveedores LLM fallaron."""


class LLMOrchestrator:
    def __init__(self, providers: Sequence[LLMProvider]) -> None:
        if not providers:
            raise ValueError("Se requiere al menos un proveedor LLM")
        self._providers = list(providers)

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)

    def execute(self, request: RecommendationRequest) -> RecommendationResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            if not provider.is_available():
                logger.info(
                    "Proveedor %s no disponible (config), saltando trace_id=%s",
                    provider.name,
                    current_trace_id(),
                )
                continue
            try:
                logger.info(
                    "Intentando con proveedor %s trace_id=%s",
                    provider.name,
                    current_trace_id(),
                )
                return provider.get_recommendations(request)
            except Exception as exc:
                logger.warning(
                    "Proveedor %s falló trace_id=%s: %s",
                    provider.name,
                    current_trace_id(),
                    exc,
                    exc_info=True,
                )
                last_error = exc

        raise AllProvidersFailedError(
            "Servicio de IA temporalmente no disponible"
        ) from last_error
