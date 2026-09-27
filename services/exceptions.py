"""Excepciones de la capa de servicios."""

from __future__ import annotations


class AIServiceError(Exception):
    """Fallo esperado del servicio de IA; se responde `503`."""


class InvalidModelOutputError(ValueError):
    """El modelo respondió, pero su salida no se puede usar (JSON roto u otra forma).

    Se distingue de un fallo de conexión o de timeout porque vale la pena
    reintentarla: un LLM pequeño a veces degenera a mitad de la respuesta, pero el
    siguiente intento suele salir bien.
    """
