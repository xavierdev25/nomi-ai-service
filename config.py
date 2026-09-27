"""Configuración del servicio, leída solo de variables de entorno (y de `.env` en
local).

La validación crítica corre al importar el módulo: en producción, una API key ausente,
corta o con un valor por defecto inseguro, o `ALLOWED_ORIGINS=*`, abortan el arranque.
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
    """Entero de una variable de entorno. Un valor no numérico aborta el arranque."""
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Variable de entorno {name} no es un entero válido: {raw!r}"
        ) from exc


def _get_bool(name: str, default: bool) -> bool:
    """`1`, `true`, `yes` u `on` (sin distinguir mayúsculas) son verdadero; lo demás,
    falso.
    """
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


ENV: Final[str] = _get_str("ENV", "development").lower()
IS_PRODUCTION: Final[bool] = ENV == "production"
APP_VERSION: Final[str] = _get_str("APP_VERSION", "2.0.0")
WEB_METRICS_ENABLED: Final[bool] = _get_bool("WEB_METRICS_ENABLED", True)

OLLAMA_HOST: Final[str] = _get_str("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: Final[str] = _get_str("OLLAMA_MODEL", "phi3")
# Los timeouts y el plazo total quedan por debajo de los 10 s que espera el backend.
OLLAMA_TIMEOUT_SECONDS: Final[int] = _get_int("OLLAMA_TIMEOUT_SECONDS", 8)

GROQ_API_KEY: Final[str] = _get_str("GROQ_API_KEY", "")
# `llama3-8b-8192` dejó de existir en Groq el 30/08/2025; este es su reemplazo oficial.
GROQ_MODEL: Final[str] = _get_str("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_TIMEOUT_SECONDS: Final[int] = _get_int("GROQ_TIMEOUT_SECONDS", 5)
LLM_DEADLINE_SECONDS: Final[int] = _get_int("LLM_DEADLINE_SECONDS", 9)

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

# Valores de ejemplo que nunca deben llegar a producción como API key.
_INSECURE_DEFAULTS = {
    "",
    "change-me-in-production",
    "changeme",
    "secret",
    "test",
    "dev",
}


def _validate_api_secret_key() -> None:
    """En producción exige una API key de 32 caracteres o más que no sea un valor de
    ejemplo. En desarrollo la permite vacía, con lo que la autenticación queda
    desactivada (con aviso en el log).
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
    """Rechaza el comodín `*` en CORS y avisa si producción incluye orígenes
    `localhost`.
    """
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
    """Vista inmutable de la configuración, para inyectarla o inspeccionarla en tests.
    """

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
    LLM_DEADLINE_SECONDS: int = LLM_DEADLINE_SECONDS
    REDIS_URL: str = REDIS_URL
    REDIS_MAX_CONNECTIONS: int = REDIS_MAX_CONNECTIONS
    AI_CACHE_TTL_SECONDS: int = AI_CACHE_TTL_SECONDS
    ALLOWED_ORIGINS: list[str] = field(default_factory=lambda: list(ALLOWED_ORIGINS))
    RATE_LIMIT_RECOMMENDATIONS: str = RATE_LIMIT_RECOMMENDATIONS
    API_SECRET_KEY: str = API_SECRET_KEY


settings = Settings()


def generate_secret_key() -> str:
    """Genera una API key segura, para usar al desplegar."""
    return secrets.token_urlsafe(48)
