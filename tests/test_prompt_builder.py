"""Tests del prompt builder (Ollama batch)."""

from __future__ import annotations

from models.schemas import (
    AvailableProduct,
    DietaryRestriction,
    RecommendationRequest,
)
from services.prompt_builder import PromptBuilder


def _make_request(**overrides):
    base = dict(
        user_id=1,
        restrictions=[DietaryRestriction.VEGANO],
        preferences=["arroz"],
        available_products=[
            AvailableProduct(
                id=1, nombre="Lomo Saltado", precio=12.0, categoria="COMIDA"
            ),
        ],
        max_recommendations=3,
    )
    base.update(overrides)
    return RecommendationRequest(**base)


def test_batch_prompt_incluye_restricciones():
    prompt = PromptBuilder.build_batch_prompt(_make_request())
    assert "VEGANO" in prompt


def test_batch_prompt_incluye_nombres_de_productos():
    prompt = PromptBuilder.build_batch_prompt(_make_request())
    assert "Lomo Saltado" in prompt


def test_batch_prompt_solicita_formato_json():
    prompt = PromptBuilder.build_batch_prompt(_make_request())
    assert "JSON estricto" in prompt
    assert '"recommendations"' in prompt


def test_batch_prompt_tiene_delimitadores_seguros():
    prompt = PromptBuilder.build_batch_prompt(_make_request())
    assert "<USER_DATA>" in prompt
    assert "<PRODUCTS>" in prompt


def test_batch_prompt_no_filtra_user_id_dentro_de_user_data_directamente():
    prompt = PromptBuilder.build_batch_prompt(_make_request(user_id=999))
    assert "999" not in prompt
