"""Cálculos del script de evaluación: cumplimiento de restricciones, candidatos y
resumen.
"""

from __future__ import annotations

import json

from scripts.evaluate import DATASET, candidates, is_suitable, summarize


def test_is_suitable_sigue_las_reglas_del_backend():
    assert is_suitable(["VEGANO"], ["VEGETARIANO", "SIN_LACTOSA"])
    assert not is_suitable(["VEGETARIANO"], ["VEGANO"])
    assert not is_suitable([], ["SIN_GLUTEN"])
    assert is_suitable([], [])
    assert is_suitable([], ["NINGUNA"])


def test_en_modo_pipeline_solo_se_envian_productos_aptos():
    catalog = json.loads(DATASET.read_text(encoding="utf-8"))["catalog"]
    vegan_ids = [p["id"] for p in candidates(catalog, ["VEGANO"], "pipeline")]
    assert vegan_ids == [4, 5]
    assert len(candidates(catalog, ["VEGANO"], "modelo")) == len(catalog)


def test_summarize_cuenta_violaciones_y_errores():
    runs = [
        {"status": 200, "latency": 1.0, "requested": 3, "recommended": [(1, True)]},
        {"status": 200, "latency": 3.0, "requested": 3, "recommended": [(2, False)]},
        {"status": 503, "latency": 2.0, "requested": 3, "recommended": []},
    ]
    summary = summarize(runs)
    assert summary["ok"] == 2
    assert summary["errors"] == 1
    assert (summary["returned"], summary["requested"]) == (2, 6)
    assert summary["violations"] == 1
    assert summary["p50"] == 2.0
    assert summary["max"] == 3.0
