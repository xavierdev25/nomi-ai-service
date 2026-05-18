"""OpenTelemetry tracing helpers."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.trace import INVALID_SPAN_CONTEXT


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if span_context == INVALID_SPAN_CONTEXT or not span_context.trace_id:
        return "untraced"
    return f"{span_context.trace_id:032x}"
