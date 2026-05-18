"""Tests unitarios del proveedor Ollama sin llamadas reales."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from models.schemas import AvailableProduct, RecommendationRequest
from services.circuit_breaker import CircuitBreaker
from services.ollama_service import OllamaProvider


def _make_request() -> RecommendationRequest:
    return RecommendationRequest(
        user_id=1,
        restrictions=[],
        preferences=[],
        available_products=[
            AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA"),
        ],
        max_recommendations=1,
    )


def test_call_ollama_api_returns_raw_content():
    mock_client = MagicMock()
    mock_client.chat.return_value = {
        "message": {"content": '{"recommendations": []}'},
    }
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with patch("services.ollama_service._client", mock_client):
        result = provider._call_ollama_api("prompt")

    assert result == '{"recommendations": []}'
    mock_client.chat.assert_called_once()


def test_call_ollama_api_rejects_unexpected_shape():
    mock_client = MagicMock()
    mock_client.chat.return_value = {"unexpected": "shape"}
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with (
        patch("services.ollama_service._client", mock_client),
        pytest.raises(ValueError, match="Unexpected Ollama response shape"),
    ):
        provider._call_ollama_api("prompt")


def test_parse_response_returns_recommendation_items():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    result = provider._parse_response(
        '{"recommendations": [{"product_id": 1, "score": 0.9, "reason": "ok"}]}'
    )

    assert result == [{"product_id": 1, "score": 0.9, "reason": "ok"}]


def test_get_recommendations_orchestrates_prompt_call_parse_and_normalize():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with patch.object(
        provider,
        "_call_ollama_api",
        return_value=(
            '{"recommendations": [{"product_id": 1, "score": 0.9, "reason": "ok"}]}'
        ),
    ):
        result = provider.get_recommendations(_make_request())

    assert result.recommendations[0].product_id == 1
    assert result.generated_by
