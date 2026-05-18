"""Limiter compartido por la app y los routers.

Vive en un módulo aparte para evitar imports circulares entre
`main.py` y `routers/recommendations.py`.

La key combina la API key (16 primeros caracteres) e IP remota para que
clientes detrás del mismo reverse proxy no compartan bucket. Si ambos
faltan se usa "anon".
"""

from __future__ import annotations

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_api_key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _per_user_key(request: Request) -> str:
    api_key = request.headers.get("X-API-Key", "")
    api_key_part = get_api_key_hash(api_key) if api_key else "anon"
    ip_part = get_remote_address(request) or "unknown"
    return f"{api_key_part}:{ip_part}"


limiter = Limiter(key_func=_per_user_key)
