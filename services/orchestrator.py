"""Orquestador de proveedores LLM con respaldo en cascada."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from config import LLM_DEADLINE_SECONDS
from models.schemas import RecommendationRequest, RecommendationResponse
from services.deadline import Deadline
from services.exceptions import AIServiceError, InvalidModelOutputError
from services.llm_provider import LLMProvider
from services.metrics import DEADLINE_EXCEEDED, LLM_CALLS, LLM_LATENCY
from services.tracing import current_trace_id

logger = logging.getLogger(__name__)


class AllProvidersFailedError(AIServiceError):
    """Ningún proveedor pudo responder."""


class LLMOrchestrator:
    """Prueba los proveedores en orden, saltando los no configurados, y devuelve la
    primera respuesta válida.
    """

    def __init__(
        self,
        providers: Sequence[LLMProvider],
        deadline_seconds: float = LLM_DEADLINE_SECONDS,
    ) -> None:
        if not providers:
            raise ValueError("Se requiere al menos un proveedor LLM")
        self._providers = list(providers)
        self._deadline_seconds = deadline_seconds

    @property
    def providers(self) -> list[LLMProvider]:
        return list(self._providers)

    def execute(self, request: RecommendationRequest) -> RecommendationResponse:
        """Devuelve la respuesta del primer proveedor que responda bien.

        Raises:
            AllProvidersFailedError: si todos fallan o ninguno está disponible. El
                detalle queda en los logs.
        """
        last_error: Exception | None = None
        deadline = Deadline(self._deadline_seconds)
        for provider in self._providers:
            if deadline.expired():
                DEADLINE_EXCEEDED.inc()
                logger.warning(
                    "Plazo agotado, no se prueba %s trace_id=%s",
                    provider.name,
                    current_trace_id(),
                )
                break
            if not provider.is_available():
                logger.info(
                    "Proveedor %s no disponible (config), saltando trace_id=%s",
                    provider.name,
                    current_trace_id(),
                )
                continue
            started = time.monotonic()
            try:
                logger.info(
                    "Intentando con proveedor %s trace_id=%s",
                    provider.name,
                    current_trace_id(),
                )
                response = provider.get_recommendations(request, deadline=deadline)
                LLM_CALLS.labels(provider.name, "success").inc()
                return response
            except Exception as exc:
                outcome = (
                    "invalid_output"
                    if isinstance(exc, InvalidModelOutputError)
                    else "error"
                )
                LLM_CALLS.labels(provider.name, outcome).inc()
                logger.warning(
                    "Proveedor %s falló trace_id=%s: %s",
                    provider.name,
                    current_trace_id(),
                    exc,
                    exc_info=True,
                )
                last_error = exc
            finally:
                LLM_LATENCY.labels(provider.name).observe(time.monotonic() - started)

        raise AllProvidersFailedError(
            "Servicio de IA temporalmente no disponible"
        ) from last_error
