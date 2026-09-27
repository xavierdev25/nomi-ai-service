# AGENTS.md — `nomi-ai-service`

Instrucciones para agentes de IA (y personas) que trabajen en este repositorio.

## Qué es

Microservicio FastAPI que recomienda productos con un LLM (Ollama `phi3`, con Groq de respaldo).
Su único cliente es `nomi-backend`, que lo llama con `X-API-Key`. No tiene base de datos: solo
una caché opcional en Redis.

## Antes de cambiar algo, lee

| Si vas a… | Lee primero |
|---|---|
| Cambiar el comportamiento de las recomendaciones | [docs/PRD.md](docs/PRD.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Tocar el prompt, el schema, los parámetros o el modelo | [docs/NLP.md](docs/NLP.md) — y evalúa contra el modelo real antes y después (§11) |
| Cambiar la petición o la respuesta | [docs/API.md](docs/API.md) — el backend (`AiServiceAdapter`, `GetRecommendationsHandler`) depende del contrato |
| Tocar prompts, validación, autenticación o logs | [SECURITY.md](SECURITY.md) |
| Cambiar configuración o despliegue | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Escribir cualquier código | [docs/CODE_STYLE.md](docs/CODE_STYLE.md) |
| Añadir o cambiar tests | [docs/TESTING.md](docs/TESTING.md) |

Si la documentación contradice el código, señálalo antes de hacer un cambio grande.

## Comandos

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8001
pytest
ruff check .
```

## Reglas

- **Los datos del usuario son datos, no instrucciones.** Todo texto que llegue al prompt pasa por
  la validación de `models/schemas.py` y el saneado de `services/sanitizer.py`, y va entre
  delimitadores.
- **No confíes en la salida del LLM.** Todo pasa por `services/validators.py`: ids que existan en
  la petición, scores en [0, 1], sin duplicados, razones saneadas y truncadas.
- **Mantén la salida estructurada.** Ollama recibe el JSON Schema de
  `PromptBuilder.build_response_schema`; volver a `format="json"` rompe las claves en la mayoría
  de las respuestas de `phi3`. Si cambias `ProductRecommendation`, cambia el schema a la vez.
- **Las restricciones las garantiza el backend, no el modelo.** El backend solo envía
  candidatos aptos según las etiquetas de los productos; no traslades esa responsabilidad al
  prompt ni supongas que el modelo sabe qué lleva un plato.
- **Tolerante con los datos, estricto con el contrato.** Un producto o una preferencia con texto
  no admitido se descarta (nunca llega al prompt); un error de contrato responde `422`.
- **Evalúa antes y después** de tocar prompt, schema, parámetros o modelo:
  `python scripts/evaluate.py --mode pipeline` y `--mode modelo` ([docs/NLP.md](docs/NLP.md) §11).
- **Nunca envíes `user_id` ni datos identificables al LLM**, y no registres preferencias,
  restricciones ni API keys en logs (usa `hash_user_id`).
- **Un proveedor nuevo implementa `LLMProvider`** y se registra en `provider_factory.py`; el
  router y el orquestador no cambian.
- **Llamadas bloqueantes (LLM, Redis) en `run_in_threadpool`**, con timeout.
- **Cambios de contrato**: actualiza `docs/API.md` y coordina con `nomi-backend`.
- **Todo cambio de lógica lleva test.** `pytest` y `ruff check .` deben pasar.
- **Documenta en español** y explica el porqué (ver CODE_STYLE.md).

## Nunca

- Escribir API keys reales en código, tests, `.env.example` o documentación.
- Permitir `ALLOWED_ORIGINS=*` o desactivar la validación de arranque de `config.py`.
- Relajar el esquema de entrada sin revisar el riesgo de inyección de prompt.
- Hacer commit o push sin que te lo pidan.
