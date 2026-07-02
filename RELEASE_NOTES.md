# Release Notes — v0.1.5

**Date:** 2026-07-02
**License:** Apache 2.0

---

## Overview

Fixes duplicate log ingestion for the OpenLLMetry and OpenInference services, and removes non-functional OTLP log export from the OneAgent service.

---

## What's New

### Duplicate log fix (OpenLLMetry and OpenInference)

After v0.1.4, these services emitted logs both via OTLP (to the correct service entity) and to stdout. OneAgent Log Monitoring was ingesting the stdout/journald stream and creating a second copy of every log record attributed to the wrong service entity (`SERVICE-97B5EFE9D15D69BF` or null). Fixed by removing the `StreamHandler` from `log_setup.py` — logs now flow exclusively via OTLP to the correct service entity.

### OneAgent log correlation

OTLP log export for the OneAgent service is removed. OTLP created a separate service entity split from the OneAgent-discovered service, and OneAgent's proprietary trace IDs don't match OTel W3C trace IDs so log-to-trace correlation was broken regardless. The OneAgent service now logs to stdout only via standard Python `logging.basicConfig`.

**Known limitation:** OneAgent Log Monitoring does not correlate containerized service logs to the correct service entity in this rootless Podman + journald setup. Log visibility for the OneAgent service in the Service Logs tab is not achievable in the current configuration.

---

## Changes Since v0.1.4

| File | Change |
|---|---|
| `log_setup.py` | Removed `StreamHandler` — OTLP services emit logs via OTLP only |
| `app_oneagent.py` | Removed `log_setup` import and OTLP export; uses `logging.basicConfig` + stdout |

---

## Upgrading from v0.1.4

No breaking changes. Rebuild containers after the update:

```bash
./stop.sh && ./start.sh --build
```

---

# Release Notes — v0.1.4

**Date:** 2026-07-02
**License:** Apache 2.0

---

## Overview

Adds trace-correlated log export to all three services. Every log record now carries the active `trace_id` and `span_id`, enabling log-to-trace correlation in Dynatrace for all three instrumentation methods — including OneAgent, which previously had no log visibility in the Service view.

---

## What's New

### Shared `log_setup.py`

New module used by all three apps. On startup it:

- Creates a `LoggerProvider` with an `OTLPLogExporter` pointed directly at `DT_ENDPOINT/api/v2/otlp/v1/logs` — bypassing the OTel Collector for OpenInference so logs always reach Dynatrace regardless of where spans go
- Calls `LoggingInstrumentor().instrument(set_logging_format=True)` to inject `otelTraceID` and `otelSpanID` into every Python log record via the active span context

### Per-request structured logging

Each `/ask` handler now emits two INFO log lines within the active span:

```
ask request received prompt_length=<n> provider=<anthropic|openai>
llm response model=<model> input_tokens=<n> output_tokens=<n>
```

Because these are emitted inside the HTTP server span (and for OpenLLMetry, inside the workflow span), Dynatrace can link them directly to the trace.

### OneAgent log correlation

OneAgent manages its own tracer provider. `LoggingInstrumentor` reads the active span from `trace.get_current_span()` — which returns OneAgent's injected span — so log records carry OneAgent trace IDs and correlate to OneAgent traces automatically. No additional setup required.

---

## Changes Since v0.1.3

| File | Change |
|---|---|
| `log_setup.py` | New — shared OTLP log export and logging instrumentation |
| `app_oneagent.py` | Imports `log_setup`; reads `DT_ENDPOINT`/`DT_API_TOKEN`; logs per-request events |
| `app_openllmetry.py` | Imports `log_setup`; logs per-request events |
| `app_openinference.py` | Imports `log_setup`; logs per-request events |
| `requirements_oneagent.txt` | Added `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-logging` |
| `requirements_openllmetry.txt` | Added `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-logging` |
| `requirements_openinference.txt` | Added `opentelemetry-instrumentation-logging` |
| `Dockerfile.oneagent` | Added `COPY log_setup.py .` |
| `Dockerfile.openllmetry` | Added `COPY log_setup.py .` |
| `Dockerfile.openinference` | Added `COPY log_setup.py .` |

---

## Upgrading from v0.1.3

No breaking changes. `DT_ENDPOINT` and `DT_API_TOKEN` are now read by `app_oneagent.py` in addition to the OTel apps — both are already present in `.env` so no changes needed there.

Rebuild containers after the update:

```bash
./stop.sh && ./start.sh --build
```

---

# Release Notes — v0.1.3

**Date:** 2026-07-02
**License:** Apache 2.0

---

## Overview

Adds FastAPI HTTP instrumentation to the OpenLLMetry and OpenInference services so that Dynatrace can compute throughput and failure rate for all three services — not just the OneAgent service. Previously, both OTel services emitted only LLM-level spans (no HTTP entry point), leaving the Service view without request count or failure rate data.

---

## What's New

### HTTP entry spans for OpenLLMetry and OpenInference

Both OTel services now instrument the FastAPI layer using `opentelemetry-instrumentation-fastapi`. Each inbound request generates a `server` span with `http.method`, `http.route`, and `http.status_code` as the trace root. Dynatrace uses these to populate `dt.service.request.count` and `dt.service.request.failure_count`, making throughput and failure rate visible in the Service view and AI Observability Explorer.

- **OpenLLMetry** — `FastAPIInstrumentor.instrument_app(app)` added after `Traceloop.init()`; the SDK's globally registered tracer provider is picked up automatically.
- **OpenInference** — `FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)` added with an explicit provider reference, ensuring HTTP and LLM spans share the same exporter pipeline and appear in a single trace.

### Updated trace hierarchy

| Service | Before | After |
|---|---|---|
| OpenLLMetry | `ask_question` → `call_llm` → LLM span | `POST /ask` → `ask_question` → `call_llm` → LLM span |
| OpenInference | `messages.create` (flat) | `POST /ask` → `messages.create` |

---

## Changes Since v0.1.2

| File | Change |
|---|---|
| `app_openllmetry.py` | Import and call `FastAPIInstrumentor.instrument_app(app)` |
| `app_openinference.py` | Import and call `FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)` |
| `requirements_openllmetry.txt` | Added `opentelemetry-instrumentation-fastapi>=0.45b0` |
| `requirements_openinference.txt` | Added `opentelemetry-instrumentation-fastapi>=0.45b0` |
| `README.md` | Updated comparison table, method descriptions, and "What to look for" sections |
| `instrumentation.md` | Updated comparison table, trace diagrams, code snippets, and data flow diagrams |

---

## Upgrading from v0.1.2

No breaking changes. Rebuild containers after the update:

```bash
./stop.sh && ./start.sh --build
```

---

# Release Notes — v0.1.2

**Date:** 2026-07-01
**License:** Apache 2.0

---

## Overview

The three instrumented apps are now LLM provider agnostic. A new shared `llm_client.py` module abstracts provider selection, client initialization, and response normalization. Switching between Anthropic and OpenAI requires only a one-line change in `.env` — no application code changes.

---

## What's New

### LLM provider abstraction (`llm_client.py`)

New shared module used by all three apps:

- `PROVIDER` — reads `LLM_PROVIDER` env var (default: `anthropic`)
- `create_client()` — returns the native SDK client for the configured provider
- `call_llm()` — calls the provider and returns a normalized `LLMResponse` (content, model, input_tokens, output_tokens)
- `default_model()` — returns the provider's recommended evaluation model if `MODEL` is unset (`claude-haiku-4-5-20251001` for Anthropic, `gpt-4o-mini` for OpenAI)

### OpenAI support

All three instrumentation paths now work with OpenAI:

- **OneAgent** — enable the **Python OpenAI** feature flag in Settings → OneAgent features; zero app code changes
- **OpenLLMetry** — `traceloop-sdk` auto-instruments whichever SDK is active; no code changes needed
- **OpenInference** — `OpenAIInstrumentor` is selected automatically when `LLM_PROVIDER=openai`

### API response includes `provider` field

All `/ask` and `/health` responses now include `"provider": "anthropic"` or `"provider": "openai"` for easy verification.

---

## Changes Since v0.1.1

| File | Change |
|---|---|
| `llm_client.py` | New — shared provider abstraction |
| `app_oneagent.py` | Uses `llm_client`; adds `provider` to response |
| `app_openllmetry.py` | Uses `llm_client`; adds `provider` to response |
| `app_openinference.py` | Uses `llm_client`; conditional instrumentor on `PROVIDER`; adds `provider` to response |
| `requirements_*.txt` | Added `openai>=1.0.0` to all three |
| `requirements_openinference.txt` | Added `openinference-instrumentation-openai>=0.1.0` |
| `Dockerfile.*` | Added `COPY llm_client.py .` to all three |
| `.env.template` | Added `LLM_PROVIDER`, `OPENAI_API_KEY`; `MODEL` now blank (defaults per provider) |
| `docker-compose.yml` | `LLM_PROVIDER` passed through to all three app services |
| `README.md` | New "Provider Configuration" section |

---

## Upgrading from v0.1.1

No breaking changes. Existing `.env` files using `ANTHROPIC_API_KEY` continue to work — `LLM_PROVIDER` defaults to `anthropic`. To add the new variable:

```bash
echo "LLM_PROVIDER=anthropic" >> .env
```

Rebuild containers after the update:

```bash
./stop.sh && ./start.sh --build
```

---

# Release Notes — v0.1.1

**Date:** 2026-07-01
**License:** Apache 2.0

---

## Overview

This release completes the OneAgent instrumentation path. All three services now run fully containerized via `podman-compose`, and OneAgent successfully injects the Python sensor into the oneagent container via ptrace. The root cause of previous injection failures — `enablePodmanInjection` being disabled by default in Dynatrace tenant settings — is identified and documented, along with required container exclusion rules and a Fedora 44 compatibility fix.

---

## What's New

### OneAgent now fully containerized

`app_oneagent.py` previously ran as a native host process (required to work around OneAgent's in-container install block). It now runs in a Podman container alongside the other two services, simplifying the stack to a single `podman-compose up`.

### OneAgent Podman injection working

Resolved the root cause of all `Container injection failed` log entries: `enablePodmanInjection` is `off` by default in Dynatrace tenants. Once enabled (**Settings → Infrastructure monitoring → Container monitoring → Podman**), the host OneAgent successfully injects `liboneagentpython.so` into the container process via ptrace and creates a service entity after the first request.

### Container exclusion rules (required)

With `enablePodmanInjection` enabled, OneAgent injects into all containers matching the default rule (`-41::INCLUDE:CONTAINS,CONTAINER_NAME,`), including the OpenLLMetry and OpenInference containers. This creates duplicate service entities alongside their OTLP-instrumented counterparts. Container injection exclusion rules for images containing `openllmetry` and `openinference` are now documented as a required setup step.

### Fedora 44 execute-bit fix

On Fedora 44 (and some other distros), the OneAgent installer sets `liboneagentproc.so` without an execute bit, causing the preload to be silently skipped. `start.sh` now detects this condition and fixes it automatically with `sudo chmod 755`.

### Apache 2.0 LICENSE added

`LICENSE` file included in the repository root.

---

## Changes Since v0.1.0

| Area | Change |
|---|---|
| `docker-compose.yml` | `oneagent` service added with `LD_PRELOAD`, host volume mounts for agent libs and IPC socket |
| `start.sh` / `stop.sh` | Simplified to pure `podman-compose`; removed native uvicorn section; added execute-bit check |
| `README.md` | OneAgent section rewritten: 5-step setup covering Podman injection, exclusion rules, Fedora fix, and rootful-container port conflict |
| `RELEASE_NOTES.md` | This file |
| `LICENSE` | Apache 2.0 added |

---

## Known Issues

| Issue | Workaround |
|---|---|
| `enablePodmanInjection` is `off` by default | Enable in **Settings → Infrastructure monitoring → Container monitoring → Podman** |
| OneAgent injects into all containers, not just oneagent | Add image-name exclusion rules for `openllmetry` and `openinference` (see README Step 4) |
| Rootful Podman containers hold port 8001 if previously used for testing | `sudo podman stop/rm dt-ai-obs-test_oneagent_1` before starting rootless stack |
| `otlphttp` exporter name deprecated in OTel Collector 0.51+ | Non-breaking warning; will be updated in a future release |
| Apple Silicon: OneAgent has no ARM Linux build | Container configured with `platform: linux/amd64`; runs via Rosetta emulation |

---

## Requirements

- Python 3.11+ (inside containers)
- Podman + podman-compose
- Dynatrace SaaS tenant with DPS license and Grail enabled
- Anthropic API key
- Dynatrace API token with scopes: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`
- Dynatrace PaaS token (OneAgent host installation only)
- OneAgent installed on the host machine with `enablePodmanInjection` enabled

---

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
