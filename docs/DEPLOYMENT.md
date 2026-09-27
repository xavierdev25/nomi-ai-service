# DEPLOYMENT.md — `nomi-ai-service`

## 1. Variables de entorno

Se leen de `.env` (con `python-dotenv`) o del entorno. Los ejemplos están en `.env.example`;
**nunca pongas valores reales en este documento ni en el repositorio.**

| Variable | Por defecto | Uso |
|---|---|---|
| `ENV` | `development` | `production` activa la validación estricta y oculta `/docs` |
| `API_SECRET_KEY` | vacío | API key compartida con el backend. Obligatoria en producción (≥ 32 caracteres, no un valor de ejemplo). Vacía en desarrollo desactiva la autenticación. |
| `ALLOWED_ORIGINS` | `http://localhost:8080` | Orígenes CORS separados por comas. `*` aborta el arranque. |
| `OLLAMA_HOST` | `http://localhost:11434` | URL de Ollama |
| `OLLAMA_MODEL` | `phi3` | Modelo local |
| `OLLAMA_TIMEOUT_SECONDS` | `8` | Timeout de cada llamada a Ollama |
| `GROQ_API_KEY` | vacío | Activa el respaldo en Groq |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Modelo de Groq. `llama3-8b-8192` se retiró el 30/08/2025: si tu `.env` lo tiene, cámbialo |
| `GROQ_TIMEOUT_SECONDS` | `5` | Timeout de Groq |
| `LLM_DEADLINE_SECONDS` | `9` | Plazo total por petición: con él agotado no se reintenta ni se prueba otro proveedor. Debe quedar por debajo del timeout de lectura del backend (10 s) |
| `REDIS_URL` | `redis://localhost:6379` | Caché (opcional) |
| `REDIS_MAX_CONNECTIONS` | `50` | Pool de Redis |
| `AI_CACHE_TTL_SECONDS` | `300` | Vida de la caché |
| `RATE_LIMIT_RECOMMENDATIONS` | `10/minute` | Límite por estudiante (`X-Nomi-User-Id`) o, sin cabecera, por API key e IP. Vive en la memoria de cada worker |
| `WEB_METRICS_ENABLED` | `true` | Expone `/metrics` |
| `APP_VERSION` | `2.0.0` | Versión mostrada en `/health` y OpenAPI |
| `WEB_CONCURRENCY` | `4` | Workers de Gunicorn (solo Docker) |

`AI_SERVICE_PORT` aparece en `.env.example` y en el compose del backend, pero el servicio no la
lee: el puerto se fija en el comando de arranque (`--port 8001` / `--bind 0.0.0.0:8001`).

Generar una API key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. Local

```bash
source venv/bin/activate
uvicorn main:app --reload --port 8001
```

Ollama debe estar corriendo (`ollama serve`) con el modelo descargado (`ollama pull phi3`). Si no
lo está, el servicio arranca igual (solo avisa) y responde `503` si tampoco hay Groq.

## 3. Docker

```bash
docker build -t nomi-ai-service .
docker run --env-file .env -e ENV=production -p 8001:8001 nomi-ai-service
```

El `Dockerfile` usa una imagen `python:3.11-slim` fijada por digest, en dos etapas, ejecuta como
usuario sin privilegios y arranca Gunicorn con `WEB_CONCURRENCY` workers Uvicorn. Su
`HEALTHCHECK` consulta `/health` (vida); para la disponibilidad real usa `/health/ready` en el
orquestador.

Dentro de un contenedor, `OLLAMA_HOST` debe apuntar al host (por ejemplo
`http://host.docker.internal:11434`), no a `localhost`.

> El `docker-compose.yml` de `nomi-backend` construye este servicio (`ai-service`) desde
> `../nomi-ai-service`, con `OLLAMA_HOST` apuntando al Ollama del host. No lo arranques a la vez
> que `uvicorn`: ambos usan el puerto 8001.

## 4. Integración continua

`.github/workflows/ci.yml`: instala `requirements-dev.txt` con Python 3.11 y ejecuta
`pytest --cov=. --cov-fail-under=75` y `ruff check .`. El umbral local (`pyproject.toml`) es más
estricto: 80 %.

## 5. Checklist de producción

La lista completa está en [SECURITY.md](../SECURITY.md#4-checklist-de-deploy-a-producción). Lo
mínimo:

- [ ] `ENV=production` y `API_SECRET_KEY` fuerte, igual que `AI_SERVICE_SECRET_KEY` del backend.
- [ ] `ALLOWED_ORIGINS` con los orígenes reales.
- [ ] Ollama accesible solo por red privada; `GROQ_API_KEY` si se quiere respaldo.
- [ ] Redis con contraseña y en red privada.
- [ ] `/metrics` protegido o desactivado.
