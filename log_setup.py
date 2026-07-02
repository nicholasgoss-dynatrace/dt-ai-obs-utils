"""
Shared OTLP log setup for all three instrumentation apps.

Sets up a LoggerProvider exporting directly to Dynatrace, and optionally
instruments Python's standard logging module so every log record carries
the active trace_id and span_id.

OTel trace injection (inject_trace_context=True) only works when the app
owns the global OTel TracerProvider — i.e. OpenLLMetry and OpenInference.
For OneAgent, pass inject_trace_context=False: OneAgent does not register
as the OTel global provider, so trace.get_current_span() returns a no-op
span and injected trace IDs would be all zeros. OneAgent log correlation
is handled natively by OneAgent Log Monitoring, which captures stdout and
links log lines to traces via its own context propagation.
"""

import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource


def setup_logging(
    service_name: str,
    dt_endpoint: str,
    dt_api_token: str,
    inject_trace_context: bool = True,
) -> logging.Logger:
    """
    Wire up OTel log export to Dynatrace.

    Always exports directly to DT_ENDPOINT (not via the OTel Collector) so that
    log-to-trace correlation works regardless of where spans go.

    Set inject_trace_context=False for OneAgent — see module docstring.
    """
    resource = Resource.create({SERVICE_NAME: service_name})
    logger_provider = LoggerProvider(resource=resource)

    exporter = OTLPLogExporter(
        endpoint=f"{dt_endpoint.rstrip('/')}/api/v2/otlp/v1/logs",
        headers={"Authorization": f"Api-Token {dt_api_token}"},
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(logger_provider)

    if inject_trace_context:
        # Injects otelTraceID / otelSpanID into every Python log record using
        # the active OTel span — only meaningful when the app owns the global provider.
        LoggingInstrumentor().instrument(set_logging_format=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # stdout handler — explicit because basicConfig is a no-op once any handler exists
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    # Bridge Python logging to the OTel LoggerProvider so records are exported via OTLP.
    root.addHandler(LoggingHandler(logger_provider=logger_provider))

    return logging.getLogger(service_name)
