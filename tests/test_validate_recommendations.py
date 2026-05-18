"""Tests de validación de recomendaciones y esquemas relacionados."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import (
    AvailableProduct,
    ProductRecommendation,
    RecommendationRequest,
)
from services.validators import normalize_recommendation_items, sort_and_trim


def _make_request(products):
    return RecommendationRequest(
        user_id=1,
        restrictions=[],
        preferences=[],
        available_products=products,
        max_recommendations=5,
    )


def test_valida_producto_existente():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 1, "score": 0.9, "reason": "bueno"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert len(result) == 1
    assert result[0].product_id == 1
    assert result[0].nombre == "Arroz"


def test_descarta_producto_inexistente():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 99, "score": 0.9, "reason": "alucinado"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert len(result) == 0


def test_corrige_score_fuera_de_rango():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 1, "score": 1.5, "reason": "ok"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert result[0].score == 1.0


def test_corrige_score_negativo():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 1, "score": -0.5, "reason": "ok"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert result[0].score == 0.0


def test_score_no_numerico_se_normaliza():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 1, "score": "no_es_numero", "reason": "ok"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert 0.0 <= result[0].score <= 1.0


def test_trunca_reason_larga():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [{"product_id": 1, "score": 0.8, "reason": "x" * 200}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert len(result[0].reason) <= 80


def test_descarta_items_no_dict():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = ["no_es_dict", None, 42, {"product_id": 1, "score": 0.5, "reason": "ok"}]
    result = normalize_recommendation_items(items, _make_request(products))
    assert len(result) == 1


def test_descarta_duplicados():
    products = [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    items = [
        {"product_id": 1, "score": 0.9, "reason": "uno"},
        {"product_id": 1, "score": 0.5, "reason": "duplicado"},
    ]
    result = normalize_recommendation_items(items, _make_request(products))
    assert len(result) == 1


def test_sort_and_trim():
    products = [
        AvailableProduct(id=i, nombre=f"P{i}", precio=1.0, categoria="C")
        for i in range(1, 6)
    ]
    items = [
        {"product_id": 1, "score": 0.3, "reason": "a"},
        {"product_id": 2, "score": 0.9, "reason": "b"},
        {"product_id": 3, "score": 0.0, "reason": "c"},
        {"product_id": 4, "score": 0.7, "reason": "d"},
        {"product_id": 5, "score": 0.5, "reason": "e"},
    ]
    request = _make_request(products)
    result = sort_and_trim(
        normalize_recommendation_items(items, request), max_recommendations=2
    )
    assert [r.product_id for r in result] == [2, 4]


def test_cap_max_recommendations_a_productos_disponibles():
    request = _make_request(
        [AvailableProduct(id=1, nombre="Arroz", precio=5.0, categoria="COMIDA")]
    )

    assert request.max_recommendations == 1


def test_product_recommendation_rechaza_product_id_menor_a_uno():
    with pytest.raises(ValidationError):
        ProductRecommendation(
            product_id=0,
            nombre="Arroz",
            precio=5.0,
            categoria="COMIDA",
            score=0.9,
            reason="ok",
        )
