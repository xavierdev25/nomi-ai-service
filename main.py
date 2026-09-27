"""Aplicación FastAPI del servicio de recomendaciones de Nomi.

Configura logs JSON con secretos redactados, autenticación por API key, límite de
peticiones, CORS, métricas Prometheus y trazas OpenTelemetry. Al arrancar crea el
orquestador con la cadena de proveedores LLM (Ollama y, si hay clave, Groq).

Salud: `/health` (vivo, público), `/health/ready` (listo, público) y `/health/detail`
(detalle, requiere API key). La documentación interactiva se desactiva en producción.
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from config import (
    ALLOWED_ORIGINS,
    API_SECRET_KEY,
    GROQ_API_KEY,
    IS_PRODUCTION,
    OLLAMA_MODEL,
    settings,
)
from routers import recommendations
from services.cache_service import get_cache_service
from services.exceptions import AIServiceError
from services.logging_filter import install_secret_filter
from services.ollama_service import check_ollama_health
from services.orchestrator import LLMOrchestrator
from services.provider_factory import LLMProviderFactory
from services.rate_limit import limiter

provider = TracerProvider()
trace.set_tracer_provider(provider)

handler = logging.StreamHandler()
handler.setFormatter(
    jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
)
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
install_secret_filter()
logger = logging.getLogger(__name__)


# Rutas accesibles sin API key: sondas de salud y métricas para Prometheus.
_PUBLIC_PATHS = {"/health", "/health/ready", "/metrics"}

# Límite aparte para fallos de autenticación (10 por minuto e IP): solo se consume con
# una API key inválida, así el tráfico legítimo sigue usando el límite normal de cada
# ruta.
auth_limiter = Limiter(key_func=get_remote_address, key_style="endpoint")


def _auth_failure_limit_scope(request: Request) -> None:
    return None


_auth_failure_limit_scope = auth_limiter.limit("10/minute")(_auth_failure_limit_scope)


def _consume_auth_failure_quota(request: Request) -> None:
    """Descuenta un intento del límite de fallos de autenticación.

    Raises:
        RateLimitExceeded: si se superó el límite.
    """
    auth_limiter._check_request_limit(  # noqa: SLF001 - SlowAPI has no public manual-hit API.
        request,
        _auth_failure_limit_scope,
        in_middleware=False,
    )


class APIKeyAuthMiddleware:
    """Exige la cabecera `X-API-Key` salvo en las rutas públicas, comparándola en tiempo
    constante (`hmac.compare_digest`).

    Es middleware ASGI puro, no `BaseHTTPMiddleware`: este último, combinado con
    SlowAPI, bloqueaba peticiones anidadas.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        if not IS_PRODUCTION and path in {"/docs", "/openapi.json"}:
            await self.app(scope, receive, send)
            return

        # Solo posible en desarrollo: en producción la configuración aborta sin API key.
        if not API_SECRET_KEY:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        provided = headers.get("X-API-Key", "")
        valid = hmac.compare_digest(
            provided.encode("utf-8"),
            API_SECRET_KEY.encode("utf-8"),
        )

        if valid:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        try:
            _consume_auth_failure_quota(request)
        except RateLimitExceeded as exc:
            response = _rate_limit_handler(request, exc)
        else:
            response = JSONResponse(
                status_code=401,
                content={"error": "API key inválida o ausente"},
            )
        await response(scope, receive, send)


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Respuesta `429` sin detalles internos."""
    return JSONResponse(
        status_code=429,
        content={"error": "Demasiadas requests, intenta más tarde"},
    )


def _ai_service_error_handler(request: Request, exc: AIServiceError) -> JSONResponse:
    """`503` cuando ningún proveedor LLM respondió; el backend usa entonces su respuesta
    de degradación.
    """
    logger.warning("AI service unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Servicio de IA temporalmente no disponible"},
    )


def _check_readiness_internal() -> bool:
    """Listo si Ollama responde con el modelo configurado, o si hay Groq como
    alternativa.
    """
    try:
        check_ollama_health()
        return True
    except Exception:
        return bool(GROQ_API_KEY)


def _check_health_detail_internal(app: FastAPI) -> dict:
    """Estado de Ollama, de Groq, de la caché y de la cadena de proveedores."""
    ollama_ok = False
    try:
        check_ollama_health()
        ollama_ok = True
    except Exception:
        pass

    cache = get_cache_service()
    orchestrator = getattr(app.state, "orchestrator", None)
    providers = []
    if orchestrator is not None:
        providers = [provider.name for provider in orchestrator.providers]

    return {
        "ready": ollama_ok or bool(GROQ_API_KEY),
        "ollama": "up" if ollama_ok else "down",
        "groq_configured": bool(GROQ_API_KEY),
        "cache": "up" if cache.is_available else "down",
        "providers": providers,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque y parada: construye el orquestador y comprueba Ollama y Redis.

    Si Ollama no está disponible al arrancar solo se registra un aviso: el servicio
    arranca igual.
    """
    logger.info(
        "Nomi AI Service iniciando (env=%s)", "production" if IS_PRODUCTION else "dev"
    )
    logger.info("CORS permitido para: %s", ALLOWED_ORIGINS)
    logger.info(
        "Autenticación API key: %s", "activada" if API_SECRET_KEY else "DESACTIVADA"
    )

    providers = LLMProviderFactory.build_from_config()
    app.state.orchestrator = LLMOrchestrator(providers)

    try:
        await run_in_threadpool(check_ollama_health)
        logger.info("Ollama UP (modelo=%s)", OLLAMA_MODEL)
    except Exception as exc:
        logger.warning("Ollama no disponible al arranque: %s", exc)

    if GROQ_API_KEY:
        logger.info("Groq fallback configurado")
    else:
        logger.warning("Groq fallback NO configurado — sin redundancia LLM")

    cache = await run_in_threadpool(get_cache_service)
    logger.info("Cache Redis: %s", "UP" if cache.is_available else "DOWN")

    yield
    logger.info("Nomi AI Service detenido")


app = FastAPI(
    title="Nomi AI Service",
    description="Microservicio de recomendaciones con IA para Nomi",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    openapi_tags=[
        {"name": "recommendations", "description": "Motor de recomendaciones con IA"}
    ],
)

app.state.limiter = limiter
app.state.auth_limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_exception_handler(AIServiceError, _ai_service_error_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(APIKeyAuthMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET"],
    allow_headers=["X-API-Key", "Content-Type", "Accept"],
    max_age=600,
)

app.include_router(recommendations.router, prefix="/api/ai", tags=["recommendations"])

if settings.WEB_METRICS_ENABLED:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
def health():
    """Sonda de vida: el proceso responde."""
    return {
        "status": "ok",
        "service": "nomi-ai-service",
        "version": settings.APP_VERSION,
    }


@app.get("/health/ready")
async def readiness():
    """Sonda de disponibilidad: hay al menos un proveedor LLM utilizable."""
    is_ready = await run_in_threadpool(_check_readiness_internal)
    return {"ready": is_ready}


@app.get("/health/detail")
async def health_detail(request: Request):
    """Estado detallado de dependencias; requiere API key."""
    return await run_in_threadpool(_check_health_detail_internal, request.app)
