"""Redacción de secretos en logs y hash de ids de usuario."""

from __future__ import annotations

import logging

from services.logging_filter import SecretFilter, hash_user_id


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_redacta_bearer_token():
    f = SecretFilter()
    record = _make_record("Authorization: Bearer abc123def456ghi789")
    f.filter(record)
    assert "abc123def456" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redacta_x_api_key():
    f = SecretFilter()
    record = _make_record("X-API-Key: super-secret-key-12345")
    f.filter(record)
    assert "super-secret" not in record.getMessage()


def test_redacta_api_key_en_dict_string():
    f = SecretFilter()
    record = _make_record("Request failed with api_key=sk-abc12345xyz")
    f.filter(record)
    assert "sk-abc12345xyz" not in record.getMessage()


def test_no_modifica_mensaje_sin_secretos():
    f = SecretFilter()
    record = _make_record("Recomendaciones generadas para usuario 42")
    f.filter(record)
    assert record.getMessage() == "Recomendaciones generadas para usuario 42"


def test_hash_user_id_es_deterministico():
    assert hash_user_id(42) == hash_user_id(42)


def test_hash_user_id_no_revela_id():
    h = hash_user_id(42)
    assert "42" not in h
    assert len(h) == 12


def test_hash_user_id_distintos_para_distintos_uid():
    assert hash_user_id(1) != hash_user_id(2)
