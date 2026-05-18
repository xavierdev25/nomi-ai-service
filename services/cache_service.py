"""Servicio de caché Redis con graceful degradation.

Características:

- Connection pool reutilizable entre requests.
- Reconexión perezosa: si Redis cae al arranque, futuros requests
  intentan reconectar en lugar de quedar permanentemente deshabilitados.
- Las claves incluyen TODOS los inputs que afectan al resultado
  (user_id, productos, restricciones, preferencias, max_recommendations)
  para evitar servir recomendaciones obsoletas o que violen restricciones.
- Falla silenciosamente: cualquier error de Redis se loguea como
  warning, nunca como excepción al caller.
- No almacena PII directa; sólo IDs y la respuesta serializada (que
  contiene IDs de productos, scores y razones).
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

_KEY_PREFIX = "foodv:ai:recs:"


class CacheService:
    """Wrapper minimalista de Redis con manejo de errores."""

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
        """Construye una clave determinística para los inputs relevantes."""
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
        if not self.is_available:
            return
        try:
            self._client().setex(key, self._ttl, json.dumps(data, ensure_ascii=False))
        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("Error escribiendo cache (%s): %s", key, exc)


# Instancia global perezosa
_cache_service: CacheService | None = None


def get_cache_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def reset_cache_service_for_tests() -> None:
    """Solo para tests: fuerza re-inicialización."""
    global _cache_service
    _cache_service = None
