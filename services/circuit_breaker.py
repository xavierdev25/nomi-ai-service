"""Thread-safe circuit breaker for synchronous provider calls."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


T = TypeVar("T")


class CircuitBreaker:
    def __init__(self, threshold: int = 3, reset_after: float = 60.0):
        self.threshold = threshold
        self.reset_after = reset_after
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        with self._lock:
            if self._state == CircuitState.OPEN:
                opened_at = self._opened_at or 0.0
                if time.monotonic() - opened_at >= self.reset_after:
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise RuntimeError("Circuit breaker is OPEN - Ollama unavailable")
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self._failures = 0
                self._state = CircuitState.CLOSED
                self._opened_at = None
            return result
        except Exception:
            with self._lock:
                self._failures += 1
                if self._failures >= self.threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
            raise
