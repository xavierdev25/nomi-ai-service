"""Validación post-LLM compartida entre proveedores.

Cualquier proveedor (Ollama, Groq, futuros) que devuelva una lista de
items con la forma `{product_id, score, reason}` debe pasar por
`normalize_recommendation_items` para garantizar:

1. Que el `product_id` corresponda a un producto realmente disponible
   (anti-alucinación).
2. Que los datos del producto (nombre, precio, categoría) se tomen del
   catálogo real, no del LLM.
3. Que el `score` esté clamped a [0.0, 1.0].
4. Que el `reason` esté sanitizado para retorno seguro al cliente.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from models.schemas import ProductRecommendation, RecommendationRequest
from services.sanitizer import safe_reason

logger = logging.getLogger(__name__)


def normalize_recommendation_items(
    items: Iterable[dict],
    request: RecommendationRequest,
) -> list[ProductRecommendation]:
    """Convierte items crudos del LLM en `ProductRecommendation` validados."""
    valid_products = {p.id: p for p in request.available_products}
    out: list[ProductRecommendation] = []
    seen_ids: set[int] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        pid = item.get("product_id")
        if not isinstance(pid, int):
            try:
                pid = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                pid = None

        if pid is None or pid not in valid_products:
            logger.warning(
                "Descartando recomendación con product_id=%r (alucinado o duplicado)",
                pid,
            )
            continue

        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        real = valid_products[pid]

        try:
            score_raw = float(item.get("score", 0.5))
        except (TypeError, ValueError):
            score_raw = 0.5
        score = max(0.0, min(1.0, score_raw))

        out.append(
            ProductRecommendation(
                product_id=pid,
                nombre=real.nombre,
                precio=real.precio,
                categoria=real.categoria,
                score=score,
                reason=safe_reason(item.get("reason")),
            )
        )

    return out


def sort_and_trim(
    recommendations: list[ProductRecommendation],
    max_recommendations: int,
) -> list[ProductRecommendation]:
    """Filtra score>0, ordena por score desc y aplica el max."""
    filtered = [r for r in recommendations if r.score > 0.0]
    filtered.sort(key=lambda r: r.score, reverse=True)
    return filtered[:max_recommendations]
