"""Caché: claves deterministas que cambian con cada entrada y degradación sin Redis."""

from __future__ import annotations

from unittest.mock import MagicMock

from services.cache_service import CacheService


def _service_with_mock_redis(client_mock: MagicMock) -> CacheService:
    service = CacheService.__new__(CacheService)
    service._url = "redis://test"
    service._ttl = 300
    service._pool = MagicMock()
    service._client = lambda: client_mock  # type: ignore[assignment]
    return service


def test_make_key_es_deterministico():
    a = CacheService.make_key(1, [3, 1, 2], ["VEGANO"], ["arroz"], 5)
    b = CacheService.make_key(1, [1, 2, 3], ["VEGANO"], ["arroz"], 5)
    assert a == b


def test_make_key_diferencia_por_restricciones():
    a = CacheService.make_key(1, [1], ["VEGANO"], [], 5)
    b = CacheService.make_key(1, [1], ["VEGETARIANO"], [], 5)
    assert a != b


def test_make_key_diferencia_por_preferencias():
    a = CacheService.make_key(1, [1], [], ["arroz"], 5)
    b = CacheService.make_key(1, [1], [], ["pollo"], 5)
    assert a != b


def test_make_key_diferencia_por_max_recommendations():
    a = CacheService.make_key(1, [1], [], [], 5)
    b = CacheService.make_key(1, [1], [], [], 10)
    assert a != b


def test_make_key_diferencia_por_user_id():
    a = CacheService.make_key(1, [1], [], [], 5)
    b = CacheService.make_key(2, [1], [], [], 5)
    assert a != b


def test_get_retorna_none_si_cache_no_disponible():
    service = CacheService.__new__(CacheService)
    service._pool = None
    assert service.get("any") is None


def test_set_no_falla_si_cache_no_disponible():
    service = CacheService.__new__(CacheService)
    service._pool = None
    service._ttl = 300
    service.set("any", {"x": 1})


def test_get_hit():
    redis_client = MagicMock()
    redis_client.get.return_value = '{"user_id": 1, "recommendations": []}'
    service = _service_with_mock_redis(redis_client)
    assert service.get("k") == {"user_id": 1, "recommendations": []}


def test_get_miss():
    redis_client = MagicMock()
    redis_client.get.return_value = None
    service = _service_with_mock_redis(redis_client)
    assert service.get("k") is None


def test_get_json_corrupto_devuelve_none():
    redis_client = MagicMock()
    redis_client.get.return_value = "{not json"
    service = _service_with_mock_redis(redis_client)
    assert service.get("k") is None


def test_set_serializa_y_aplica_ttl():
    redis_client = MagicMock()
    service = _service_with_mock_redis(redis_client)
    service.set("k", {"a": 1})
    redis_client.setex.assert_called_once()
    args, _ = redis_client.setex.call_args
    assert args[0] == "k"
    assert args[1] == 300
