# ARCHITECTURE.md — `nomi-ai-service`

## 1. Contexto

```text
nomi-backend ──POST /api/ai/recommendations (X-API-Key, X-Nomi-User-Id)──► nomi-ai-service ──► Ollama (local, phi3)
                                                                                │          └──► Groq (nube, respaldo)
                                                                                └──► Redis (caché opcional)
```

El backend ya envía solo **candidatos** que el estudiante puede pedir y comer (filtrados con
las etiquetas dietéticas de los productos). Este servicio los ordena y explica; no decide qué
cumple una restricción.

## 2. Flujo de una petición

```text
Petición
 → CORSMiddleware
 → APIKeyAuthMiddleware        X-API-Key con hmac.compare_digest; fallos limitados a 10/min por IP
 → SlowAPIMiddleware + límite  RATE_LIMIT_RECOMMENDATIONS por estudiante (X-Nomi-User-Id)
                               o, sin cabecera, por hash(API key) + IP
 → Validación Pydantic         contrato estricto (422); productos y preferencias no admitidos
                               se descartan de uno en uno
 → Caché Redis                 clave = sha256(usuario, productos, restricciones, preferencias, cantidad)
     ├─ acierto → respuesta
     └─ fallo  → LLMOrchestrator.execute (en threadpool, plazo total 9 s)
                   ├─ OllamaProvider  format = JSON Schema; 1 reintento si la salida no sirve
                   │                  y queda plazo; circuit breaker: 3 fallos → abierto 60 s
                   └─ GroqProvider    (solo con GROQ_API_KEY): mismo prompt, modo JSON
                 → validators: ids reales, score en [0,1], sin duplicados, razón en texto
                   plano, ordenar y recortar
                 → guardar en caché → respuesta
     └─ todos fallan o plazo agotado → AllProvidersFailedError → 503
```

## 3. Componentes

| Módulo | Responsabilidad |
|---|---|
| `main.py` | App, middlewares, manejadores de error, `lifespan` (crea el orquestador y comprueba Ollama y Redis sin bloquear el arranque), health, métricas y trazas |
| `config.py` | Lee el entorno y **aborta el arranque** con configuración insegura en producción |
| `models/schemas.py` | Contrato de entrada y salida; validación de textos del usuario |
| `routers/recommendations.py` | Endpoint de recomendaciones: caché, orquestador y manejo de errores |
| `services/llm_provider.py` | Protocolo `LLMProvider` (`name`, `is_available`, `get_recommendations`) |
| `services/provider_factory.py` | Cadena de proveedores a partir de la configuración |
| `services/orchestrator.py` | Prueba los proveedores en orden dentro del plazo total y devuelve la primera respuesta válida; registra métricas por proveedor |
| `services/deadline.py` | Plazo total de la petición (reloj monotónico) |
| `services/ollama_service.py` | Llamada a Ollama con salida estructurada (JSON Schema), temperatura 0.2, timeout, un reintento ante salida inservible (si queda plazo) y circuit breaker |
| `services/groq_service.py` | Respaldo en Groq con el mismo prompt, mensaje de sistema y parseo, modo JSON y timeout |
| `services/prompt_builder.py` | Mensaje de sistema y prompt de todos los proveedores (datos entre `<USER_DATA>` y `<PRODUCTS>`) y JSON Schema de la respuesta |
| `services/json_utils.py` | Extracción de JSON y parseo común de la respuesta de cualquier proveedor |
| `services/validators.py` | Convierte la salida del LLM en `ProductRecommendation` fiables |
| `services/sanitizer.py` | Saneado hacia el prompt y texto plano hacia el cliente |
| `services/rate_limit.py` | Límite de peticiones por estudiante |
| `services/metrics.py` | Métricas Prometheus del pipeline |
| `services/cache_service.py` | Redis con degradación silenciosa |
| `services/circuit_breaker.py` | Estados cerrado / abierto / semiabierto, thread-safe |
| `services/logging_filter.py` | Redacta secretos en logs y hashea `user_id` |

## 4. Decisiones

| Decisión | Motivo |
|---|---|
| Una sola llamada al LLM por petición, en lote y en JSON | Un modelo pequeño local (`phi3`) es lento: puntuar producto por producto multiplicaba la latencia. |
| Salida estructurada con JSON Schema (no `format="json"`) | Con el modo JSON genérico, `phi3` rompía las claves en ~8 de cada 10 respuestas y el JSON en ~1 de cada 10. La gramática lo hace imposible y además restringe los ids al catálogo. |
| Reintento solo ante salida inservible | Es un fallo esporádico y barato de reintentar; los timeouts y errores de conexión no se reintentan para no alargar la espera del backend (10 s). |
| Plazo total por petición (9 s) | El backend abandona a los 10 s: seguir después (reintentar, probar Groq) solo gasta un hilo y el modelo. |
| Restricciones filtradas en el backend, no por el LLM | El modelo no sabe qué lleva cada plato: con el catálogo completo, `phi3` viola la restricción en la mayoría de las recomendaciones. |
| Validación tolerante con los datos, estricta con el contrato | Un nombre de producto con apóstrofo dejaba sin recomendaciones a todos; un error de contrato sí es un bug que debe verse. |
| Límite por estudiante | El backend es el único cliente: limitar por API key + IP era limitar a toda la plataforma. |
| Un solo prompt para todos los proveedores | Con prompts distintos, el respaldo se comportaba distinto y nunca se había probado. |
| Ollama primero, Groq de respaldo | Los datos de salud (restricciones) se quedan en la red propia siempre que se pueda. |
| Nombre, precio y categoría salen del catálogo recibido, no del LLM | El modelo puede alucinar; solo se confía en el `product_id` y se valida que exista. |
| Caché por combinación exacta de entradas | Cualquier cambio de perfil o catálogo invalida el resultado sin lógica extra. |
| Redis opcional | La caché mejora latencia pero no es imprescindible. |
| Middleware ASGI puro para la API key | `BaseHTTPMiddleware` combinado con SlowAPI bloqueaba peticiones anidadas. |
| Proveedores detrás de `LLMProvider` | Añadir un modelo no toca el router ni el orquestador. |
| Configuración validada al importar | Un despliegue inseguro falla al arrancar, no en producción con tráfico. |

## 5. Concurrencia

FastAPI es asíncrono, pero los SDK de Ollama, Groq y Redis son síncronos: se ejecutan con
`run_in_threadpool` para no bloquear el bucle de eventos. En Docker, Gunicorn levanta
`WEB_CONCURRENCY` workers (4 por defecto). La caché se comparte en Redis, pero los límites de
SlowAPI se guardan en la memoria de cada proceso: con 4 workers, el límite efectivo es hasta 4
veces el configurado.

El detalle del pipeline (prompt, schema, parámetros, calidad medida) está en [NLP.md](NLP.md).

## 6. Observabilidad

- Logs JSON con `trace_id` y `user_id` hasheado. Los productos y preferencias descartados se
  registran con su id, nunca con el texto.
- `/metrics` (Prometheus) si `WEB_METRICS_ENABLED=true`: métricas HTTP y del pipeline
  (`services/metrics.py`): llamadas por proveedor y resultado, latencia, reintentos, plazos
  agotados, entradas descartadas, caché y recomendaciones devueltas.
- Trazas OpenTelemetry de FastAPI y un span `llm.recommendation` por llamada al modelo (sin
  exportador configurado todavía, `IA13`).
- `scripts/evaluate.py`: evaluación contra el modelo real (ver [NLP.md](NLP.md) §11).
