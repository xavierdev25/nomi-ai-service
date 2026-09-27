# API.md — `nomi-ai-service`

Fuera de producción, Swagger UI en `http://localhost:8001/docs` y el esquema en `/openapi.json`.

## 1. Autenticación

Cabecera `X-API-Key` con el valor de `API_SECRET_KEY` (en el backend, `AI_SERVICE_SECRET_KEY`).
Sin clave o con una incorrecta: `401 {"error": "API key inválida o ausente"}`; más de 10 fallos
por minuto desde la misma IP: `429`.

Cabecera `X-Nomi-User-Id` (opcional): el id numérico del estudiante que pide. El límite de
recomendaciones (`RATE_LIMIT_RECOMMENDATIONS`, 10/min) se aplica por estudiante si llega y, si
no, por API key e IP. El backend la envía siempre; sin ella, todo el backend compartiría un
único cupo.

Rutas públicas (sin clave): `/health`, `/health/ready`, `/metrics` y, fuera de producción,
`/docs` y `/openapi.json`.

## 2. Endpoints

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `POST` | `/api/ai/recommendations` | Sí | Genera recomendaciones |
| `GET` | `/api/ai/health/ollama` | Sí | Estado de Ollama y del modelo (`503` si no está) |
| `GET` | `/health` | No | Vida: `{"status": "ok", "service": "nomi-ai-service", "version": "…"}` |
| `GET` | `/health/ready` | No | Disponibilidad: `{"ready": true}` si Ollama responde o hay Groq configurado |
| `GET` | `/health/detail` | Sí | Estado de Ollama, Groq, caché y cadena de proveedores |
| `GET` | `/metrics` | No | Métricas Prometheus (si `WEB_METRICS_ENABLED=true`) |

## 3. `POST /api/ai/recommendations`

### Petición

```json
{
  "user_id": 1,
  "restrictions": ["VEGETARIANO"],
  "preferences": ["economico", "almuerzo"],
  "available_products": [
    { "id": 1, "nombre": "Ensalada César", "precio": 8.5, "categoria": "COMIDA" },
    { "id": 3, "nombre": "Jugo de naranja", "precio": 4.0, "categoria": "BEBIDA" }
  ],
  "max_recommendations": 2
}
```

| Campo | Reglas |
|---|---|
| `user_id` | Entero ≥ 1. No se envía al LLM. |
| `restrictions` | Hasta 10, de `VEGETARIANO`, `VEGANO`, `SIN_GLUTEN`, `SIN_LACTOSA`, `NINGUNA`. Otro valor: `422`. |
| `preferences` | Hasta 50. Se descartan las no admitidas (texto de más de 40 caracteres o con caracteres no permitidos) y las repetidas sin distinguir mayúsculas, y se usan las 10 primeras válidas. |
| `available_products` | 1 a 200 productos sin ids repetidos (si no, `422`). `nombre` ≤ 80 y `categoria` ≤ 40 caracteres; `precio` entre 0 y 10 000. Un producto que no cumple se descarta; si no queda ninguno, `422`. |
| `max_recommendations` | 1 a 20 (por defecto 5); si supera el número de productos válidos, se reduce a ese número. |

Los textos (`preferences`, `nombre`, `categoria`) solo admiten letras (con tildes y ñ), dígitos,
espacios y `- _ , . ( ) / & % +`, sin frases típicas de inyección (`ignore`, `system:`,
`<assistant>`…). No se admiten `:`, comillas ni saltos de línea. Lo que no cumple **nunca llega
al prompt**: se descarta, queda en el log con su id y cuenta en
`nomi_ai_inputs_dropped_total`.

**El servicio no filtra por restricciones:** espera candidatos que ya las cumplen (lo hace el
backend con las etiquetas de los productos). Las restricciones se usan solo para las razones.

### Respuesta `200`

```json
{
  "user_id": 1,
  "recommendations": [
    { "product_id": 1, "nombre": "Ensalada César", "precio": 8.5, "categoria": "COMIDA",
      "score": 0.92, "reason": "Vegetariana y económica" }
  ],
  "generated_by": "phi3"
}
```

- `nombre`, `precio` y `categoria` se copian del catálogo recibido, no del modelo.
- Ordenadas por `score` (0–1) descendente; se descartan las de score 0.
- `reason`: texto plano de máximo 80 caracteres, sin etiquetas ni marcado. No viene escapada
  como HTML: un cliente web debe escaparla al pintarla.
- `generated_by`: `OLLAMA_MODEL` (por ejemplo `phi3`) o `groq/<modelo>`.
- La lista puede venir vacía si el modelo no devuelve nada válido.

### Errores

| Código | Cuerpo | Cuándo |
|---|---|---|
| `401` | `{"error": "API key inválida o ausente"}` | Sin clave o incorrecta |
| `422` | `{"detail": [...]}` (formato de FastAPI) | Error de contrato: restricción fuera del enum, ids repetidos, tamaños fuera de rango o ningún producto válido |
| `429` | `{"error": "Demasiadas requests, intenta más tarde"}` | Límite de peticiones o de fallos de autenticación |
| `503` | `{"detail": "Servicio de IA temporalmente no disponible"}` | Ningún proveedor LLM respondió, o se agotó el plazo total (9 s) |
| `500` | `{"detail": {"error_id": "…", "message": "Error interno"}}` | Error inesperado; `error_id` aparece en los logs |

## 4. Cómo lo usa el backend

`GetRecommendationsHandler` (en `nomi-backend`) elige los candidatos (se pueden pedir, tienda
activa, aptos para las restricciones del estudiante, sin "no me gusta", como mucho 40) y, si no
hay ninguno, ni siquiera llama a este servicio. `AiServiceAdapter` llama con timeouts de 3 s
(conexión) y 10 s (lectura), `X-API-Key` y `X-Nomi-User-Id`, y un circuit breaker. Cualquier
error se convierte en una respuesta vacía con `generatedBy = "FALLBACK"` para la app; los `4xx`
no abren el circuito y se registran como error.

## 5. Cambiar el contrato

1. Cambia `models/schemas.py` y añade tests de validación (incluidos los de inyección).
2. Actualiza este documento.
3. Actualiza el cliente del backend (`AiServiceAdapter`, `GetRecommendationsHandler` y sus DTOs) en
   el mismo ciclo: un campo nuevo obligatorio aquí rompe las recomendaciones en producción.
