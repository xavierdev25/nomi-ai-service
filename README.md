# Nomi — Servicio de IA (`nomi-ai-service`)

Microservicio de **recomendaciones de comida** de Nomi. Recibe del backend el perfil del
estudiante (restricciones y preferencias) y el catálogo disponible, pide a un LLM que puntúe los
productos y devuelve los mejores con una razón corta. Usa **Ollama** (modelo local `phi3`, con
salida estructurada por JSON Schema) y, si falla, **Groq** en la nube.

> El backend solo envía **candidatos** que el estudiante puede pedir y comer (según las
> etiquetas dietéticas de los productos); este servicio los ordena y explica. El modelo por sí
> solo no sabe qué lleva cada plato ([docs/NLP.md](docs/NLP.md) §9).

Solo lo llama `nomi-backend`, autenticado con una API key compartida. Si este servicio no
responde, el backend devuelve una lista vacía: las recomendaciones nunca rompen la app.

## Stack

| | |
|---|---|
| Lenguaje | Python 3.11 |
| Framework | FastAPI + Pydantic 2 (validación estricta) |
| Servidor | Uvicorn (desarrollo), Gunicorn con workers Uvicorn (Docker) |
| LLM | Ollama (`phi3`), Groq como respaldo |
| Caché | Redis (opcional: sin Redis funciona sin caché) |
| Límites | SlowAPI |
| Observabilidad | Logs JSON, Prometheus (`/metrics`), OpenTelemetry |
| Calidad | pytest (cobertura mínima 80 %), ruff, mypy |

## Requisitos

- Python 3.11 o superior.
- [Ollama](https://ollama.com) con el modelo: `ollama pull phi3`.
- Opcional: Redis para caché y una API key de Groq para el respaldo.

## Empezar

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt     # incluye requirements.txt, pytest y ruff
cp .env.example .env                    # y rellenar los valores

ollama serve                            # en otra terminal
uvicorn main:app --reload --port 8001
```

- Con `ENV=development` y `API_SECRET_KEY` vacía, la autenticación queda **desactivada** (se
  avisa en el log). Para probar con el backend, usa el mismo valor que su
  `AI_SERVICE_SECRET_KEY`.
- Swagger UI en `http://localhost:8001/docs` (solo fuera de producción).

## Tests y calidad

```bash
pytest          # 129 tests, falla si la cobertura baja del 80 %
ruff check .
python scripts/evaluate.py --mode pipeline   # contra el modelo real (necesita API_SECRET_KEY)
```

No necesitan Ollama, Groq ni Redis: se simulan. Detalle en [docs/TESTING.md](docs/TESTING.md).

## Estructura

```text
main.py              App FastAPI: middlewares (API key, CORS, rate limit), health, métricas, trazas
config.py            Variables de entorno y validación de arranque
models/schemas.py    Contrato de entrada y salida (Pydantic), validación anti-inyección
routers/             POST /api/ai/recommendations y GET /api/ai/health/ollama
services/
├── orchestrator.py        Cadena de proveedores con respaldo y plazo total
├── deadline.py            Plazo total de la petición
├── metrics.py             Métricas Prometheus del pipeline
├── provider_factory.py    Composición de la cadena según la configuración
├── llm_provider.py        Contrato común de los proveedores
├── ollama_service.py      Proveedor principal: salida estructurada, reintento y circuit breaker
├── groq_service.py        Proveedor de respaldo (mismo prompt, modo JSON)
├── prompt_builder.py      Mensaje de sistema, prompt con delimitadores y JSON Schema
├── validators.py          Validación y normalización de la salida del LLM
├── sanitizer.py           Saneado de textos hacia el prompt y hacia el cliente
├── json_utils.py          Extracción de JSON de la respuesta del modelo
├── cache_service.py       Caché Redis que degrada en silencio
├── circuit_breaker.py     Circuit breaker thread-safe
├── rate_limit.py          Límite de peticiones por estudiante
├── logging_filter.py      Redacción de secretos y hash de user_id en logs
├── tracing.py             Utilidades de OpenTelemetry
└── exceptions.py          Excepciones del servicio
scripts/             Evaluación contra el modelo real (evaluate.py + eval_dataset.json)
tests/               Tests (pytest)
```

## Documentación

| Documento | Contenido |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Qué debe hacer el servicio y qué no |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flujo de una recomendación, proveedores y decisiones |
| [docs/NLP.md](docs/NLP.md) | Pipeline del LLM: contexto, prompt, salida estructurada, validación, calidad medida y cómo evaluar |
| [docs/API.md](docs/API.md) | Endpoints, contrato y errores |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Variables de entorno, Docker y CI |
| [SECURITY.md](SECURITY.md) | Amenazas, flujo de datos, configuración y checklist de producción |
| [docs/CODE_STYLE.md](docs/CODE_STYLE.md) | Convenciones de código y de documentación |
| [docs/TESTING.md](docs/TESTING.md) | Cómo se prueba y qué está cubierto |
| [CHANGELOG.md](CHANGELOG.md) | Cambios relevantes |
| [AGENTS.md](AGENTS.md) | Instrucciones para agentes de IA |
| [ANALYSIS-ai-service.md](ANALYSIS-ai-service.md) | Análisis de ingeniería anterior (en inglés; puede no reflejar el estado actual) |

La documentación general del sistema vive en el sitio Starlight de `nomi-docs`.

## Proyectos relacionados

- `nomi-backend` — API principal (Spring Boot); único cliente de este servicio.
- `nomi-ios` — app iOS del estudiante.
- `nomi-docs` — documentación general.
