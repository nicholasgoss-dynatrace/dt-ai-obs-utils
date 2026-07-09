"""
GenAiSpanEnricher — SpanProcessor that injects extra attributes into
instrumentor-generated gen_ai spans so they appear in DT AI Obs Explorer.

Two injection points:

  on_start  — fires while the span is writable; used for tool-use attributes
              that are known BEFORE the second LLM call (stored in a ContextVar
              immediately before calling messages.create / chat.completions).

  on_end    — fires before the BatchSpanProcessor queues the span; used for
              gen_ai.error.code which is only known after the exception is
              caught by the instrumentor's own error handling. The ReadableSpan
              object still has a mutable _attributes dict at this point.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from opentelemetry.sdk.trace import SpanProcessor, ReadableSpan
from opentelemetry.trace import Span

# ── Shared state (ContextVar is coroutine-safe; threading.local is not needed) ─

_pending_attrs: ContextVar[dict[str, Any] | None] = ContextVar("_pending_attrs", default=None)
_pending_error_code: ContextVar[str | None] = ContextVar("_pending_error_code", default=None)


def set_pending_attrs(**attrs: Any) -> None:
    """Call immediately before messages.create() to inject attrs into the next gen_ai span."""
    _pending_attrs.set(attrs)


def set_pending_error_code(code: str) -> None:
    """Call in an except block to inject gen_ai.error.code into the closing gen_ai span."""
    _pending_error_code.set(code)


def clear_pending() -> None:
    _pending_attrs.set(None)
    _pending_error_code.set(None)


class GenAiSpanEnricher(SpanProcessor):
    """Injects pending gen_ai attributes into instrumentor-managed spans."""

    def on_start(self, span: Span, parent_context=None) -> None:
        attrs = _pending_attrs.get()
        if attrs:
            for k, v in attrs.items():
                span.set_attribute(k, v)
            _pending_attrs.set(None)

    def on_end(self, span: ReadableSpan) -> None:
        code = _pending_error_code.get()
        if not code:
            return
        # Only inject into gen_ai spans (those the instrumentor created)
        raw_attrs = getattr(span, "_attributes", None)
        if raw_attrs is None:
            return
        if raw_attrs.get("gen_ai.system"):
            raw_attrs["gen_ai.error.code"] = code
            _pending_error_code.set(None)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
