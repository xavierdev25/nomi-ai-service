"""Redacción de secretos en los logs.

Los SDK y las trazas de errores HTTP pueden incluir cabeceras `Authorization` o
`X-API-Key`; el filtro se instala en el logger raíz y las sustituye por `[REDACTED]`.
"""

from __future__ import annotations

import hashlib
import logging
import re

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.~+/=]{8,}", re.IGNORECASE),
    re.compile(r"(X-API-Key\s*[:=]\s*)[^\s\"'&]{6,}", re.IGNORECASE),
    re.compile(r"(api[_\-]?key\s*[:=]\s*[\"']?)[A-Za-z0-9\-_\.]{8,}", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*[\"']?)[^\"'\s]{8,}", re.IGNORECASE),
)


def _redact(message: str) -> str:
    redacted = message
    for pattern in _PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


class SecretFilter(logging.Filter):
    """Sustituye secretos en el mensaje ya formateado de cada registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        clean = _redact(rendered)
        if clean != rendered:
            record.msg = clean
            record.args = ()
        return True


def install_secret_filter() -> None:
    """Instala el filtro en el logger raíz y en sus handlers."""
    secret_filter = SecretFilter()
    root = logging.getLogger()
    root.addFilter(secret_filter)
    for handler in root.handlers:
        handler.addFilter(secret_filter)


def hash_user_id(user_id: int | str, length: int = 12) -> str:
    """Hash corto del id de usuario, para correlacionar logs sin guardar el id."""
    return hashlib.sha256(f"nomi-uid-{user_id}".encode()).hexdigest()[:length]
