import re
import secrets
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request

CORRELATION_HEADER = "X-AI-ACQ-QA-Correlation-Id"
REQUEST_ID_HEADER = "X-Request-ID"
TRACEPARENT_HEADER = "traceparent"
TRACE_ID_HEADER = "X-AI-ACQ-Trace-Id"
SPAN_ID_HEADER = "X-AI-ACQ-Span-Id"

EXPOSED_CORRELATION_HEADERS = [
    CORRELATION_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    TRACE_ID_HEADER,
    SPAN_ID_HEADER,
]

correlation_id_var: ContextVar[str] = ContextVar("ai_acq_correlation_id", default="")
traceparent_var: ContextVar[str] = ContextVar("ai_acq_traceparent", default="")

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")
_TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def current_correlation_id() -> str:
    return correlation_id_var.get()


def current_traceparent() -> str:
    return traceparent_var.get()


def _safe_header_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _SAFE_ID_RE.match(candidate):
        return candidate
    return str(uuid.uuid4())


def _new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def _safe_traceparent(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    if _TRACEPARENT_RE.match(candidate):
        trace_id = candidate.split("-")[1]
        span_id = candidate.split("-")[2]
        if trace_id != "0" * 32 and span_id != "0" * 16:
            return candidate
    return _new_traceparent()


def _trace_parts(traceparent: str) -> tuple[str, str]:
    parts = traceparent.split("-")
    if len(parts) >= 4:
        return parts[1], parts[2]
    return "", ""


def install_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = _safe_header_id(
            request.headers.get(CORRELATION_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or request.headers.get("X-Correlation-ID")
        )
        traceparent = _safe_traceparent(request.headers.get(TRACEPARENT_HEADER))
        trace_id, span_id = _trace_parts(traceparent)
        request.state.correlation_id = correlation_id
        request.state.traceparent = traceparent
        correlation_token = correlation_id_var.set(correlation_id)
        trace_token = traceparent_var.set(traceparent)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            response.headers[REQUEST_ID_HEADER] = correlation_id
            response.headers[TRACEPARENT_HEADER] = traceparent
            response.headers[TRACE_ID_HEADER] = trace_id
            response.headers[SPAN_ID_HEADER] = span_id
            return response
        finally:
            correlation_id_var.reset(correlation_token)
            traceparent_var.reset(trace_token)
