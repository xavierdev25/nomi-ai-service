"""Prompt construction for recommendation providers."""

from __future__ import annotations

from models.schemas import RecommendationRequest
from services.sanitizer import scrub_for_prompt, scrub_list_for_prompt


class PromptBuilder:
    @staticmethod
    def build_batch_prompt(request: RecommendationRequest) -> str:
        restrictions_text = scrub_list_for_prompt(
            [r.value for r in request.restrictions], max_items=10, max_len=20
        )
        preferences_text = scrub_list_for_prompt(
            request.preferences, max_items=10, max_len=40
        )

        products_lines = []
        for product in request.available_products:
            nombre = scrub_for_prompt(product.nombre, max_len=60)
            categoria = scrub_for_prompt(product.categoria, max_len=30)
            products_lines.append(
                f"- id={product.id} | nombre={nombre} | "
                f"categoria={categoria} | precio=S/.{product.precio:.2f}"
            )
        products_text = "\n".join(products_lines)

        return f"""<USER_DATA>
restricciones_dieteticas: {restrictions_text}
preferencias: {preferences_text}
</USER_DATA>

<PRODUCTS>
{products_text}
</PRODUCTS>

Tarea: evalúa cada producto y devuelve los {request.max_recommendations} mejores.
- Si un producto viola las restricciones dietéticas, descártalo.
- Asigna un score entre 0.0 y 1.0 según las preferencias.
- La razón debe ser de máximo 4 palabras en español, sin comillas ni saltos de línea.

Formato de respuesta (JSON estricto, sin markdown, sin texto antes ni después):
{{"recommendations": [
  {{"product_id": <int>, "score": <float 0.0-1.0>, "reason": "<máximo 4 palabras>"}}
]}}
"""
