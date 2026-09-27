"""Contenido y delimitadores del prompt de recomendaciones."""

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


def _catalogo(*ids: int) -> list[AvailableProduct]:
    return [
        AvailableProduct(id=i, nombre=f"Producto {i}", precio=5.0, categoria="COMIDA")
        for i in ids
    ]


def test_schema_solo_admite_ids_del_catalogo():
    request = _make_request(available_products=_catalogo(9, 3, 15))
    schema = PromptBuilder.build_response_schema(request)
    item = schema["properties"]["recommendations"]["items"]
    assert item["properties"]["product_id"]["enum"] == [3, 9, 15]
    assert item["required"] == ["product_id", "score", "reason"]


def test_schema_limita_la_cantidad_y_el_largo_del_motivo():
    request = _make_request(
        available_products=_catalogo(1, 2, 3, 4), max_recommendations=2
    )
    schema = PromptBuilder.build_response_schema(request)
    recommendations = schema["properties"]["recommendations"]
    assert recommendations["maxItems"] == 2
    assert recommendations["items"]["properties"]["reason"]["maxLength"] == 80


def test_schema_usa_el_maximo_ya_recortado_al_tamano_del_catalogo():
    request = _make_request(available_products=_catalogo(1, 2), max_recommendations=20)
    schema = PromptBuilder.build_response_schema(request)
    assert schema["properties"]["recommendations"]["maxItems"] == 2
