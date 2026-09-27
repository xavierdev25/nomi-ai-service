"""Plazo total de una petición de recomendaciones.

El backend deja de esperar a los 10 s (timeout de lectura). Todo trabajo posterior se
desperdicia y ocupa un hilo del threadpool, así que el orquestador no prueba otro
proveedor, ni Ollama reintenta, cuando ya no queda tiempo para terminar.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class Deadline:
    """Instante límite medido con un reloj monotónico (inyectable en tests)."""

    def __init__(
        self, seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._clock = clock
        self._expires_at = clock() + seconds

    def remaining(self) -> float:
        """Segundos que quedan; nunca negativo."""
        return max(0.0, self._expires_at - self._clock())

    def expired(self) -> bool:
        return self.remaining() <= 0.0
