"""Proveedor Ollama: llamada con salida estructurada, forma de la respuesta, parseo,
reintento ante salida inservible y flujo completo.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from models.schemas import AvailableProduct, RecommendationRequest
from services.circuit_breaker import CircuitBreaker
from services.deadline import Deadline
from services.exceptions import InvalidModelOutputError
from services.ollama_service import OllamaProvider
from services.prompt_builder import PromptBuilder

_VALID = '{"recommendations": [{"product_id": 1, "score": 0.9, "reason": "ok"}]}'


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
        result = provider._call_ollama_api("prompt", {"type": "object"})

    assert result == '{"recommendations": []}'
    mock_client.chat.assert_called_once()


def test_call_ollama_api_sends_the_response_schema_as_format():
    mock_client = MagicMock()
    mock_client.chat.return_value = {"message": {"content": _VALID}}
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())
    schema = PromptBuilder.build_response_schema(_make_request())

    with patch("services.ollama_service._client", mock_client):
        provider._call_ollama_api("prompt", schema)

    assert mock_client.chat.call_args.kwargs["format"] == schema


def test_call_ollama_api_rejects_unexpected_shape():
    mock_client = MagicMock()
    mock_client.chat.return_value = {"unexpected": "shape"}
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with (
        patch("services.ollama_service._client", mock_client),
        pytest.raises(InvalidModelOutputError, match="Unexpected Ollama response"),
    ):
        provider._call_ollama_api("prompt", {"type": "object"})


def test_parse_response_returns_recommendation_items():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    result = provider._parse_response(_VALID)

    assert result == [{"product_id": 1, "score": 0.9, "reason": "ok"}]


def test_parse_response_rejects_broken_json():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with pytest.raises(InvalidModelOutputError):
        provider._parse_response('{"recommendations": [{"product_idносилому')


def test_get_recommendations_orchestrates_prompt_call_parse_and_normalize():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with patch.object(provider, "_call_ollama_api", return_value=_VALID):
        result = provider.get_recommendations(_make_request())

    assert result.recommendations[0].product_id == 1
    assert result.generated_by


def test_broken_output_is_retried_once_and_the_retry_is_used():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with patch.object(
        provider, "_call_ollama_api", side_effect=['{"recommendations": [', _VALID]
    ) as call:
        result = provider.get_recommendations(_make_request())

    assert call.call_count == 2
    assert [r.product_id for r in result.recommendations] == [1]


def test_broken_output_twice_gives_up_after_two_attempts():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with (
        patch.object(provider, "_call_ollama_api", return_value="no es json") as call,
        pytest.raises(InvalidModelOutputError),
    ):
        provider.get_recommendations(_make_request())

    assert call.call_count == 2


def test_connection_failures_are_not_retried():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with (
        patch.object(
            provider,
            "_call_ollama_api",
            side_effect=RuntimeError("Ollama no respondió"),
        ) as call,
        pytest.raises(RuntimeError, match="Ollama no respondió"),
    ):
        provider.get_recommendations(_make_request())

    assert call.call_count == 1


def test_no_retry_when_the_deadline_has_no_time_left():
    provider = OllamaProvider(circuit_breaker=CircuitBreaker())

    with (
        patch.object(provider, "_call_ollama_api", return_value="no es json") as call,
        pytest.raises(InvalidModelOutputError),
    ):
        provider.get_recommendations(_make_request(), deadline=Deadline(0))

    assert call.call_count == 1
