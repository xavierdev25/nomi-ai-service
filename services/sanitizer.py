"""Sanitización de texto que se inyecta en prompts LLM o se devuelve al cliente.

El schema Pydantic ya rechaza strings con caracteres peligrosos antes de
que lleguen aquí. Estas funciones son una **defensa en profundidad**:
recortan, escapan y neutralizan secuencias que pudieran haber pasado el
primer filtro (por ejemplo, datos de productos cargados desde la base
de datos por administradores).
"""

from __future__ import annotations

import html
import re

# Caracteres y secuencias que deben eliminarse antes de incluir el texto
# dentro del prompt enviado al LLM.
_PROMPT_DANGEROUS_CHARS = re.compile(r"[`\"'<>{}\[\]\\|]")
_PROMPT_NEWLINES = re.compile(r"[\r\n]+")
_PROMPT_INJECTION_KEYWORDS = re.compile(
    r"(?:\b(?:ignore|disregard|forget|override|reveal|jailbreak|prompt|"
    r"new\s+instructions)\b|"
    r"\b(?:system|assistant|user)\s*:)",
    re.IGNORECASE,
)


def scrub_for_prompt(text: str | None, max_len: int = 60) -> str:
    """Limpia texto potencialmente no confiable antes del prompt."""
    if not text:
        return ""
    text = _PROMPT_NEWLINES.sub(" ", text)
    text = _PROMPT_DANGEROUS_CHARS.sub("", text)
    text = _PROMPT_INJECTION_KEYWORDS.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def scrub_list_for_prompt(
    items: list[str] | None, max_items: int = 10, max_len: int = 40
) -> str:
    """Une una lista de strings ya sanitizándolos individualmente."""
    if not items:
        return "ninguna"
    cleaned = [scrub_for_prompt(item, max_len) for item in items[:max_items]]
    cleaned = [c for c in cleaned if c]
    return ", ".join(cleaned) if cleaned else "ninguna"


def safe_reason(text: str | None, max_len: int = 80) -> str:
    """Sanitiza el campo `reason` que viene del LLM antes de retornarlo al cliente.

    Aplica `html.escape` PRIMERO para que cualquier `<script>` se transforme en
    `&lt;script&gt;` sin desaparecer (lo que dejaría texto suelto explotable
    en otros contextos). Luego remueve caracteres remanentes peligrosos.
    """
    if not text:
        return "Recomendado por IA"
    text = _PROMPT_NEWLINES.sub(" ", text)
    text = html.escape(text, quote=True)
    text = re.sub(r"[{}\\`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] or "Recomendado por IA"
