"""Orquestador: uso del primer proveedor, respaldo en cascada, error cuando todos
fallan y plazo total de la petición.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models.schemas import (
    AvailableProduct,
    RecommendationRequest,
    RecommendationResponse,
)
from services.deadline import Deadline
from services.exceptions import InvalidModelOutputError
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


def test_pasa_el_plazo_a_los_proveedores():
    expected = RecommendationResponse(
        user_id=1, recommendations=[], generated_by="primary"
    )
    primary = _provider("primary", return_value=expected)

    LLMOrchestrator([primary]).execute(_make_request())

    assert isinstance(
        primary.get_recommendations.call_args.kwargs["deadline"], Deadline
    )


def test_con_el_plazo_agotado_no_prueba_mas_proveedores():
    primary = _provider("primary", return_value=None)

    orch = LLMOrchestrator([primary], deadline_seconds=0)
    with pytest.raises(AllProvidersFailedError):
        orch.execute(_make_request())
    primary.get_recommendations.assert_not_called()


def test_deadline_cuenta_hacia_atras_con_el_reloj():
    now = [100.0]
    deadline = Deadline(5, clock=lambda: now[0])
    assert deadline.remaining() == 5
    now[0] = 103.5
    assert deadline.remaining() == 1.5
    assert not deadline.expired()
    now[0] = 106
    assert deadline.remaining() == 0
    assert deadline.expired()


def _sample(name: str, labels: dict[str, str]) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_registra_metricas_por_proveedor_y_resultado():
    ok = {"provider": "m-ok", "outcome": "success"}
    bad = {"provider": "m-bad", "outcome": "invalid_output"}
    before_ok = _sample("nomi_ai_llm_calls_total", ok)
    before_bad = _sample("nomi_ai_llm_calls_total", bad)
    expected = RecommendationResponse(user_id=1, recommendations=[], generated_by="x")
    failing = _provider("m-bad", side_effect=InvalidModelOutputError("roto"))
    working = _provider("m-ok", return_value=expected)

    LLMOrchestrator([failing, working]).execute(_make_request())

    assert _sample("nomi_ai_llm_calls_total", ok) == before_ok + 1
    assert _sample("nomi_ai_llm_calls_total", bad) == before_bad + 1
    assert _sample("nomi_ai_llm_latency_seconds_count", {"provider": "m-ok"}) >= 1
