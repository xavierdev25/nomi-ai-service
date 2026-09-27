"""Entorno de pruebas: variables mínimas antes de importar la app (API key de prueba,
sin Groq y Redis local).
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
