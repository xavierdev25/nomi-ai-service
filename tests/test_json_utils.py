"""Tests de extracción JSON desde respuestas LLM."""

from __future__ import annotations

import pytest

from services.json_utils import extract_json


def test_clean_json_array_parses_correctly():
    result = extract_json('[{"product_id": 1, "score": 0.9}]')

    assert result == [{"product_id": 1, "score": 0.9}]


def test_json_embedded_in_markdown_code_block_extracts_correctly():
    result = extract_json('```json\n{"product_id": 2, "score": 0.8}\n```')

    assert result == {"product_id": 2, "score": 0.8}


def test_completely_invalid_string_raises_value_error():
    with pytest.raises(ValueError, match="Could not extract valid JSON"):
        extract_json("esto no es json para nada")
