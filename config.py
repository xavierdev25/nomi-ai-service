"""Configuración centralizada del servicio.

Toda la configuración proviene exclusivamente de variables de entorno.
La validación crítica se ejecuta al importar el módulo: si una variable
obligatoria en producción falta o es insegura, el proceso aborta.
"""

import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Final

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Variable de entorno {name} no es un entero válido: {raw!r}"
        ) from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


ENV: Final[str] = _get_str("ENV", "development").lower()
IS_PRODUCTION: Final[bool] = ENV == "production"
APP_VERSION: Final[str] = _get_str("APP_VERSION", "2.0.0")
WEB_METRICS_ENABLED: Final[bool] = _get_bool("WEB_METRICS_ENABLED", True)

OLLAMA_HOST: Final[str] = _get_str("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: Final[str] = _get_str("OLLAMA_MODEL", "phi3")
OLLAMA_TIMEOUT_SECONDS: Final[int] = _get_int("OLLAMA_TIMEOUT_SECONDS", 30)

GROQ_API_KEY: Final[str] = _get_str("GROQ_API_KEY", "")
GROQ_MODEL: Final[str] = _get_str("GROQ_MODEL", "llama3-8b-8192")
GROQ_TIMEOUT_SECONDS: Final[int] = _get_int("GROQ_TIMEOUT_SECONDS", 20)

REDIS_URL: Final[str] = _get_str("REDIS_URL", "redis://localhost:6379")
REDIS_MAX_CONNECTIONS: Final[int] = _get_int("REDIS_MAX_CONNECTIONS", 50)
AI_CACHE_TTL_SECONDS: Final[int] = _get_int("AI_CACHE_TTL_SECONDS", 300)

ALLOWED_ORIGINS: Final[list[str]] = [
    o.strip()
    for o in _get_str("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
    if o.strip()
]

RATE_LIMIT_RECOMMENDATIONS: Final[str] = _get_str(
    "RATE_LIMIT_RECOMMENDATIONS", "10/minute"
)

API_SECRET_KEY: Final[str] = _get_str("API_SECRET_KEY", "")

_INSECURE_DEFAULTS = {
    "",
    "change-me-in-production",
    "changeme",
    "secret",
    "test",
    "dev",
}


def _validate_api_secret_key() -> None:
    """Aborta el arranque si la API key no es segura.

    En producción la validación es estricta. En desarrollo se permite
    una clave vacía pero se loguea un warning visible.
    """
    if not API_SECRET_KEY or API_SECRET_KEY.lower() in _INSECURE_DEFAULTS:
        if IS_PRODUCTION:
            raise RuntimeError(
                "API_SECRET_KEY no configurada o usa un valor por defecto inseguro. "
                "Generar con: python -c \"import secrets; "
                'print(secrets.token_urlsafe(48))"'
            )
        logger.warning(
            "API_SECRET_KEY ausente o insegura — autenticación DESHABILITADA "
            "(solo aceptable en ENV=development)."
        )
        return

    if len(API_SECRET_KEY) < 32:
        if IS_PRODUCTION:
            raise RuntimeError(
                f"API_SECRET_KEY demasiado corta ({len(API_SECRET_KEY)} chars). "
                "Mínimo 32 caracteres en producción."
            )
        logger.warning(
            f"API_SECRET_KEY corta ({len(API_SECRET_KEY)} chars). "
            "Recomendado: 32+ caracteres."
        )


def _validate_allowed_origins() -> None:
    if "*" in ALLOWED_ORIGINS:
        raise RuntimeError(
            "ALLOWED_ORIGINS=* no está permitido. Especificar orígenes explícitos."
        )
    if IS_PRODUCTION and any(o.startswith("http://localhost") for o in ALLOWED_ORIGINS):
        logger.warning(
            "ALLOWED_ORIGINS contiene localhost en producción — revisar configuración."
        )


_validate_api_secret_key()
_validate_allowed_origins()


@dataclass(frozen=True)
class Settings:
    ENV: str = ENV
    IS_PRODUCTION: bool = IS_PRODUCTION
    APP_VERSION: str = APP_VERSION
    WEB_METRICS_ENABLED: bool = WEB_METRICS_ENABLED
    OLLAMA_HOST: str = OLLAMA_HOST
    OLLAMA_MODEL: str = OLLAMA_MODEL
    OLLAMA_TIMEOUT_SECONDS: int = OLLAMA_TIMEOUT_SECONDS
    GROQ_API_KEY: str = GROQ_API_KEY
    GROQ_MODEL: str = GROQ_MODEL
    GROQ_TIMEOUT_SECONDS: int = GROQ_TIMEOUT_SECONDS
    REDIS_URL: str = REDIS_URL
    REDIS_MAX_CONNECTIONS: int = REDIS_MAX_CONNECTIONS
    AI_CACHE_TTL_SECONDS: int = AI_CACHE_TTL_SECONDS
    ALLOWED_ORIGINS: list[str] = field(default_factory=lambda: list(ALLOWED_ORIGINS))
    RATE_LIMIT_RECOMMENDATIONS: str = RATE_LIMIT_RECOMMENDATIONS
    API_SECRET_KEY: str = API_SECRET_KEY


settings = Settings()


def generate_secret_key() -> str:
    """Helper para generar una clave segura al deploy."""
    return secrets.token_urlsafe(48)
