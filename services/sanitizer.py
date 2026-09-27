"""Saneado de textos que van al prompt o vuelven al cliente.

Los esquemas Pydantic ya rechazan entradas peligrosas; esto es defensa en profundidad
para lo que pase ese filtro, como nombres de productos cargados por administradores.
"""

from __future__ import annotations

import re

_PROMPT_DANGEROUS_CHARS = re.compile(r"[`\"'<>{}\[\]\\|]")
_PROMPT_NEWLINES = re.compile(r"[\r\n]+")
_HTML_TAG = re.compile(r"<[^>]*>")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_PROMPT_INJECTION_KEYWORDS = re.compile(
    r"(?:\b(?:ignore|disregard|forget|override|reveal|jailbreak|prompt|"
    r"new\s+instructions)\b|"
    r"\b(?:system|assistant|user)\s*:)",
    re.IGNORECASE,
)


def scrub_for_prompt(text: str | None, max_len: int = 60) -> str:
    """Quita saltos de línea, comillas, backticks, llaves y corchetes, redacta palabras
    de inyección y recorta a `max_len`.
    """
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
    """Lista saneada unida por comas, o `"ninguna"` si queda vacía."""
    if not items:
        return "ninguna"
    cleaned = [scrub_for_prompt(item, max_len) for item in items[:max_items]]
    cleaned = [c for c in cleaned if c]
    return ", ".join(cleaned) if cleaned else "ninguna"


def safe_reason(text: str | None, max_len: int = 80) -> str:
    """Convierte el motivo generado por el modelo en texto plano seguro de mostrar.

    Quita etiquetas, `< >`, llaves, backticks, barras invertidas y caracteres de
    control, pero no escapa HTML: la API es JSON y la app muestra el texto tal cual,
    así que `&amp;` aparecía literal en pantalla. Escapar es tarea de quien lo pinte
    como HTML.
    """
    if not text:
        return "Recomendado por IA"
    text = _PROMPT_NEWLINES.sub(" ", text)
    text = _HTML_TAG.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    text = re.sub(r"[<>{}\\`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len].strip() or "Recomendado por IA"
