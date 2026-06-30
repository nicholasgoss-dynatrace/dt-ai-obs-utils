# Dynatrace AI Observability — Instrumentation Comparison

Three FastAPI services, each demonstrating a different instrumentation path to Dynatrace AI Observability. All three expose the same `/ask` endpoint and make identical OpenAI chat completion calls — only the instrumentation layer differs.

| Service | Method | Port | Requires OneAgent? | Code changes? | OTel Collector? |
|---|---|---|---|---|---|
| `app_oneagent.py` | OneAgent (auto) | 8001 | ✅ Yes | ❌ No | ❌ No |
| `app_openllmetry.py` | OpenLLMetry SDK | 8002 | ❌ No | ✅ Yes | ❌ No |
| `app_openinference.py` | OpenInference SDK | 8003 | ❌ No | ✅ Yes | ✅ Yes (included) |

---

## Prerequisites

- Docker + Docker Compose
- OpenAI API key
- Dynatrace SaaS tenant with a DPS license and Grail enabled
- Dynatrace API token with scopes: `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`
- Dynatrace PaaS token (OneAgent only) — from **Settings → Integration → Platform as a Service**

---

## Quick start

```bash
cp .env.template .env
# Fill in all values in .env, then:

docker compose up --build
```

All four containers start: the three instrumented apps plus the OTel Collector (used by the OpenInference service). Once healthy, fire a test prompt at all three simultaneously:

```bash
./test_all.sh "What is observability?"

# Or hit them individually:
curl -s -X POST http://localhost:8001/ask -H "Content-Type: application/json" -d '{"prompt": "What is observability?"}' | python3 -m json.tool  # OneAgent
curl -s -X POST http://localhost:8002/ask -H "Content-Type: application/json" -d '{"prompt": "What is observability?"}' | python3 -m json.tool  # OpenLLMetry
curl -s -X POST http://localhost:8003/ask -H "Content-Type: application/json" -d '{"prompt": "What is observability?"}' | python3 -m json.tool  # OpenInference
```

Then check **AI Observability → Explorer** in your Dynatrace tenant to see data from all three.

---

## Per-method details

### OneAgent (port 8001)

**What it is:** Zero-code instrumentation. OneAgent is downloaded and installed inside the container at startup via `docker-entrypoint-oneagent.sh`. It intercepts Python OpenAI SDK calls at the process level and emits `gen_ai.*` spans automatically — no SDK imports or decorators required in `app_oneagent.py`.

**Required .env values:** `DT_ENDPOINT`, `DT_PAAS_TOKEN`

**Required Dynatrace feature flags:** Before sending requests, enable these in **Settings → Collect and capture → General monitoring settings → OneAgent features**:
- **Python OpenAI** (required)
- **Python FastAPI** (required — creates the HTTP entry-point span LLM spans nest under)
- **Python OpenAI prompt capture** (optional — captures prompt text)

Then restart the container to pick up the new flags:
```bash
docker compose restart oneagent
```

**Validate in Dynatrace:**
- **AI Observability → Explorer**: app appears as a service once the first request completes
- **Distributed Tracing**: look for `POST /ask` span with a child `openai` span carrying `gen_ai.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`

---

### OpenLLMetry (port 8002)

**What it is:** The `traceloop-sdk` wraps the OpenAI SDK and exports spans + metrics directly to Dynatrace via OTLP. `@workflow` and `@task` decorators in `app_openllmetry.py` define the trace hierarchy.

**Required .env values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `OPENAI_API_KEY`

**Validate in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openllmetry` appears after the first request
- **Distributed Tracing**: search for trace name `ask_question` — you'll see a `workflow` span → `task` span → LLM span with `gen_ai.*` attributes
- Span attributes to verify: `gen_ai.provider`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`

---

### OpenInference (port 8003)

**What it is:** `openinference-instrumentation-openai` auto-instruments the OpenAI client using OpenInference attribute conventions (`llm.model_name`, `llm.token_count.*`, etc.). Because Dynatrace AI Observability expects `gen_ai.*` attributes, spans are routed through the OTel Collector (included in `docker-compose.yml`), which applies the transform before forwarding to Dynatrace.

**Required .env values:** `DT_ENDPOINT`, `DT_API_TOKEN`, `OPENAI_API_KEY`

**Validate in Dynatrace:**
- **AI Observability → Explorer**: service `dt-ai-obs-openinference` appears after the first request
- **Distributed Tracing**: verify `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` are present (these are the normalized attributes)
- `ai.observability.source = openinference` confirms the OTel Collector transform ran

**Alternative — OpenPipeline (no Collector):** If you'd rather not run the Collector, configure a pipeline in Dynatrace (Ctrl+K → **OpenPipeline** → **Spans**) using the attribute mappings in `otel-collector-config.yaml`, with routing matcher `isNotNull(openinference.span.kind)`. Then update `docker-compose.yml` to set `OTEL_EXPORTER_OTLP_ENDPOINT=${DT_ENDPOINT}/api/v2/otlp` and remove the `depends_on` and `otel-collector` service.

---

## Running without Docker

Each app can also be run directly with Python:

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

## What to compare across all three

Once all three are running and sending data:

- **Span structure**: OneAgent nests LLM spans under an HTTP entry-point span; OpenLLMetry creates a `workflow → task → LLM` hierarchy; OpenInference creates flat LLM spans
- **Attribute coverage**: all three surface `gen_ai.request.model` and token counts; prompt capture requires explicit opt-in (OneAgent feature flag; OpenInference captures `input.value`/`output.value` automatically)
- **Metrics**: OpenLLMetry emits `gen_ai.*` OTLP metrics (request count, token totals); OneAgent and OpenInference derive metrics from traces
- **Setup friction**: OneAgent = zero code changes; OpenLLMetry = ~10 lines + decorators; OpenInference = ~20 lines + normalization step

---

## Reference

- [OneAgent docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/oneagent)
- [OpenLLMetry docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openllmetry)
- [OpenInference docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openinference)
- [Dynatrace AI instrumentation examples](https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples)
