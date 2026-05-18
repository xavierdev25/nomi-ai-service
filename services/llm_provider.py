"""Protocolo común para proveedores LLM.

Permite agregar nuevos modelos (OpenAI, Anthropic, Gemini, etc.) sin
modificar el orquestador ni el router.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from models.schemas import RecommendationRequest, RecommendationResponse


@runtime_checkable
class LLMProvider(Protocol):
    """Contrato que debe cumplir cualquier proveedor de recomendaciones."""

    name: str

    def is_available(self) -> bool:
        """Indica si el proveedor está configurado y operativo."""
        ...

    def get_recommendations(
        self, request: RecommendationRequest
    ) -> RecommendationResponse:
        """Genera recomendaciones. Lanza excepción si el proveedor falla."""
        ...
