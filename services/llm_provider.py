"""Contrato común de los proveedores LLM, para añadir modelos nuevos sin tocar el
orquestador ni el router.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from models.schemas import RecommendationRequest, RecommendationResponse
from services.deadline import Deadline


@runtime_checkable
class LLMProvider(Protocol):
    """Contrato de un proveedor de recomendaciones."""

    name: str

    def is_available(self) -> bool:
        """Si está configurado; el orquestador salta los que no lo están."""
        ...

    def get_recommendations(
        self, request: RecommendationRequest, deadline: Deadline | None = None
    ) -> RecommendationResponse:
        """Genera recomendaciones; lanza una excepción si falla, para que se pruebe el
        siguiente. `deadline` es el plazo total de la petición: el proveedor no debe
        empezar trabajo extra (un reintento) que no pueda terminar a tiempo.
        """
        ...
