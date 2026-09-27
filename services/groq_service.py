"""Proveedor LLM de respaldo en la nube (Groq).

Usa el mismo prompt, el mismo mensaje de sistema y el mismo parseo que Ollama, con el
modo JSON de Groq (`response_format`), para que el respaldo se comporte igual que el
proveedor principal. No envía el id de usuario ni datos identificables: solo
restricciones, preferencias y el catálogo, ya saneados. La respuesta pasa por la misma
validación que el resto de proveedores.
"""

from __future__ import annotations

import logging

import httpx
from groq import Groq

from config import GROQ_API_KEY, GROQ_MODEL, GROQ_TIMEOUT_SECONDS
from models.schemas import RecommendationRequest, RecommendationResponse
from services.deadline import Deadline
from services.json_utils import parse_recommendation_items
from services.prompt_builder import SYSTEM_PROMPT, PromptBuilder
from services.tracing import current_trace_id
from services.validators import normalize_recommendation_items, sort_and_trim

logger = logging.getLogger(__name__)

_client: Groq | None = None


class ProviderUnavailableError(RuntimeError):
    """Groq no pudo completar la petición."""


def _get_client() -> Groq:
    """Cliente de Groq, creado al primer uso.

    Raises:
        RuntimeError: si no hay `GROQ_API_KEY`.
    """
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY no configurado")
        timeout = httpx.Timeout(GROQ_TIMEOUT_SECONDS)
        _client = Groq(api_key=GROQ_API_KEY, timeout=timeout)
    return _client


class GroqProvider:
    """Proveedor Groq (implementa `LLMProvider`). Solo está disponible con
    `GROQ_API_KEY`.
    """

    name = "groq"

    def is_available(self) -> bool:
        return bool(GROQ_API_KEY)

    def get_recommendations(
        self, request: RecommendationRequest, deadline: Deadline | None = None
    ) -> RecommendationResponse:
        """Recomendaciones de Groq con el prompt compartido. Hace una sola llamada, así
        que el plazo lo controla el orquestador antes de llamarlo.

        Raises:
            ProviderUnavailableError: si Groq no responde.
            InvalidModelOutputError: si la respuesta no es JSON válido.
        """
        if not request.available_products:
            return RecommendationResponse(
                user_id=request.user_id,
                recommendations=[],
                generated_by=f"groq/{GROQ_MODEL}",
            )

        client = _get_client()
        logger.info("Groq recommendation call trace_id=%s", current_trace_id())

        prompt = PromptBuilder.build_batch_prompt(request)
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=800,
            )
        except Exception as exc:
            logger.error(
                "Groq falló trace_id=%s: %s", current_trace_id(), type(exc).__name__
            )
            raise ProviderUnavailableError("Groq no respondió") from exc

        content = (response.choices[0].message.content or "").strip()
        items = parse_recommendation_items(content)
        recommendations = normalize_recommendation_items(items, request)
        recommendations = sort_and_trim(recommendations, request.max_recommendations)

        logger.info(
            "Groq generó %d recomendaciones trace_id=%s",
            len(recommendations),
            current_trace_id(),
        )
        return RecommendationResponse(
            user_id=request.user_id,
            recommendations=recommendations,
            generated_by=f"groq/{GROQ_MODEL}",
        )
