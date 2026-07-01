# Dynatrace AI Observability — Instrumentation Comparison

> **Objective:** Demonstrate and compare the three paths to instrumenting an AI agent application for [Dynatrace AI Observability](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability) — OneAgent, OpenLLMetry, and OpenInference — so you can see exactly what each method captures, how the trace structure differs, and what it takes to get there.

This project provides three identical FastAPI services, each calling the Anthropic Claude API with the same prompt, but instrumented differently. The test script sends prompts across a quality spectrum (poor → mediocre → excellent) to generate meaningful signal in AI Observability.

---

## Instrumentation Methods at a Glance

| Service | Method | Port | Code changes? | Requires OneAgent? | OTel Collector? |
|---|---|---|---|---|---|
| `app_oneagent.py` | **OneAgent** (auto) | 8001 | ❌ None | ✅ Yes | ❌ No |
| `app_openllmetry.py` | **OpenLLMetry** SDK | 8002 | ✅ ~10 lines | ❌ No | ❌ No |
| `app_openinference.py` | **OpenInference** SDK | 8003 | ✅ ~20 lines | ❌ No | ✅ Yes (included) |

---

## Prerequisites

- **Podman + podman-compose** — see setup below
- **Anthropic API key** — obtain from [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys); add to `.env` only, never commit it
- **Dynatrace SaaS tenant** with a DPS license and Grail enabled
- **Dynatrace API token** with scopes: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`
- **Dynatrace PaaS token** (OneAgent only) — from **Settings → Integration → Platform as a Service**

---

## Podman Setup (first time only)

```bash
brew install podman podman-compose

podman machine init
podman machine start

podman info   # verify
```

---

## Quick Start

```bash
# 1. Copy and fill in your credentials
cp .env.template .env
#    Set: DT_ENDPOINT, DT_API_TOKEN, DT_PAAS_TOKEN, ANTHROPIC_API_KEY, MODEL

# 2. Build and start all four containers
podman-compose up --build
```

Once healthy, run the full prompt quality test across all three services simultaneously:

```bash
./test_all.sh
```

Or send a single custom prompt:

```bash
./test_all.sh "How does distributed tracing work in a microservices architecture?"
```

Or hit a single service directly:

```bash
curl -s -X POST http://localhost:8001/ask \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is observability?"}' | python3 -m json.tool
```

Ports: `8001` = OneAgent · `8002` = OpenLLMetry · `8003` = OpenInference

---

## Method Details

### 🔵 OneAgent (port 8001)

**How it works:** Zero code changes. OneAgent intercepts Anthropic SDK calls at the process level and emits `gen_ai.*` spans automatically — no SDK imports or decorators required in `app_oneagent.py`.

> **⚠️ Container limitation:** OneAgent 1.341+ blocks installation inside a container by policy. For containerized testing, run `app_oneagent.py` directly on your host machine (see [Running Without Containers](#running-without-containers)) with OneAgent installed at the host level. OneAgent installed on the host automatically monitors all processes, including those inside containers.

> **Apple Silicon note:** If running the container, OneAgent has no ARM Linux build — `docker-compose.yml` sets `platform: linux/amd64` to run via Rosetta. This is moot if using the host approach.

**Required `.env` values:** `DT_ENDPOINT`, `DT_PAAS_TOKEN`

**Required Dynatrace feature flags** — enable in **Settings → Collect and capture → General monitoring settings → OneAgent features** before sending requests:
- **Python Anthropic** *(experimental sensor — required)*
- **Python FastAPI** *(required — creates the HTTP entry-point span that LLM spans nest under)*

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service appears after the first request
- **Distributed Tracing**: `POST /ask` span with a child `anthropic` span carrying `gen_ai.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`

---

### 🟣 OpenLLMetry (port 8002)

**How it works:** The `traceloop-sdk` wraps the Anthropic SDK and exports spans + metrics directly to Dynatrace via OTLP. `@workflow` and `@task` decorators in `app_openllmetry.py` define the trace hierarchy. Prompt and completion content are captured for quality analysis.

**Required `.env` values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `ANTHROPIC_API_KEY`

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openllmetry` (or your `SERVICE_NAME`) appears after the first request
- **Distributed Tracing**: trace named `ask_question` with a `workflow → task → LLM` span hierarchy
- Attributes to verify: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Metrics**: `gen_ai.*` OTLP metrics (token totals, request counts) exported alongside traces

---

### 🟢 OpenInference (port 8003)

**How it works:** `openinference-instrumentation-anthropic` auto-instruments the Anthropic client using OpenInference attribute conventions (`llm.model_name`, `llm.token_count.*`, etc.). Because Dynatrace AI Observability expects `gen_ai.*` attributes, spans are routed through the included OTel Collector, which normalizes them before forwarding to Dynatrace. Prompt and response content are captured by default in `input.value` / `output.value`.

**Required `.env` values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `ANTHROPIC_API_KEY`

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openinference` (or your `SERVICE_NAME`) appears after the first request
- **Distributed Tracing**: verify `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` are present (these are the normalized attributes)
- `ai.observability.source = openinference` confirms the OTel Collector transform ran

**Alternative — OpenPipeline (no Collector):** Configure a pipeline in Dynatrace (Ctrl+K → **OpenPipeline** → **Spans**) using the attribute mappings in `otel-collector-config.yaml`, with routing matcher `isNotNull(openinference.span.kind)`. Then update `docker-compose.yml` to set `OTEL_EXPORTER_OTLP_ENDPOINT=${DT_ENDPOINT}/api/v2/otlp` and remove the `depends_on` and `otel-collector` service.

---

## What to Compare Across All Three

Once all three are running and sending data, AI Observability → Explorer surfaces meaningful differences:

| Dimension | OneAgent | OpenLLMetry | OpenInference |
|---|---|---|---|
| **Setup effort** | Zero code changes | ~10 lines + decorators | ~20 lines + normalization |
| **Trace structure** | HTTP entry span → LLM child span | `workflow → task → LLM` hierarchy | Flat LLM spans |
| **Prompt content** | Requires feature flag opt-in | ✅ Captured | ✅ Captured |
| **Metrics** | Derived from traces | ✅ Native OTLP metrics | Derived from traces |
| **Attribute source** | Auto via OneAgent sensor | Native `gen_ai.*` | OpenInference → normalized via Collector |

The test script's prompt quality tiers (poor / mediocre / excellent) are designed to produce clearly different token counts, latencies, and response lengths — giving AI Observability enough signal to show you patterns across all three methods simultaneously.

---

## Running Without Containers

Each app can also be run directly:

```bash
# OneAgent — requires OneAgent installed on the host
pip install -r requirements_oneagent.txt
uvicorn app_oneagent:app --port 8001

# OpenLLMetry
pip install -r requirements_openllmetry.txt
uvicorn app_openllmetry:app --port 8002

# OpenInference (with OTel Collector running separately on port 4318)
pip install -r requirements_openinference.txt
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uvicorn app_openinference:app --port 8003
```

---

## Customer Distribution

To export a clean tarball (no git history, no secrets) for sharing:

```bash
./export.sh
# → outputs dt-ai-obs-test-YYYYMMDD.tar.gz one level above this directory
```

---

## Reference

- [Dynatrace AI Observability — OneAgent](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/oneagent)
- [Dynatrace AI Observability — OpenLLMetry](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openllmetry)
- [Dynatrace AI Observability — OpenInference](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openinference)
- [Dynatrace AI instrumentation examples](https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples)

---

*Licensed under the [Apache License 2.0](LICENSE).*
