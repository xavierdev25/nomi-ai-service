"""Proveedor LLM principal: Ollama con un modelo local (por defecto `phi3`).

Una llamada por intento con salida estructurada: el JSON Schema de la respuesta se pasa
en `format` y Ollama restringe la generación a él. Con `format="json"`, `phi3` rompía
los nombres de las claves en la mayoría de las respuestas y a veces el JSON entero. Si
aun así la salida no sirve, se reintenta una vez; los fallos de conexión y los timeouts
no se reintentan (los cubre el circuit breaker).

El prompt no incluye el id de usuario, así que ningún dato personal sale del host. El
cliente se crea al primer uso, para que los tests puedan sustituirlo.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import ollama
from ollama import Client as OllamaClient

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS
from models.schemas import RecommendationRequest, RecommendationResponse
from services.circuit_breaker import CircuitBreaker
from services.deadline import Deadline
from services.exceptions import InvalidModelOutputError
from services.json_utils import parse_recommendation_items
from services.metrics import LLM_RETRIES
from services.prompt_builder import SYSTEM_PROMPT, PromptBuilder
from services.tracing import current_trace_id
from services.validators import normalize_recommendation_items, sort_and_trim

logger = logging.getLogger(__name__)

_client: OllamaClient | None = None
_circuit_breaker = CircuitBreaker(threshold=3, reset_after=60.0)

# Un reintento basta: la salida inválida es esporádica, y cada intento de `phi3` tarda
# ~1,5 s frente a los 10 s de lectura que concede el backend.
_MAX_ATTEMPTS = 2


def _get_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SECONDS)
    return _client


def check_ollama_health() -> dict[str, Any]:
    """Comprueba que Ollama responde y tiene el modelo configurado.

    Raises:
        RuntimeError: si no responde o no tiene el modelo.
    """
    try:
        models_response = _get_client().list()
    except (ConnectionError, httpx.HTTPError, ollama.RequestError) as exc:
        logger.error("No se pudo conectar a Ollama: %s", exc)
        raise RuntimeError("Servicio Ollama no disponible") from exc

    available = [getattr(m, "model", "") for m in models_response.models]
    if not any(OLLAMA_MODEL in (name or "") for name in available):
        raise RuntimeError(f"Modelo '{OLLAMA_MODEL}' no encontrado en Ollama")

    return {"status": "ok", "model": OLLAMA_MODEL}


class OllamaProvider:
    """Proveedor Ollama (implementa `LLMProvider`)."""

    name = "ollama"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None) -> None:
        self._circuit_breaker = circuit_breaker or _circuit_breaker

    def is_available(self) -> bool:
        return bool(OLLAMA_HOST)

    def _call_ollama_api(self, prompt: str, response_schema: dict[str, Any]) -> str:
        """Texto crudo de la respuesta, generado bajo `response_schema`.

        Raises:
            RuntimeError: si Ollama no responde, expira o el circuito está abierto.
            InvalidModelOutputError: si la respuesta no trae contenido.
        """
        client = _get_client()
        try:
            response = self._circuit_breaker.call(
                client.chat,
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                format=response_schema,
                options={
                    "temperature": 0.2,
                    "num_predict": 800,
                },
            )
        except (
            httpx.TimeoutException,
            ollama.RequestError,
            ollama.ResponseError,
        ) as exc:
            logger.error("Ollama falló trace_id=%s: %s", current_trace_id(), exc)
            raise RuntimeError("Ollama no respondió") from exc

        # `ollama` 0.6 devuelve un `ChatResponse` (modelo Pydantic), nunca un `dict`;
        # admite `.get()` y `[]` por compatibilidad.
        content = response.get("message", {}).get("content")
        if not isinstance(content, str):
            raise InvalidModelOutputError(
                f"Unexpected Ollama response shape: {response}"
            )
        return content.strip()

    def _parse_response(self, raw: str) -> list[Any]:
        """Lista de ítems del modelo, venga como array o como
        `{"recommendations": [...]}`.

        Raises:
            InvalidModelOutputError: si el texto no contiene JSON válido.
        """
        try:
            return parse_recommendation_items(raw)
        except InvalidModelOutputError:
            logger.error(
                "Respuesta de Ollama no es JSON válido trace_id=%s (%d caracteres)",
                current_trace_id(),
                len(raw),
            )
            raise

    def _generate_items(
        self, request: RecommendationRequest, deadline: Deadline | None
    ) -> list[Any]:
        """Ítems crudos del modelo, con un reintento si la salida no sirve y queda
        tiempo: al menos lo que tardó el intento fallido.

        Raises:
            InvalidModelOutputError: si los intentos hechos devuelven salida inservible.
            RuntimeError: si Ollama no responde (sin reintento).
        """
        prompt = PromptBuilder.build_batch_prompt(request)
        schema = PromptBuilder.build_response_schema(request)
        last_error = InvalidModelOutputError("Sin intentos")
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            logger.info(
                "Ollama recommendation call trace_id=%s attempt=%d",
                current_trace_id(),
                attempt,
            )
            started = time.monotonic()
            try:
                return self._parse_response(self._call_ollama_api(prompt, schema))
            except InvalidModelOutputError as exc:
                last_error = exc
                took = time.monotonic() - started
                if attempt == _MAX_ATTEMPTS:
                    break
                if deadline is not None and deadline.remaining() < took:
                    logger.warning(
                        "Salida de Ollama inservible y sin tiempo para reintentar "
                        "trace_id=%s",
                        current_trace_id(),
                    )
                    break
                LLM_RETRIES.labels(self.name).inc()
                logger.warning(
                    "Salida de Ollama inservible, reintentando trace_id=%s",
                    current_trace_id(),
                )
        raise last_error

    def get_recommendations(
        self, request: RecommendationRequest, deadline: Deadline | None = None
    ) -> RecommendationResponse:
        if not request.available_products:
            return RecommendationResponse(
                user_id=request.user_id, recommendations=[], generated_by=OLLAMA_MODEL
            )

        items = self._generate_items(request, deadline)
        recommendations = normalize_recommendation_items(items, request)
        recommendations = sort_and_trim(recommendations, request.max_recommendations)

        return RecommendationResponse(
            user_id=request.user_id,
            recommendations=recommendations,
            generated_by=OLLAMA_MODEL,
        )
