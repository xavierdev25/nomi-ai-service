"""Limitador compartido por la app y los routers (en su propio módulo para evitar
imports circulares).

El único cliente es el backend: una API key y una IP para todos los estudiantes. Por
eso la clave usa, si llega, el estudiante de la cabecera `X-Nomi-User-Id`; si no,
se limitaba a toda la plataforma a la vez. Sin la cabecera, la clave combina un hash
de la API key y la IP, para que clientes tras el mismo proxy no compartan cupo.

La cabecera solo se tiene en cuenta en peticiones ya autenticadas (el middleware de la
API key corre antes), así que un tercero no puede usarla para esquivar el límite.
"""

from __future__ import annotations

import hashlib
import re

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.logging_filter import hash_user_id

USER_ID_HEADER = "X-Nomi-User-Id"

_USER_ID = re.compile(r"^\d{1,19}$")


def get_api_key_hash(api_key: str) -> str:
    """Primeros 16 caracteres del SHA-256 de la API key: identifica al cliente sin
    guardarla.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _per_user_key(request: Request) -> str:
    """Cliente y estudiante (hasheado: SlowAPI escribe la clave en el log) o, sin
    estudiante, cliente e IP.
    """
    api_key = request.headers.get("X-API-Key", "")
    api_key_part = get_api_key_hash(api_key) if api_key else "anon"
    user_id = request.headers.get(USER_ID_HEADER, "").strip()
    if _USER_ID.match(user_id):
        return f"{api_key_part}:u:{hash_user_id(user_id)}"
    ip_part = get_remote_address(request) or "unknown"
    return f"{api_key_part}:{ip_part}"


limiter = Limiter(key_func=_per_user_key)
