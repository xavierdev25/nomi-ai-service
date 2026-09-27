# CODE_STYLE.md — `nomi-ai-service`

## 1. Herramientas

- **ruff** (`line-length = 88`; reglas `E`, `F`, `I`, `N`, `UP`): `ruff check .` debe pasar.
- **mypy** en modo `strict` configurado en `pyproject.toml`.
- Python 3.11: tipos modernos (`list[str]`, `X | None`) y `from __future__ import annotations`
  donde haga falta.

## 2. Idioma

- Nombres técnicos en inglés (`get_recommendations`, `CacheService`).
- Campos del contrato con el backend tal como los define la API (`available_products`, `nombre`,
  `precio`, `categoria`).
- Docstrings, comentarios, mensajes de error y documentación en español.

## 3. Organización

- `routers/`: solo HTTP (dependencias, códigos de estado). La lógica va en `services/`.
- `services/`: un módulo por responsabilidad. Los proveedores implementan `LLMProvider`.
- `models/schemas.py`: todo el contrato y su validación.
- `config.py`: única puerta a las variables de entorno; el resto del código importa de ahí.

## 4. Reglas de código

- Todo texto que venga del cliente se valida en el esquema y se sanea antes de entrar al prompt.
- Toda salida del LLM pasa por `validators.py` antes de devolverse.
- Llamadas bloqueantes (SDK de LLM, Redis) con timeout y, desde un endpoint, en
  `run_in_threadpool`.
- Errores de proveedor: lanza excepciones propias de `services/exceptions.py`; el router no
  expone detalles internos (usa un `error_id` para cruzar con los logs).
- Logs con `logging` y parámetros `%s`; nunca API keys, preferencias ni `user_id` en claro (usa
  `hash_user_id`).
- Sin estado global mutable salvo los clientes perezosos ya existentes (Ollama, Groq, Redis).

## 5. Docstrings y comentarios

Explican **por qué**, no qué. Estilo Google:

```python
def extract_json(text: str) -> Any:
    """Parsea el texto como JSON y, si falla, busca el primer array u objeto dentro de
    él (por ejemplo, rodeado de markdown).

    Raises:
        ValueError: si no hay JSON válido.
    """
```

- Docstring de módulo en cada archivo de `services/`, `routers/` y `models/`, con su
  responsabilidad.
- En funciones, solo si el comportamiento no es evidente: efectos, errores (`Raises:`), decisiones.
- Comentarios `#` para casos límite o requisitos externos (por ejemplo, la forma de la respuesta
  del SDK de Ollama).
- Sin código comentado ni comentarios de historial.
- Respeta el límite de 88 columnas también en docstrings: reenvuelve párrafos completos, no dejes
  líneas de una sola palabra.

## 6. Tests

Ver [TESTING.md](TESTING.md).
