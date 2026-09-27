"""Composición de la cadena de proveedores según la configuración."""

from __future__ import annotations

from config import settings
from services.circuit_breaker import CircuitBreaker
from services.groq_service import GroqProvider
from services.llm_provider import LLMProvider
from services.ollama_service import OllamaProvider


class LLMProviderFactory:
    @staticmethod
    def build_from_config() -> list[LLMProvider]:
        """Ollama siempre; Groq como respaldo solo si hay `GROQ_API_KEY`."""
        providers: list[LLMProvider] = [
            OllamaProvider(circuit_breaker=CircuitBreaker()),
        ]
        if settings.GROQ_API_KEY:
            providers.append(GroqProvider())
        return providers
