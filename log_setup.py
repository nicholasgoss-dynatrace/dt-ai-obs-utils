"""
Shared OTLP log setup for all three instrumentation apps.

Sets up a LoggerProvider exporting directly to Dynatrace, and instruments
Python's standard logging module so every log record carries the active
trace_id and span_id — enabling log-to-trace correlation in Dynatrace.
"""

import logging

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource


def setup_logging(service_name: str, dt_endpoint: str, dt_api_token: str) -> logging.Logger:
    """
    Wire up OTel log export to Dynatrace and inject trace context into log records.

    Always exports directly to DT_ENDPOINT (not via the OTel Collector) so that
    log-to-trace correlation works regardless of whether spans go through a Collector.
    """
    resource = Resource.create({SERVICE_NAME: service_name})
    logger_provider = LoggerProvider(resource=resource)

    exporter = OTLPLogExporter(
        endpoint=f"{dt_endpoint.rstrip('/')}/api/v2/otlp/v1/logs",
        headers={"Authorization": f"Api-Token {dt_api_token}"},
    )
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(logger_provider)

    # Injects otelTraceID / otelSpanID into every Python log record
    LoggingInstrumentor().instrument(set_logging_format=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return logging.getLogger(service_name)
