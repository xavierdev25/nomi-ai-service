# TESTING.md — `nomi-ai-service`

## 1. Cómo correr los tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt     # pytest, pytest-cov, pytest-asyncio, ruff, mypy
pytest                                  # con cobertura; falla por debajo del 80 %
pytest tests/test_prompt_injection.py   # un archivo
ruff check .
```

No hacen falta Ollama, Groq ni Redis: los proveedores y el cliente de Redis se simulan.

`tests/conftest.py` fija las variables mínimas **antes** de importar la app (API key de prueba,
sin Groq, Redis local), porque `config.py` valida la configuración al importarse.

## 2. Cobertura actual (129 tests, ~93 % de líneas)

| Archivo | Tests | Cubre |
|---|---:|---|
| `test_prompt_injection.py` | 26 | Restricciones fuera del enum rechazadas; preferencias y productos con texto no admitido descartados y ausentes del prompt; recorte a 10 preferencias; contrato (duplicados, vacío, rangos) |
| `test_api_security.py` | 18 | Rutas públicas y protegidas, API key, límite de fallos de autenticación, entrada maliciosa que no llega al modelo, límite por estudiante, métricas expuestas |
| `test_sanitizer.py` | 12 | Saneado hacia el prompt; motivo devuelto en texto plano sin etiquetas ni entidades HTML |
| `test_cache_service.py` | 11 | Claves deterministas, cambios de entrada, degradación sin Redis, JSON corrupto |
| `test_validate_recommendations.py` | 11 | Ids alucinados, duplicados, scores fuera de rango, orden y recorte |
| `test_fallback.py` | 10 | Orquestador: primer proveedor, cascada, error cuando todos fallan, plazo total, métricas por proveedor |
| `test_ollama_service.py` | 10 | Schema como `format`, forma de la respuesta, JSON roto, reintento único, sin reintento ante fallos de conexión ni sin plazo, flujo completo |
| `test_prompt_builder.py` | 8 | Contenido y delimitadores del prompt; JSON Schema (ids del catálogo, `maxItems`, largo del motivo) |
| `test_logging_filter.py` | 7 | Redacción de secretos y hash de `user_id` |
| `test_groq_service.py` | 6 | Disponibilidad según la clave, prompt y modo JSON compartidos, respuesta válida, fallos, JSON malformado |
| `test_circuit_breaker.py` | 4 | Cerrado → abierto → semiabierto |
| `test_json_utils.py` | 3 | Extracción de JSON |
| `test_evaluate.py` | 3 | Cálculos del script de evaluación |

Sin cubrir:
- un test de contrato automático con el backend (el payload real que envía
  `GetRecommendationsHandler`);
- la **calidad** del modelo en CI: los tests usan mocks. Se mide contra el modelo real con
  `scripts/evaluate.py` ([NLP.md](NLP.md) §11).

## 3. Evaluación contra el modelo real

```bash
export API_SECRET_KEY=...
python scripts/evaluate.py --runs 10 --mode pipeline   # flujo real: 0 violaciones esperadas
python scripts/evaluate.py --runs 10 --mode modelo     # lo que el modelo sabe por sí solo
```

Necesita Ollama y el servicio en marcha. Córrelo antes y después de cambiar el prompt, el
schema, los parámetros o el modelo, y compara con [NLP.md](NLP.md) §9.

## 4. Cómo escribir un test

- Archivo `tests/test_<módulo>.py` con docstring de módulo que diga qué cubre; funciones
  `test_<comportamiento>` descriptivas (hay archivos en inglés y en español: sigue el idioma del
  archivo).
- Un comportamiento por test.
- Simula los proveedores y Redis con `monkeypatch` o `unittest.mock`; nunca llames a Ollama o
  Groq reales en los tests.
- Para la API usa `fastapi.testclient.TestClient` con la app real, así se ejercitan middlewares,
  límites y validación.
- Todo patrón de inyección nuevo que se bloquee lleva su caso en `test_prompt_injection.py`.
- Usa solo claves de prueba (como la de `conftest.py`), nunca reales.

## 5. Regla

Todo cambio de lógica lleva test. Antes de terminar, `pytest` y `ruff check .` deben pasar. La CI
exige además un 75 % de cobertura; el umbral local (80 %) es el que manda.
