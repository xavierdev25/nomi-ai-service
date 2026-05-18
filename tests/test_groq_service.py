"""Tests del proveedor Groq sin llamadas reales a la API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from models.schemas import AvailableProduct, RecommendationRequest
from services.groq_service import (
    GroqProvider,
    ProviderUnavailableError,
)


@pytest.fixture(autouse=True)
def _reset_groq_client():
    with patch("services.groq_service._client", None):
        yield


def _make_request() -> RecommendationRequest:
    return RecommendationRequest(
        user_id=7,
        restrictions=[],
        preferences=["pollo"],
        available_products=[
            AvailableProduct(
                id=1, nombre="Pollo saltado", precio=12.5, categoria="COMIDA"
            ),
            AvailableProduct(
                id=2, nombre="Ensalada fresca", precio=8.0, categoria="COMIDA"
            ),
        ],
        max_recommendations=2,
    )


def _groq_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_is_available_returns_true_when_groq_api_key_is_set():
    with patch("services.groq_service.GROQ_API_KEY", "test-groq-key"):
        assert GroqProvider().is_available() is True


def test_is_available_returns_false_when_groq_api_key_is_missing():
    with patch("services.groq_service.GROQ_API_KEY", ""):
        assert GroqProvider().is_available() is False


def test_get_recommendations_returns_valid_list_when_groq_returns_json():
    content = """
    [
      {"product_id": 1, "score": 0.92, "reason": "Buen match"},
      {"product_id": 2, "score": 0.71, "reason": "Ligera"}
    ]
    """
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _groq_response(content)

    with (
        patch("services.groq_service.GROQ_API_KEY", "test-groq-key"),
        patch("services.groq_service.Groq", return_value=mock_client),
    ):
        result = GroqProvider().get_recommendations(_make_request())

    assert result.user_id == 7
    assert result.generated_by.startswith("groq/")
    assert [item.product_id for item in result.recommendations] == [1, 2]
    assert result.recommendations[0].nombre == "Pollo saltado"
    mock_client.chat.completions.create.assert_called_once()


def test_get_recommendations_raises_provider_unavailable_when_groq_raises():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("network down")

    with (
        patch("services.groq_service.GROQ_API_KEY", "test-groq-key"),
        patch("services.groq_service.Groq", return_value=mock_client),
        pytest.raises(ProviderUnavailableError, match="Groq no respondió"),
    ):
        GroqProvider().get_recommendations(_make_request())


def test_get_recommendations_handles_malformed_json_gracefully():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _groq_response(
        '[{"product_id": 1, "score": 0.9,}]'
    )

    with (
        patch("services.groq_service.GROQ_API_KEY", "test-groq-key"),
        patch("services.groq_service.Groq", return_value=mock_client),
        pytest.raises(RuntimeError, match="Respuesta inválida del modelo"),
    ):
        GroqProvider().get_recommendations(_make_request())
