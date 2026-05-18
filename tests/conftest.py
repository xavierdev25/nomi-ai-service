"""Configuración global de tests.

Inyecta variables de entorno seguras antes de que `config.py` se
importe. Esto evita que los tests fallen por validaciones estrictas
de producción y mantiene el aislamiento (sin red real).
"""

from __future__ import annotations

import os

os.environ.setdefault("ENV", "development")
os.environ.setdefault(
    "API_SECRET_KEY", "test-secret-key-for-pytest-with-32-plus-chars-aaaa"
)
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:8080")
os.environ.setdefault("OLLAMA_HOST", "http://localhost:11434")
os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
