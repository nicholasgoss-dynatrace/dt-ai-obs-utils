# Dynatrace AI Observability — Instrumentation Comparison

> **Objective:** Demonstrate and compare the three paths to instrumenting an AI agent application for [Dynatrace AI Observability](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability) — OneAgent, OpenLLMetry, and OpenInference — so you can see exactly what each method captures, how the trace structure differs, and what it takes to get there.

This project provides three identical FastAPI services, each calling an LLM with the same prompt, but instrumented differently. The LLM provider is configurable (Anthropic or OpenAI). The test script sends prompts across a quality spectrum (poor → mediocre → excellent) to generate meaningful signal in AI Observability.

---

## Instrumentation Methods at a Glance

| Service | Method | Port | Code changes? | Requires OneAgent? | OTel Collector? | HTTP metrics? |
|---|---|---|---|---|---|---|
| `app_oneagent.py` | **OneAgent** (auto) | 8001 | ❌ None | ✅ Yes | ❌ No | ✅ Auto |
| `app_openllmetry.py` | **OpenLLMetry** SDK | 8002 | ✅ ~10 lines | ❌ No | ❌ No | ✅ FastAPI instrumentor |
| `app_openinference.py` | **OpenInference** SDK | 8003 | ✅ ~20 lines | ❌ No | ✅ Yes (included) | ✅ FastAPI instrumentor |

---

## Prerequisites

- **Podman + podman-compose** — see setup below
- **LLM API key** — Anthropic (`ANTHROPIC_API_KEY`) or OpenAI (`OPENAI_API_KEY`); add to `.env` only, never commit it
- **Dynatrace SaaS tenant** with a DPS license and Grail enabled
- **Dynatrace API token** with scopes: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`
- **Dynatrace PaaS token** (OneAgent host install only) — from **Settings → Integration → Platform as a Service**

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
#    Set: DT_ENDPOINT, DT_API_TOKEN, ANTHROPIC_API_KEY, MODEL

# 2. Start all services
./start.sh           # first run
./start.sh --build   # after code changes (rebuilds containers)
```

`start.sh` starts all services via podman-compose (oneagent, openllmetry, openinference, and the OTel Collector). No sudo required.

Once running, fire the full prompt quality test across all three services simultaneously:

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

To stop everything:

```bash
./stop.sh
```

---

## Provider Configuration

All three services share a single `LLM_PROVIDER` setting. Set it in `.env` before starting:

```bash
# Use Anthropic (default)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# — or — use OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Model defaults if `MODEL` is unset: `claude-haiku-4-5-20251001` for Anthropic, `gpt-4o-mini` for OpenAI. Override with `MODEL=<any model string>` in `.env`.

> **OneAgent note:** Enable the matching OneAgent feature flag for your provider — **Python Anthropic** or **Python OpenAI** — in Settings → OneAgent features.

> **OpenInference note:** The correct instrumentor (`AnthropicInstrumentor` or `OpenAIInstrumentor`) is selected automatically at startup based on `LLM_PROVIDER`.

After changing the provider, rebuild containers:

```bash
./stop.sh && ./start.sh --build
```

---

## Method Details

### 🔵 OneAgent (port 8001)

**How it works:** Zero code changes. OneAgent intercepts Anthropic SDK calls at the process level and emits `gen_ai.*` spans automatically — no SDK imports or decorators required in `app_oneagent.py`. The app runs in a Podman container; the host OneAgent detects it via cgroup metadata and injects the Python sensor via ptrace.

#### Host Setup (required — one-time)

**Step 1 — Install OneAgent on your host machine**

1. In Dynatrace, go to **Hub → OneAgent** (or Ctrl+K → "Deploy OneAgent")
2. Select your OS, copy the install command, run it — it includes your PaaS token automatically
3. Verify: `systemctl status oneagent` (Linux) or check the Dynatrace tray icon (macOS)

> **Fedora / RHEL note:** On some distros the installer sets `liboneagentproc.so` without an execute bit, silently breaking injection. `start.sh` detects and fixes this automatically with `sudo chmod 755`.

**Step 2 — Enable Podman container injection**

By default, OneAgent does not inject into Podman containers. Enable it once per tenant:

In **Settings → Infrastructure monitoring → Container monitoring**, enable **Podman** container monitoring.

Without this, every injection attempt logs `Container injection failed` even when ptrace permissions are fine.

**Step 3 — Enable required Python feature flags**

In **Settings → Collect and capture → General monitoring settings → OneAgent features**, enable:
- **Python Anthropic** *(experimental sensor — required)*
- **Python FastAPI** *(required — creates the HTTP entry-point span that LLM spans nest under)*
- **Log Monitoring** *(required for log-to-trace correlation — enables OneAgent to capture process stdout and link log lines to traces via its own context propagation)*

Restart OneAgent after enabling:
```bash
# Linux
sudo systemctl restart oneagent
```

**Step 4 — Add container injection exclusions**

Because OneAgent injects into any detected container, it will also attempt to inject into the OpenLLMetry and OpenInference containers — which already have OTLP instrumentation and don't need it. Exclude them to avoid duplicate service entities.

In **Settings → Processes and containers → Container monitoring → Container injection rules**, add two exclusion rules:
- Exclude containers where `Image name` **contains** `openllmetry`
- Exclude containers where `Image name` **contains** `openinference`

**Step 5 — Avoid port conflicts with rootful Podman containers**

If you previously ran `sudo podman run` to test container injection, a root-owned container may still hold port 8001. The rootless `podman-compose` container cannot start until it is removed:

```bash
sudo podman stop dt-ai-obs-test_oneagent_1
sudo podman rm dt-ai-obs-test_oneagent_1
```

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service appears after the first request
- **Distributed Tracing**: `POST /ask` span with a child `anthropic` span carrying `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`

---

### 🟣 OpenLLMetry (port 8002)

**How it works:** The `traceloop-sdk` wraps the Anthropic SDK and exports spans + metrics directly to Dynatrace via OTLP. `@workflow` and `@task` decorators in `app_openllmetry.py` define the trace hierarchy. Prompt and completion content are captured for quality analysis. `FastAPIInstrumentor` adds an HTTP server entry span on every request so Dynatrace can compute throughput and failure rate.

**Required `.env` values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `ANTHROPIC_API_KEY`

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openllmetry` (or your `SERVICE_NAME`) appears after the first request
- **Distributed Tracing**: trace with `POST /ask` HTTP server span → `ask_question` workflow → `call_llm` task → LLM span hierarchy
- Attributes to verify: `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Metrics**: `gen_ai.*` OTLP metrics (token totals, request counts) exported alongside traces; **throughput and failure rate** visible in the Service view

---

### 🟢 OpenInference (port 8003)

**How it works:** `openinference-instrumentation-anthropic` auto-instruments the Anthropic client using OpenInference attribute conventions (`llm.model_name`, `llm.token_count.*`, etc.). Because Dynatrace AI Observability expects `gen_ai.*` attributes, spans are routed through the included OTel Collector, which normalizes them before forwarding to Dynatrace. Prompt and response content are captured by default in `input.value` / `output.value`. `FastAPIInstrumentor` adds an HTTP server entry span on every request so Dynatrace can compute throughput and failure rate.

**Required `.env` values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `ANTHROPIC_API_KEY`

**What to look for in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openinference` (or your `SERVICE_NAME`) appears after the first request
- **Distributed Tracing**: `POST /ask` HTTP server span (parent) with `messages.create` LLM span as child; verify `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` are present
- `ai.observability.source = openinference` confirms the OTel Collector transform ran
- **Throughput and failure rate** now visible in the Service view

**Alternative — OpenPipeline (no Collector):** Configure a pipeline in Dynatrace (Ctrl+K → **OpenPipeline** → **Spans**) using the attribute mappings in `otel-collector-config.yaml`, with routing matcher `isNotNull(openinference.span.kind)`. Then update `docker-compose.yml` to set `OTEL_EXPORTER_OTLP_ENDPOINT=${DT_ENDPOINT}/api/v2/otlp` and remove the `depends_on` and `otel-collector` service.

---

## What to Compare Across All Three

Once all three are running and sending data, AI Observability → Explorer surfaces meaningful differences:

| Dimension | OneAgent | OpenLLMetry | OpenInference |
|---|---|---|---|
| **Setup effort** | Zero code changes | ~10 lines + decorators | ~20 lines + normalization |
| **Trace structure** | HTTP entry span → LLM child span | HTTP entry span → `workflow → task → LLM` | HTTP entry span → LLM span |
| **Prompt content** | Requires feature flag opt-in | ✅ Captured | ✅ Captured |
| **HTTP metrics (throughput/failure rate)** | ✅ Auto via OneAgent | ✅ FastAPI instrumentor | ✅ FastAPI instrumentor |
| **Attribute source** | Auto via OneAgent sensor | Native `gen_ai.*` | OpenInference → normalized via Collector |

The test script's prompt quality tiers (poor / mediocre / excellent) are designed to produce clearly different token counts, latencies, and response lengths — giving AI Observability enough signal to show you patterns across all three methods simultaneously.

---

## Running Without Containers

Each app can also be run directly. Copy `.env.template` to `.env`, fill in your values, then:

```bash
# Load env vars
source .env

# OneAgent — host-level OneAgent must be installed, Podman injection enabled,
#            and the exclusion rules added (see OneAgent setup above)
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
