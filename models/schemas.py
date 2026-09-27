"""Modelos Pydantic de entrada y salida, con validación estricta.

Las restricciones dietéticas son un enum y no texto libre, y los textos de usuario
(nombres de productos, preferencias) pasan por un filtro que rechaza caracteres y
patrones típicos de inyección de prompt.

La petición distingue dos tipos de error. Un error de contrato (restricción fuera del
enum, ids repetidos, tamaños fuera de rango, ningún producto válido) responde `422`. Un
producto o una preferencia con texto no admitido solo se descarta: vienen de datos del
sistema (un nombre como `Helado D'Onofrio`) y rechazar la petición entera dejaba sin
recomendaciones a todos los usuarios. En ambos casos el texto nunca llega al prompt.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from config import settings
from services.metrics import INPUTS_DROPPED

logger = logging.getLogger(__name__)

# Preferencias que se usan como mucho; las válidas que sobran se ignoran.
MAX_PREFERENCES = 10
# Productos que admite una petición (contrato con el backend).
MAX_PRODUCTS = 200


class DietaryRestriction(str, Enum):
    """Restricciones dietéticas admitidas. Cualquier otro valor se rechaza."""

    VEGETARIANO = "VEGETARIANO"
    VEGANO = "VEGANO"
    SIN_GLUTEN = "SIN_GLUTEN"
    SIN_LACTOSA = "SIN_LACTOSA"
    NINGUNA = "NINGUNA"


# Letras (con tildes y ñ), dígitos, espacios y la puntuación `- _ , . ( ) / & % +`. No
# admite saltos de línea, comillas, backticks, `$ < > { } [ ] | \` ni `:`.
_SAFE_USER_TEXT = re.compile(
    r"^[A-Za-z0-9áéíóúÁÉÍÓÚñÑüÜ\s\-_,.()/&%+]+$",
    re.UNICODE,
)

# Frases y marcadores de rol típicos de inyección de prompt.
_INJECTION_PATTERNS = re.compile(
    r"(?:^|\s)(ignore|disregard|forget|override|system\s*:|assistant\s*:|"
    r"</?(?:system|user|assistant)>|\\n|\\r)",
    re.IGNORECASE | re.UNICODE,
)


def _validate_user_text(value: str, field: str, max_len: int) -> str:
    """Recorta y valida un texto de usuario.

    Raises:
        ValueError: si está vacío, supera `max_len`, tiene caracteres no permitidos o
            patrones de inyección.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} no puede estar vacío")
    if len(value) > max_len:
        raise ValueError(f"{field} excede el largo máximo ({max_len} caracteres)")
    if not _SAFE_USER_TEXT.match(value):
        raise ValueError(f"{field} contiene caracteres no permitidos")
    if _INJECTION_PATTERNS.search(value):
        raise ValueError(f"{field} contiene patrones no permitidos")
    return value


class AvailableProduct(BaseModel):
    """Producto candidato enviado por el backend."""

    id: int = Field(ge=1)
    nombre: str = Field(min_length=1, max_length=80)
    precio: float = Field(ge=0, le=10_000)
    categoria: str = Field(min_length=1, max_length=40)

    @field_validator("nombre", mode="after")
    @classmethod
    def _validate_nombre(cls, v: str) -> str:
        return _validate_user_text(v, "nombre", max_len=80)

    @field_validator("categoria", mode="after")
    @classmethod
    def _validate_categoria(cls, v: str) -> str:
        return _validate_user_text(v, "categoria", max_len=40)


class RecommendationRequest(BaseModel):
    """Petición de recomendaciones: perfil del usuario y catálogo candidato (1 a 200
    productos sin ids repetidos).

    Las preferencias no válidas o repetidas (sin distinguir mayúsculas) se descartan y
    se usan las `MAX_PREFERENCES` primeras válidas. Los productos no válidos se
    descartan; si no queda ninguno, la petición se rechaza.
    """

    user_id: int = Field(ge=1, description="ID interno del usuario")
    restrictions: list[DietaryRestriction] = Field(default_factory=list, max_length=10)
    preferences: list[str] = Field(default_factory=list, max_length=50)
    available_products: list[AvailableProduct] = Field(
        default_factory=list, max_length=MAX_PRODUCTS
    )
    max_recommendations: int = Field(default=5, ge=1, le=20)

    @field_validator("preferences", mode="after")
    @classmethod
    def _validate_preferences(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for pref in v:
            try:
                cleaned_pref = _validate_user_text(pref, "preference", max_len=40)
            except ValueError as exc:
                INPUTS_DROPPED.labels("preference").inc()
                logger.warning("Preferencia descartada: %s", exc)
                continue
            key = cleaned_pref.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(cleaned_pref)
        return cleaned[:MAX_PREFERENCES]

    @field_validator("available_products", mode="before")
    @classmethod
    def _drop_invalid_products(cls, v: Any) -> Any:
        """Valida cada producto por separado y descarta los inválidos.

        Se registra el id, no el nombre: podría ser justo el texto malicioso.
        """
        if not isinstance(v, list) or len(v) > MAX_PRODUCTS:
            return v  # el tope de `Field` la rechaza sin validar cada elemento
        kept: list[Any] = []
        for item in v:
            if isinstance(item, AvailableProduct):
                kept.append(item)
                continue
            try:
                kept.append(AvailableProduct.model_validate(item))
            except ValidationError as exc:
                INPUTS_DROPPED.labels("product").inc()
                product_id = item.get("id") if isinstance(item, dict) else None
                reasons = "; ".join(str(error["msg"]) for error in exc.errors())
                logger.warning("Producto id=%r descartado: %s", product_id, reasons)
        if v and not kept:
            raise ValueError("available_products no contiene ningún producto válido")
        return kept

    @field_validator("available_products", mode="after")
    @classmethod
    def _validate_products(cls, v: list[AvailableProduct]) -> list[AvailableProduct]:
        if not v:
            raise ValueError("available_products no puede estar vacío")
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("available_products contiene IDs duplicados")
        return v

    @model_validator(mode="after")
    def cap_max_recommendations(self) -> RecommendationRequest:
        """No se pueden pedir más recomendaciones que productos candidatos."""
        if self.max_recommendations > len(self.available_products):
            self.max_recommendations = len(self.available_products)
        return self


class ProductRecommendation(BaseModel):
    """Producto recomendado. Nombre, precio y categoría salen del catálogo, no del
    modelo.
    """

    product_id: int = Field(..., ge=1)
    nombre: str
    precio: float
    categoria: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=80)


class RecommendationResponse(BaseModel):
    """Lista de recomendaciones y proveedor que la generó."""

    user_id: int
    recommendations: list[ProductRecommendation]
    generated_by: str = Field(default_factory=lambda: settings.OLLAMA_MODEL)


class OllamaHealthResponse(BaseModel):
    """Estado de Ollama y del modelo configurado."""

    ollama: str
    model: str
    available: bool
