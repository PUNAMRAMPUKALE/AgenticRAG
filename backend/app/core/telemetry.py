from __future__ import annotations

import logging
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

from app.core.config import Settings

log = logging.getLogger(__name__)

_SERVICE = "agenticrag"
_configured = False


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_SERVICE)


def current_trace_ids() -> tuple[str, str]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return "", ""
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def record_exception(exc: BaseException) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))


def setup_telemetry(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    resource = Resource.create(
        {
            "service.name": settings.otel_service_name.strip() or _SERVICE,
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        traces_url = endpoint.rstrip("/")
        if not traces_url.endswith("/v1/traces"):
            traces_url = f"{traces_url}/v1/traces"
        headers = _parse_headers(settings.otel_exporter_otlp_headers)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url, headers=headers)))
        host = urlparse(endpoint).netloc or endpoint
        log.info("OTLP trace export enabled (%s)", host)
    elif settings.environment.lower() == "production":
        log.warning(
            "Production traces are not exported. Set OTEL_EXPORTER_OTLP_ENDPOINT "
            "(Grafana Tempo, Jaeger, Honeycomb, Datadog OTLP)."
        )
    elif settings.otel_console_spans:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()


def instrument_app(app) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health|metrics")


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key, value = key.strip(), value.strip()
        if key:
            headers[key] = value
    return headers
