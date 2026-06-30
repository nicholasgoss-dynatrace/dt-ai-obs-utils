<<<<<<< HEAD
# dt-ai-obs-test
Testing the myriad of ways to instrument an AI Agent with Dynatrace 
=======
# Dynatrace AI Observability — Instrumentation Comparison

Three minimal Python apps, each demonstrating a different instrumentation path to Dynatrace AI Observability. All three make the same OpenAI chat completion calls; only the instrumentation layer differs.

| File | Method | Requires OneAgent? | Requires code changes? | Requires OTel Collector? |
|---|---|---|---|---|
| `app_oneagent.py` | OneAgent (auto) | ✅ Yes | ❌ No | ❌ No |
| `app_openllmetry.py` | OpenLLMetry SDK | ❌ No | ✅ Yes | ❌ No |
| `app_openinference.py` | OpenInference SDK | ❌ No | ✅ Yes | Optional |

---

## Prerequisites

- Python 3.9+
- OpenAI API key
- Dynatrace SaaS tenant with a DPS license and Grail enabled
- A Dynatrace API token — see scope requirements per method below

---

## 1. Common setup

```bash
cp .env.template .env
# Fill in DT_ENDPOINT, DT_API_TOKEN, OPENAI_API_KEY, MODEL
```

---

## 2. OneAgent

### What it is
Zero-code instrumentation. OneAgent intercepts Python OpenAI SDK calls at the process level and emits `gen_ai.*` spans automatically. No SDK or decorators required in your code.

### Prerequisites
- OneAgent installed on the host running the app
- In Dynatrace: **Settings → Collect and capture → General monitoring settings → OneAgent features**, filter by "Python" and enable:
  - **Python OpenAI** (required)
  - **Python OpenAI prompt capture** (optional — captures prompt text)
  - **Python FastAPI** (required — creates the HTTP entry-point span that LLM spans nest under)

### Setup

```bash
pip install -r requirements_oneagent.txt
```

### Run

```bash
uvicorn app_oneagent:app --host 0.0.0.0 --port 8000
```

Then send test requests:

```bash
# Single request
curl -s -X POST http://localhost:8000/ask \
    -H "Content-Type: application/json" \
    -d '{"prompt": "What is observability?"}'

# Multiple requests to generate more signal
for prompt in "What is observability?" "Explain distributed tracing." "What are LLM tokens?"; do
  curl -s -X POST http://localhost:8000/ask \
    -H "Content-Type: application/json" \
    -d "{\"prompt\": \"$prompt\"}" | python3 -m json.tool
done
```

### Validate in Dynatrace
- **AI Observability → Explorer**: the app appears as a service named after its process once the first request completes
- **Distributed Tracing**: look for an HTTP `POST /ask` span with an `openai` child span carrying `gen_ai.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
- **Token scopes needed**: none (OneAgent pushes data via its own channel)

---

## 3. OpenLLMetry

### What it is
The `traceloop-sdk` wraps the OpenAI SDK and exports spans and metrics via OTLP directly to Dynatrace. Decorators (`@workflow`, `@task`) define trace structure.

### API token scopes required
- `openTelemetryTrace.ingest`
- `metrics.ingest`
- `logs.ingest`

### Setup

```bash
pip install -r requirements_openllmetry.txt
```

### Run

```bash
python app_openllmetry.py
```

You'll see output like:

```
Q: What is observability and why does it matter for AI systems?
A: Observability means ...
   [gpt-4o-mini | in=42 out=87]
...
✓ Done. Check AI Observability > Explorer in your Dynatrace tenant.
```

### Validate in Dynatrace
- **AI Observability → Explorer**: service `dt-ai-obs-openllmetry` appears after the first run
- **Distributed Tracing**: search for trace name `ask_question` — you'll see a workflow span → task spans → LLM span with `gen_ai.*` attributes
- Span attributes to verify: `gen_ai.provider`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, temperature

---

## 4. OpenInference

### What it is
`openinference-instrumentation-openai` auto-instruments the OpenAI client using OpenInference attribute conventions (`llm.model_name`, `llm.token_count.*`, etc.). Because Dynatrace AI Observability natively expects `gen_ai.*`, a normalization step is required.

**Two normalization options — pick one:**

| | Option A: OTel Collector | Option B: OpenPipeline |
|---|---|---|
| Where transforms run | Locally in Docker | Server-side in Dynatrace |
| Requires Docker | Yes | No |
| Requires Dynatrace config | No | Yes (one-time) |

### API token scopes required
- `openTelemetryTrace.ingest`

### Setup

```bash
pip install -r requirements_openinference.txt
```

---

### Option A — OTel Collector (Docker)

Start the Dynatrace OTel Collector with the provided config. It listens on port 4318, applies the transform, and forwards normalized spans to Dynatrace.

```bash
source .env  # or export DT_ENDPOINT and DT_API_TOKEN manually

docker run -d --name otel-collector -p 4318:4318 \
  -v $(pwd)/otel-collector-config.yaml:/etc/otelcol/otel-collector-config.yaml:ro \
  -e DT_ENDPOINT=$DT_ENDPOINT \
  -e DT_API_TOKEN=$DT_API_TOKEN \
  ghcr.io/dynatrace/dynatrace-otel-collector/dynatrace-otel-collector:latest \
  --config=/etc/otelcol/otel-collector-config.yaml

# Tail collector logs to confirm it's running
docker logs -f otel-collector
```

Run the app, pointing it at the local Collector (no Dynatrace credentials needed in the app):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python app_openinference.py
```

Stop the Collector when done:

```bash
docker stop otel-collector && docker rm otel-collector
```

---

### Option B — OpenPipeline (no Docker)

One-time setup in Dynatrace:

1. In Dynatrace, press `Ctrl+K` → search **OpenPipeline** → select **Spans**
2. Click **Add pipeline** → name it `openinference-ai-spans`
3. Add processors matching the attribute mappings in `otel-collector-config.yaml` (the same transforms, expressed as OpenPipeline DPL rules)
4. Go to the **Routing** tab → Add entry:
   - **Matcher:** `isNotNull(openinference.span.kind)`
   - **Pipeline:** `openinference-ai-spans`

Run the app directly against Dynatrace:

```bash
source .env
OTEL_EXPORTER_OTLP_ENDPOINT=$DT_ENDPOINT/api/v2/otlp python app_openinference.py
```

---

### Validate in Dynatrace (both options)
- **AI Observability → Explorer**: service `dt-ai-obs-openinference` appears after the first run
- **Distributed Tracing**: find spans for `dt-ai-obs-openinference` — verify `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` are present (these are the normalized attributes)
- Also check `ai.observability.source = openinference` is set on spans — this confirms normalization ran
- **Before normalization** (raw): spans carry `llm.model_name`, `llm.token_count.prompt`, `llm.token_count.completion`
- **After normalization**: those become `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`

---

## What to compare across all three

Once all three are running and sending data, compare in Dynatrace:

- **Span structure**: OneAgent wraps under an HTTP span; OpenLLMetry creates workflow/task hierarchy; OpenInference creates flat LLM spans
- **Attribute coverage**: all three should surface `gen_ai.request.model` and token counts; prompt capture requires explicit enablement (OneAgent feature flag or OpenInference `input.value`/`output.value`)
- **Metrics**: OpenLLMetry emits `gen_ai.*` metrics (request count, token counts) as OTLP metrics; OneAgent and OpenInference send trace-derived metrics
- **Setup friction**: OneAgent = zero code changes; OpenLLMetry = ~10 lines + decorators; OpenInference = ~20 lines + normalization step

## Reference

- [OneAgent docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/oneagent)
- [OpenLLMetry docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openllmetry)
- [OpenInference docs](https://docs.dynatrace.com/docs/observe/dynatrace-for-ai-observability/get-started/openinference)
- [Dynatrace sample apps repo](https://github.com/dynatrace-oss/dynatrace-ai-agent-instrumentation-examples)
>>>>>>> 92f7fb6 (Initial commit: DT AI Observability instrumentation test apps)
