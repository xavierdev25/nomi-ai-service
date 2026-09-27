"""Extracción de JSON de las respuestas de un LLM."""

from __future__ import annotations

import json
import re
from typing import Any

from services.exceptions import InvalidModelOutputError


def extract_json(text: str) -> Any:
    """Parsea el texto como JSON y, si falla, busca el primer array u objeto dentro de
    él (por ejemplo, rodeado de markdown).

    Raises:
        ValueError: si no hay JSON válido.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from: {text[:200]}")


def parse_recommendation_items(raw: str) -> list[Any]:
    """Ítems crudos de la respuesta de cualquier proveedor, venga como
    `{"recommendations": [...]}` o como array. Otra forma válida da una lista vacía.

    Raises:
        InvalidModelOutputError: si el texto no contiene JSON válido.
    """
    try:
        payload = extract_json(raw)
    except ValueError as exc:
        raise InvalidModelOutputError("Respuesta inválida del modelo") from exc
    items = payload.get("recommendations", []) if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else []
