"""Modelos Pydantic con validación estricta de input.

Las restricciones están tipadas con `DietaryRestriction` (enum), no con
`str` libre, para impedir prompt injection vía este campo. Las
preferencias y nombres de productos pasan por validadores que rechazan
caracteres usados típicamente en payloads de inyección (saltos de
línea, backticks, marcadores de role).
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from config import settings

# ---------------------------------------------------------------------------
# Restricciones dietéticas (estrictamente tipadas)
# ---------------------------------------------------------------------------


class DietaryRestriction(str, Enum):
    VEGETARIANO = "VEGETARIANO"
    VEGANO = "VEGANO"
    SIN_GLUTEN = "SIN_GLUTEN"
    SIN_LACTOSA = "SIN_LACTOSA"
    NINGUNA = "NINGUNA"


# ---------------------------------------------------------------------------
# Validación de strings de usuario
# ---------------------------------------------------------------------------

# Permite letras (con tildes/ñ), dígitos, espacios y signos de puntuación
# inocuos. Bloquea: \n \r ` $ < > { } [ ] | \ y comillas.
_SAFE_USER_TEXT = re.compile(
    r"^[A-Za-z0-9áéíóúÁÉÍÓÚñÑüÜ\s\-_,.()/&%+]+$",
    re.UNICODE,
)

# Patrones que sugieren intentos de prompt injection
_INJECTION_PATTERNS = re.compile(
    r"(?:^|\s)(ignore|disregard|forget|override|system\s*:|assistant\s*:|"
    r"</?(?:system|user|assistant)>|\\n|\\r)",
    re.IGNORECASE | re.UNICODE,
)


def _validate_user_text(value: str, field: str, max_len: int) -> str:
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


# ---------------------------------------------------------------------------
# Productos disponibles
# ---------------------------------------------------------------------------


class AvailableProduct(BaseModel):
    """Producto del catálogo enviado por el backend Spring."""

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


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class RecommendationRequest(BaseModel):
    user_id: int = Field(ge=1, description="ID interno del usuario")
    restrictions: list[DietaryRestriction] = Field(default_factory=list, max_length=10)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    available_products: list[AvailableProduct] = Field(
        default_factory=list, max_length=200
    )
    max_recommendations: int = Field(default=5, ge=1, le=20)

    @field_validator("preferences", mode="after")
    @classmethod
    def _validate_preferences(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for pref in v:
            cleaned_pref = _validate_user_text(pref, "preference", max_len=40)
            key = cleaned_pref.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(cleaned_pref)
        return cleaned

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
        if self.max_recommendations > len(self.available_products):
            self.max_recommendations = len(self.available_products)
        return self


class ProductRecommendation(BaseModel):
    product_id: int = Field(..., ge=1)
    nombre: str
    precio: float
    categoria: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=80)


class RecommendationResponse(BaseModel):
    user_id: int
    recommendations: list[ProductRecommendation]
    generated_by: str = Field(default_factory=lambda: settings.OLLAMA_MODEL)


# ---------------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------------


class OllamaHealthResponse(BaseModel):
    ollama: str
    model: str
    available: bool
