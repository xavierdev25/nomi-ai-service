"""Caché de recomendaciones en Redis que degrada en silencio.

Cualquier error de Redis se registra como aviso y la petición sigue sin caché. Solo
guarda ids, puntuaciones y motivos; el id de usuario solo forma parte del hash de la
clave.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

import redis
from redis.connection import ConnectionPool

from config import AI_CACHE_TTL_SECONDS, REDIS_MAX_CONNECTIONS, REDIS_URL

logger = logging.getLogger(__name__)

_KEY_PREFIX = "nomi:ai:recs:"


class CacheService:
    """Envoltorio de Redis con pool de conexiones y timeouts cortos (2 s)."""

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        ttl_seconds: int = AI_CACHE_TTL_SECONDS,
        max_connections: int = REDIS_MAX_CONNECTIONS,
    ) -> None:
        self._url = redis_url
        self._ttl = ttl_seconds
        self._pool: ConnectionPool | None = None
        try:
            self._pool = ConnectionPool.from_url(
                redis_url,
                decode_responses=True,
                max_connections=max_connections,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            self._client().ping()
            logger.info("Redis cache conectado correctamente")
        except Exception as exc:
            self._pool = None
            logger.warning("Redis no disponible al arranque: %s", exc)

    @property
    def is_available(self) -> bool:
        """`False` si Redis no respondió al arrancar."""
        return self._pool is not None

    def _client(self) -> redis.Redis:
        if self._pool is None:
            raise RuntimeError("Redis no inicializado")
        return redis.Redis(connection_pool=self._pool)

    @staticmethod
    def make_key(
        user_id: int,
        product_ids: Sequence[int],
        restrictions: Sequence[str],
        preferences: Sequence[str],
        max_recommendations: int,
    ) -> str:
        """Clave determinista: hash SHA-256 de las entradas normalizadas (ordenadas,
        preferencias en minúsculas).
        """
        parts = [
            str(user_id),
            ",".join(str(i) for i in sorted(product_ids)),
            ",".join(sorted(r for r in restrictions)),
            ",".join(sorted(p.lower() for p in preferences)),
            str(max_recommendations),
        ]
        raw = "|".join(parts)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{_KEY_PREFIX}{digest}"

    def get(self, key: str) -> dict[str, Any] | None:
        """Respuesta cacheada, o `None` si no existe, Redis no está o está corrupta."""
        if not self.is_available:
            return None
        try:
            value = self._client().get(key)
            if value:
                return json.loads(value)
        except (redis.RedisError, json.JSONDecodeError) as exc:
            logger.warning("Error leyendo cache (%s): %s", key, exc)
        return None

    def set(self, key: str, data: dict[str, Any]) -> None:
        """Guarda la respuesta con el TTL configurado; los errores solo se registran."""
        if not self.is_available:
            return
        try:
            self._client().setex(key, self._ttl, json.dumps(data, ensure_ascii=False))
        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("Error escribiendo cache (%s): %s", key, exc)


_cache_service: CacheService | None = None


def get_cache_service() -> CacheService:
    """Instancia única, creada la primera vez que se pide."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def reset_cache_service_for_tests() -> None:
    """Solo para tests: fuerza a crear una instancia nueva."""
    global _cache_service
    _cache_service = None
