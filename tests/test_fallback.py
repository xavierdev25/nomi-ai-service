"""Tests del orquestador de proveedores LLM (fallback)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models.schemas import (
    AvailableProduct,
    RecommendationRequest,
    RecommendationResponse,
)
from services.orchestrator import AllProvidersFailedError, LLMOrchestrator


def _make_request():
    return RecommendationRequest(
        user_id=1,
        restrictions=[],
        preferences=[],
        available_products=[
            AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA"),
        ],
        max_recommendations=1,
    )


def _provider(
    name: str, *, available: bool = True, side_effect=None, return_value=None
):
    p = MagicMock()
    p.name = name
    p.is_available.return_value = available
    if side_effect is not None:
        p.get_recommendations.side_effect = side_effect
    elif return_value is not None:
        p.get_recommendations.return_value = return_value
    return p


def test_usa_primer_proveedor_si_funciona():
    expected = RecommendationResponse(
        user_id=1, recommendations=[], generated_by="primary"
    )
    primary = _provider("primary", return_value=expected)
    fallback = _provider("fallback", return_value=expected)

    orch = LLMOrchestrator([primary, fallback])
    result = orch.execute(_make_request())

    assert result is expected
    primary.get_recommendations.assert_called_once()
    fallback.get_recommendations.assert_not_called()


def test_fallback_se_usa_si_primero_falla():
    expected = RecommendationResponse(
        user_id=1, recommendations=[], generated_by="fallback"
    )
    primary = _provider("primary", side_effect=RuntimeError("ollama down"))
    fallback = _provider("fallback", return_value=expected)

    orch = LLMOrchestrator([primary, fallback])
    result = orch.execute(_make_request())

    assert result is expected
    primary.get_recommendations.assert_called_once()
    fallback.get_recommendations.assert_called_once()


def test_salta_proveedor_no_disponible_sin_intentar_call():
    expected = RecommendationResponse(
        user_id=1, recommendations=[], generated_by="fallback"
    )
    primary = _provider("primary", available=False)
    fallback = _provider("fallback", return_value=expected)

    orch = LLMOrchestrator([primary, fallback])
    result = orch.execute(_make_request())

    primary.get_recommendations.assert_not_called()
    assert result is expected


def test_lanza_error_si_todos_fallan():
    primary = _provider("primary", side_effect=RuntimeError("ollama down"))
    fallback = _provider("fallback", side_effect=RuntimeError("groq down"))

    orch = LLMOrchestrator([primary, fallback])
    with pytest.raises(AllProvidersFailedError):
        orch.execute(_make_request())


def test_lanza_error_si_ninguno_disponible():
    p1 = _provider("p1", available=False)
    p2 = _provider("p2", available=False)
    orch = LLMOrchestrator([p1, p2])
    with pytest.raises(AllProvidersFailedError):
        orch.execute(_make_request())


def test_orquestador_requiere_al_menos_un_proveedor():
    with pytest.raises(ValueError):
        LLMOrchestrator([])
