# Changelog — `nomi-ai-service`

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Las versiones
siguen [SemVer](https://semver.org/lang/es/). Los cambios nuevos van en **No publicado**.

## [No publicado]

### Añadido
- Salida estructurada en Ollama: el JSON Schema de la respuesta (ids de los candidatos como
  `enum`, `maxItems`, razón ≤ 80 caracteres) se pasa en `format` en lugar de `"json"`.
- Un reintento cuando la salida del modelo es inservible (`InvalidModelOutputError`), solo si
  queda plazo; los fallos de conexión y los timeouts no se reintentan.
- Plazo total por petición (`LLM_DEADLINE_SECONDS`, 9 s): con él agotado no se reintenta ni se
  prueba otro proveedor.
- Límite de peticiones por estudiante con la cabecera `X-Nomi-User-Id`.
- Métricas Prometheus del pipeline (`services/metrics.py`): llamadas por proveedor y resultado,
  latencia, reintentos, plazos agotados, entradas descartadas, caché y recomendaciones devueltas.
- `scripts/evaluate.py` y `scripts/eval_dataset.json`: evaluación contra el modelo real en modo
  `pipeline` y `modelo`.
- `docs/NLP.md`: el pipeline del LLM, calidad medida y cómo evaluar.
- Tests: schema, reintento, plazo, límite por estudiante, validación tolerante, Groq, métricas y
  evaluación (129 en total).
- Docstrings y comentarios en español en todo el código y los tests.
- Documentación del repositorio: README actualizado, AGENTS y `docs/` (PRD, arquitectura, API,
  despliegue, estilo y tests).

### Cambiado
- **La marca es Nomi:** servicio `nomi-ai-service`, cabecera `X-Nomi-User-Id`, métricas
  `nomi_ai_*` y prefijo de caché `nomi:ai:recs:` (la caché anterior se ignora). La sal de
  `hash_user_id` cambió, así que los hashes de usuario de los logs nuevos no coinciden con los
  anteriores.
- Validación tolerante con los datos: un producto o una preferencia con texto no admitido se
  descarta en lugar de rechazar la petición con `422`; se usan como mucho 10 preferencias (se
  admiten hasta 50). Los errores de contrato siguen respondiendo `422`.
- Groq usa el mismo mensaje de sistema, prompt y parseo que Ollama, con modo JSON
  (`response_format`), temperatura 0.2 y 800 tokens.
- `reason` se devuelve como texto plano (sin etiquetas ni marcado) en lugar de escapada como HTML.
- Timeouts por defecto: Ollama 8 s (antes 30), Groq 5 s (antes 20).
- Modelo de Groq por defecto: `llama-3.1-8b-instant` (el anterior, `llama3-8b-8192`, se retiró
  el 30/08/2025).
- El log de salida inválida de Ollama ya no incluye la respuesta cruda del modelo.
- `SECURITY.md`: amenazas y mitigaciones actualizadas; el hash de `user_id`, el `HEALTHCHECK`,
  `/metrics` y el contenido de la caché se describen como están implementados.

### Corregido
- `phi3` rompía los nombres de las claves en ~8 de cada 10 respuestas (se perdían
  recomendaciones) y devolvía JSON inválido en ~1 de cada 10 (`503`).
- Un nombre de producto con apóstrofo, comillas o `:` dejaba sin recomendaciones a todos los
  usuarios.
- El límite de 10 recomendaciones por minuto era global para toda la plataforma.
- La app iOS mostraba `&amp;` o `&quot;` literales en las razones.
- El servicio podía seguir trabajando hasta 50 s después de que el backend abandonara.

## [2.0.0] — 2026-05-18

### Añadido
- Circuit breaker en el proveedor Ollama.
- Cadena de proveedores tras el contrato `LLMProvider` (`provider_factory`, `orchestrator`).
- Métricas Prometheus (`/metrics`), trazas OpenTelemetry y logs JSON.
- `/health/detail` con el estado de dependencias.

### Seguridad
- Validación de arranque en producción (API key fuerte, sin `ALLOWED_ORIGINS=*`).
- Límite de fallos de autenticación por IP y rate limit por API key + IP.
- Validación anti-inyección en el esquema y saneado de la salida del modelo.

## [1.0.0] — 2026-04-27

### Añadido
- Recomendaciones con Ollama (`phi3`) evaluando el catálogo en una sola llamada JSON.
- Respaldo en Groq, caché Redis, autenticación por API key y tests.
