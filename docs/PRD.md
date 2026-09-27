# PRD — Servicio de recomendaciones con IA

## 1. Propósito

Sugerir a cada estudiante productos del catálogo que encajen con sus restricciones dietéticas y
sus preferencias, con una razón breve, para acortar la búsqueda en la app. Es una función
**accesoria**: si falla, la app sigue funcionando sin recomendaciones.

## 2. Cliente

Solo `nomi-backend`. La app nunca llama a este servicio directamente: el backend arma el contexto
del usuario (preferencias, productos más pedidos, momento del día) y el catálogo, y aplica su
propio fallback (`FALLBACK`) si este servicio no responde.

## 3. Requisitos funcionales

- **RF-01** Recibir `user_id`, restricciones (`VEGETARIANO`, `VEGANO`, `SIN_GLUTEN`, `SIN_LACTOSA`,
  `NINGUNA`), preferencias, entre 1 y 200 productos **candidatos** y el número de
  recomendaciones pedido (1–20, nunca más que productos).
- **RF-02** Descartar, sin rechazar la petición, los productos y preferencias con texto no
  admitido; usar como mucho 10 preferencias. Rechazar con `422` solo los errores de contrato.
- **RF-03** Devolver hasta `max_recommendations` productos **de los candidatos recibidos**,
  ordenados por score (0–1), con una razón corta en texto plano y `generated_by` (modelo que
  respondió). La salida del modelo se restringe con un JSON Schema y se reintenta una vez si no
  sirve y queda plazo.
- **RF-04** Usar Ollama como proveedor principal y Groq como respaldo si está configurado, con
  el mismo prompt.
- **RF-05** Si ningún proveedor responde dentro del plazo total, devolver `503`.
- **RF-06** Cachear la respuesta en Redis por combinación exacta de entradas (TTL 5 minutos por
  defecto).
- **RF-07** Exponer sondas de salud (`/health`, `/health/ready`) y métricas del pipeline
  (`/metrics`).

**El cumplimiento de restricciones no es responsabilidad de este servicio.** El backend solo
envía candidatos aptos según las etiquetas dietéticas de los productos: el modelo no sabe qué
lleva cada plato y, con el catálogo completo, viola las restricciones en la mayoría de sus
recomendaciones ([NLP.md](NLP.md) §9).

## 4. Requisitos no funcionales

- **RNF-01 Seguridad**: API key obligatoria en producción; entradas validadas contra inyección
  de prompt; salida del LLM anclada al catálogo y convertida en texto plano. Ver
  [SECURITY.md](../SECURITY.md).
- **RNF-02 Privacidad**: el `user_id` nunca llega al LLM; en logs solo se registra su hash.
- **RNF-03 Disponibilidad**: timeouts (Ollama 8 s, Groq 5 s) y plazo total de 9 s, por debajo de
  los 10 s del backend; circuit breaker en Ollama; caché que degrada sin error si Redis cae.
- **RNF-04 Límites**: 10 recomendaciones por minuto por estudiante (configurable) y 10 fallos de
  autenticación por minuto e IP.
- **RNF-05 Calidad**: cobertura de tests mínima del 80 %; evaluación contra el modelo real con
  `scripts/evaluate.py` antes de cambiar prompt o modelo.

## 5. Fuera de alcance

- Aprender de las valoraciones del usuario. El backend ya excluye los productos marcados como
  "no me gusta", pero el modelo no usa el historial de valoraciones.
- Guardar datos de usuarios: el servicio no tiene base de datos.
- Hablar directamente con clientes finales.

## 6. Problemas abiertos

- **Calidad del modelo en el dominio** (`IA11`): `phi3` conoce poco la cocina peruana; afecta a
  la calidad del ranking y de las razones, ya no a la seguridad.
- **Ranking poco personalizado** (`IA8`): con temperatura baja, perfiles parecidos reciben casi
  las mismas recomendaciones.
