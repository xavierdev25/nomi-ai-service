"""Tests del circuit breaker usado por proveedores sync."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.circuit_breaker import CircuitBreaker, CircuitState


def test_circuit_starts_closed():
    breaker = CircuitBreaker()

    assert breaker.state == CircuitState.CLOSED


def test_circuit_opens_after_threshold_failures():
    breaker = CircuitBreaker(threshold=2, reset_after=60.0)

    for _ in range(2):
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

    assert breaker.state == CircuitState.OPEN


def test_circuit_rejects_calls_when_open():
    breaker = CircuitBreaker(threshold=1, reset_after=60.0)

    with pytest.raises(ValueError):
        breaker.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

    with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
        breaker.call(lambda: "ok")


def test_circuit_transitions_to_half_open_after_reset_after_seconds():
    breaker = CircuitBreaker(threshold=1, reset_after=10.0)

    with patch("services.circuit_breaker.time.monotonic", side_effect=[100.0, 105.0]):
        with pytest.raises(ValueError):
            breaker.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        with pytest.raises(RuntimeError):
            breaker.call(lambda: "ok")

    assert breaker.state == CircuitState.OPEN

    def succeed_from_half_open():
        assert breaker.state == CircuitState.HALF_OPEN
        return "ok"

    with patch("services.circuit_breaker.time.monotonic", return_value=111.0):
        assert breaker.call(succeed_from_half_open) == "ok"

    assert breaker.state == CircuitState.CLOSED
