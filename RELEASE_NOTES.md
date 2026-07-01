# Release Notes — v0.1.0

**Date:** 2026-07-01
**License:** Apache 2.0

---

## Overview

Initial release of the Dynatrace AI Observability Instrumentation Comparison project. This is a self-contained test environment for demonstrating and comparing the three supported instrumentation paths for AI agent applications in Dynatrace AI Observability: OneAgent, OpenLLMetry, and OpenInference.

All three services expose an identical `/ask` endpoint backed by the Anthropic Claude API. Only the instrumentation layer differs, making it straightforward to compare what each method captures, how traces are structured, and what setup is required.

---

## What's Included

### Three instrumented FastAPI applications

| App | Method | Port |
|---|---|---|
| `app_oneagent.py` | OneAgent auto-instrumentation | 8001 |
| `app_openllmetry.py` | OpenLLMetry (`traceloop-sdk`) | 8002 |
| `app_openinference.py` | OpenInference (`openinference-instrumentation-anthropic`) | 8003 |

### Infrastructure
- **`docker-compose.yml`** — orchestrates all three apps plus the OTel Collector
- **`otel-collector-config.yaml`** — Dynatrace OTel Collector config that normalizes OpenInference attribute conventions (`llm.model_name`, `llm.token_count.*`, etc.) to `gen_ai.*` semantic conventions required by Dynatrace AI Observability
- **Separate Dockerfiles** per service (`Dockerfile.oneagent`, `Dockerfile.openllmetry`, `Dockerfile.openinference`)

### Testing
- **`test_all.sh`** — sends 9 prompts across three quality tiers (poor / mediocre / excellent) to all three services simultaneously, producing varied token counts and latencies for meaningful AI Observability signal
  - Supports `./test_all.sh "custom prompt"` for single-prompt mode
  - Runs services in parallel per round, sequential across rounds with a 2-second pause for trace separation

### Configuration
- **`.env.template`** — safe-to-commit template with placeholder values for all required credentials
- Configurable `SERVICE_NAME` env var (OpenLLMetry + OpenInference service name in Dynatrace)
- Configurable `HOST_GROUP` env var (OneAgent host group)

### Distribution
- **`export.sh`** — generates a clean customer tarball (`dt-ai-obs-test-YYYYMMDD.tar.gz`) via `git archive` with no git history and no secrets

---

## Instrumentation Notes

### OneAgent
- Zero code changes required in the application
- Requires the **Python Anthropic** (experimental) and **Python FastAPI** OneAgent feature flags to be enabled in your Dynatrace tenant before first use
- **Known limitation:** OneAgent 1.341+ blocks installer execution inside a container by policy. For containerized environments, OneAgent must be installed at the host level. For direct host testing, run `app_oneagent.py` with `uvicorn` and install OneAgent on the host machine.
- Apple Silicon: the container is configured with `platform: linux/amd64` to run via Rosetta emulation, as OneAgent has no ARM Linux build

### OpenLLMetry
- Uses `traceloop-sdk` with `@workflow` and `@task` decorators for trace hierarchy
- Exports spans and `gen_ai.*` metrics directly to Dynatrace via OTLP
- Prompt and completion content capture enabled via `TRACELOOP_TRACE_CONTENT=true`
- Requires `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta` for correct metric aggregation in Dynatrace

### OpenInference
- Uses `openinference-instrumentation-anthropic` for automatic Anthropic SDK instrumentation
- Requires OTel Collector for attribute normalization from OpenInference conventions to `gen_ai.*`
- `ai.observability.source = openinference` attribute set on all spans for DQL filtering
- Spans include `gen_ai.input.messages` and `gen_ai.output.messages` (prompt + response content) by default
- Alternative: OpenPipeline can replace the OTel Collector — see README for configuration steps

---

## Known Issues

| Issue | Workaround |
|---|---|
| OneAgent 1.341+ blocks container installation | Run `app_oneagent.py` directly on the host with host-level OneAgent installed |
| Podman `krunkit` provider may fail on some macOS configurations | Use `podman machine init --provider applehv` instead |
| `otlphttp` exporter name deprecated in OTel Collector 0.51+ | Non-breaking warning; will be updated to `otlp_http` in a future release |

---

## Requirements

- Python 3.11+
- Podman + podman-compose (or Docker + docker-compose)
- Dynatrace SaaS tenant with DPS license and Grail enabled
- Anthropic API key
- Dynatrace API token with scopes: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`
- Dynatrace PaaS token (OneAgent path only)
