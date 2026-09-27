"""Evaluación del servicio de recomendaciones contra un modelo real.

Envía cada escenario de `eval_dataset.json` varias veces al servicio en marcha, con un
`user_id` distinto por corrida para no acertar en la caché, y resume por escenario:
respuestas correctas, recomendaciones devueltas frente a pedidas, violaciones de
restricciones y latencia.

Modos:
- `pipeline` (por defecto): envía solo los productos aptos, como hace el backend. Las
  violaciones deben ser 0; mide éxito, cobertura y latencia del flujo real.
- `modelo`: envía el catálogo completo. Mide lo que el modelo sabe por sí solo de las
  restricciones; sirve para comparar modelos o prompts.

Uso (con el servicio y Ollama en marcha):

    API_SECRET_KEY=... python scripts/evaluate.py --runs 10 --mode pipeline
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

DATASET = Path(__file__).with_name("eval_dataset.json")

# Mismas reglas que `DietaryRestriction.isSatisfiedBy` del backend.
_SATISFIED_BY = {
    "VEGETARIANO": {"VEGETARIANO", "VEGANO"},
    "VEGANO": {"VEGANO"},
    "SIN_GLUTEN": {"SIN_GLUTEN"},
    "SIN_LACTOSA": {"SIN_LACTOSA", "VEGANO"},
}


def is_suitable(tags: Iterable[str], restrictions: Iterable[str]) -> bool:
    """Si un producto con estas etiquetas cumple todas las restricciones."""
    tag_set = set(tags)
    return all(tag_set & _SATISFIED_BY[r] for r in restrictions if r in _SATISFIED_BY)


def candidates(catalog: list[dict[str, Any]], restrictions: list[str], mode: str):
    """Productos que se envían: solo los aptos en modo `pipeline`, todos en `modelo`."""
    if mode == "modelo":
        return catalog
    return [p for p in catalog if is_suitable(p["etiquetas"], restrictions)]


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de las corridas de un escenario. Cada corrida tiene `status`,
    `latency`, `requested` y `recommended` (lista de ids aptos o no, como
    `(id, apto)`).
    """
    ok = [r for r in runs if r["status"] == 200]
    returned = sum(len(r["recommended"]) for r in ok)
    requested = sum(r["requested"] for r in ok)
    violations = sum(1 for r in ok for _, suitable in r["recommended"] if not suitable)
    latencies = [r["latency"] for r in runs]
    return {
        "ok": len(ok),
        "errors": len(runs) - len(ok),
        "returned": returned,
        "requested": requested,
        "violations": violations,
        "p50": statistics.median(latencies) if latencies else 0.0,
        "max": max(latencies) if latencies else 0.0,
    }


def _run_scenario(client, scenario, catalog, mode, runs, user_base):
    products = candidates(catalog, scenario["restrictions"], mode)
    if not products:
        return None
    tags_by_id = {p["id"]: p["etiquetas"] for p in catalog}
    body_products = [
        {k: p[k] for k in ("id", "nombre", "precio", "categoria")} for p in products
    ]
    results = []
    for i in range(runs):
        body = {
            "user_id": user_base + i,
            "restrictions": scenario["restrictions"],
            "preferences": scenario["preferences"],
            "available_products": body_products,
            "max_recommendations": scenario["max_recommendations"],
        }
        started = time.perf_counter()
        # Como el backend: el límite de peticiones del servicio es por estudiante.
        response = client.post(
            "/api/ai/recommendations",
            json=body,
            headers={"X-Nomi-User-Id": str(body["user_id"])},
        )
        latency = time.perf_counter() - started
        recommended = []
        if response.status_code == 200:
            for rec in response.json()["recommendations"]:
                pid = rec["product_id"]
                ok = is_suitable(tags_by_id[pid], scenario["restrictions"])
                recommended.append((pid, ok))
        results.append(
            {
                "status": response.status_code,
                "latency": latency,
                "requested": min(scenario["max_recommendations"], len(products)),
                "recommended": recommended,
            }
        )
    return summarize(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8001")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--mode", choices=("pipeline", "modelo"), default="pipeline")
    args = parser.parse_args()

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    headers = {"X-API-Key": os.environ.get("API_SECRET_KEY", "")}
    user_base = random.randint(1_000_000, 9_000_000)

    print(f"modo={args.mode} corridas={args.runs}")
    print(
        f"{'escenario':<28}{'200':>5}{'err':>5}{'recs':>10}{'viol':>6}{'p50':>7}{'max':>7}"
    )
    with httpx.Client(base_url=args.url, headers=headers, timeout=30) as client:
        for n, scenario in enumerate(dataset["scenarios"]):
            summary = _run_scenario(
                client,
                scenario,
                dataset["catalog"],
                args.mode,
                args.runs,
                user_base + n * 1000,
            )
            if summary is None:
                print(f"{scenario['name']:<28} sin productos aptos")
                continue
            recs = f"{summary['returned']}/{summary['requested']}"
            print(
                f"{scenario['name']:<28}{summary['ok']:>5}{summary['errors']:>5}"
                f"{recs:>10}{summary['violations']:>6}"
                f"{summary['p50']:>7.1f}{summary['max']:>7.1f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
