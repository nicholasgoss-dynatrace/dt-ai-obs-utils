# Instrumentation Deep Dive — OneAgent vs OpenLLMetry vs OpenInference

This document explains how each instrumentation method works, what code it requires, what trace structure it produces, and how data reaches Dynatrace AI Observability. All examples are drawn from the three apps in this repository.

---

## Comparison at a Glance

| Dimension | OneAgent | OpenLLMetry | OpenInference |
|---|---|---|---|
| **Mechanism** | ptrace injection from host | SDK import + decorator | SDK import + OTel setup |
| **App code changes** | None | ~10 lines | ~20 lines |
| **Trace hierarchy** | HTTP span → LLM child span | workflow → task → LLM | Flat LLM span |
| **Attribute convention** | `gen_ai.*` (native) | `gen_ai.*` (native) | OpenInference → normalized to `gen_ai.*` |
| **Normalization needed** | No | No | Yes (OTel Collector or OpenPipeline) |
| **Prompt/response content** | Feature flag opt-in | `TRACELOOP_TRACE_CONTENT=true` | Captured by default |
| **Provider agnostic** | Yes (via feature flags) | Yes (auto-detects SDK) | Yes (conditional instrumentor) |
| **Data path to Dynatrace** | OneAgent daemon | OTLP direct | OTLP → OTel Collector → Dynatrace |

---

## OneAgent

### How it works

OneAgent instruments the Python process entirely from outside the application. When a new Python process is detected (via `/proc` scanning), the host OneAgent daemon:

1. Matches the process against injection rules (rule `-41` matches any container with a name)
2. Uses `ptrace` to attach to the process
3. Calls `dlopen` inside the process to load `liboneagentpython.so` — the Python sensor
4. The sensor hooks into Python internals, patching the Anthropic (or OpenAI) SDK at the C extension level
5. Each LLM call generates a child span under the active HTTP entry span

The application code is entirely unmodified. OneAgent provides the HTTP entry span (via the FastAPI sensor) and the LLM child span (via the Anthropic or OpenAI sensor) automatically.

### Application code

```python
# app_oneagent.py — no instrumentation code whatsoever
import llm_client

app = FastAPI(title="DT AI Obs — OneAgent test")
client = llm_client.create_client()
MODEL = llm_client.default_model()

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    resp = llm_client.call_llm(client, MODEL, req.prompt)   # ← OneAgent intercepts here
    return AskResponse(result=resp.content, model=resp.model, ...)
```

No imports, no init calls, no decorators. The instrumentation is invisible to the developer.

### Required setup (outside the app)

```
Settings → Collect and capture → General monitoring settings → OneAgent features
  ✅ Python Anthropic  (experimental — required for Anthropic)
  ✅ Python OpenAI     (experimental — required for OpenAI)
  ✅ Python FastAPI    (required — creates the HTTP parent span)

Settings → Infrastructure monitoring → Container monitoring
  ✅ Podman            (required if running in rootless Podman containers)
```

### Injection flow

```
Host OneAgent daemon
  │
  ├── /proc scan detects new uvicorn PID
  ├── checks injection rules → rule -41 matches (CONTAINER_NAME present)
  ├── ptrace attach to PID
  ├── dlopen("/opt/dynatrace/oneagent/agent/bin/.../liboneagentpython.so")
  └── Python sensor active — SDK calls now generate gen_ai.* spans
```

### Trace structure in Dynatrace

```
POST /ask  (FastAPI HTTP span — OneAgent FastAPI sensor)
└── anthropic.messages.create  (LLM span — OneAgent Anthropic sensor)
      gen_ai.system              = anthropic
      gen_ai.request.model       = claude-haiku-4-5-20251001
      gen_ai.usage.input_tokens  = 20
      gen_ai.usage.output_tokens = 225
      gen_ai.prompt              = "What is observability?"  (requires feature flag)
      gen_ai.completion          = "Observability is..."     (requires feature flag)
```

The HTTP span provides the entry point context. Without FastAPI sensor enabled, LLM spans have no parent and may not surface correctly in AI Observability Explorer.

---

## OpenLLMetry

### How it works

OpenLLMetry uses the `traceloop-sdk`, which wraps the OpenTelemetry SDK and auto-instruments LLM provider SDKs at import time. When `Traceloop.init()` is called, it:

1. Scans installed packages for supported LLM SDKs (Anthropic, OpenAI, etc.)
2. Patches the SDK clients using OpenTelemetry instrumentation hooks
3. Configures an OTLP exporter pointing to Dynatrace
4. Registers `@workflow` and `@task` decorators that create named spans in the trace hierarchy

Each LLM SDK call automatically generates a child span. The `@workflow` and `@task` decorators create structural parent spans that define the trace shape.

### Application code

```python
# app_openllmetry.py
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

# One-time init — auto-instruments all detected LLM SDKs
Traceloop.init(
    app_name=SERVICE_NAME,
    api_endpoint=f"{DT_ENDPOINT}/api/v2/otlp",
    headers={"Authorization": f"Api-Token {DT_API_TOKEN}"},
    disable_batch=True,
)

client = llm_client.create_client()

@task(name="call_llm")                      # ← named task span
def call_llm_task(prompt: str) -> dict:
    resp = llm_client.call_llm(client, MODEL, prompt)   # ← auto-instrumented
    return {"content": resp.content, ...}

@workflow(name="ask_question")              # ← top-level workflow span
def ask_question(prompt: str) -> dict:
    return call_llm_task(prompt)

@app.post("/ask")
def ask(req: AskRequest) -> AskResponse:
    result = ask_question(req.prompt)       # ← kicks off the workflow
    ...
```

Content capture is enabled via environment variable — no code change required:

```yaml
# docker-compose.yml
environment:
  - TRACELOOP_TRACE_CONTENT=true
```

### Trace structure in Dynatrace

```
ask_question  (workflow span — @workflow decorator)
└── call_llm  (task span — @task decorator)
    └── anthropic.chat  (LLM span — auto-instrumented by traceloop-sdk)
          gen_ai.system              = anthropic
          gen_ai.request.model       = claude-haiku-4-5-20251001
          gen_ai.usage.input_tokens  = 20
          gen_ai.usage.output_tokens = 225
          gen_ai.input.messages      = [{"role": "user", "parts": [...]}]
          gen_ai.output.messages     = [{"role": "assistant", "parts": [...]}]
```

The workflow → task → LLM hierarchy is the key differentiator. It mirrors how a real agent application would be structured: a named workflow (an agent run) containing tasks (reasoning steps) each of which may call an LLM one or more times.

### Data flow

```
app_openllmetry.py
  │  traceloop-sdk patches anthropic client at init
  │
  ├── @workflow span created on ask_question() call
  │   └── @task span created on call_llm_task() call
  │       └── LLM span created on client.messages.create()
  │
  └── BatchSpanProcessor → OTLP exporter
        → DT_ENDPOINT/api/v2/otlp  (direct, no collector needed)
        → Dynatrace Grail → AI Observability Explorer
```

---

## OpenInference

### How it works

OpenInference is an open standard for AI observability that defines its own span attribute conventions (`llm.model_name`, `llm.token_count.prompt`, `openinference.span.kind`, etc.). The `openinference-instrumentation-*` packages wrap LLM SDK clients using standard OpenTelemetry hooks.

Because OpenInference uses different attribute names than Dynatrace AI Observability expects (`gen_ai.*`), a **normalization layer** is required. This repo includes an OTel Collector configured to transform the attributes before forwarding to Dynatrace.

### Application code

```python
# app_openinference.py
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

# Full OTel SDK setup (TracerProvider, exporter, processor)
tracer_provider = TracerProvider(resource=Resource.create({SERVICE_NAME: SERVICE}))
exporter = OTLPSpanExporter(endpoint=otlp_endpoint, headers={...})
tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

# Provider-conditional instrumentor — patches the SDK client automatically
if llm_client.PROVIDER == "anthropic":
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
elif llm_client.PROVIDER == "openai":
    from openinference.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

client = llm_client.create_client()

@app.post("/ask")
def ask(req: AskRequest) -> AskResponse:
    resp = llm_client.call_llm(client, MODEL, req.prompt)   # ← auto-instrumented
    ...
```

More boilerplate than OpenLLMetry because you wire the full OTel SDK manually. The upside is full control over the exporter pipeline, resource attributes, and span processor configuration.

### Raw span attributes (before normalization)

```
messages.create  (span name — OpenInference convention)
  openinference.span.kind     = LLM
  llm.model_name              = claude-haiku-4-5-20251001
  llm.provider                = anthropic
  llm.token_count.prompt      = 20
  llm.token_count.completion  = 225
  llm.max_tokens              = 1024
  input.value                 = {"messages": [{"role": "user", "content": "..."}]}
  output.value                = {"id": "msg_...", "content": [...]}
```

### Normalization layer (OTel Collector)

The OTel Collector's `transform/openinference` processor maps OpenInference attributes to `gen_ai.*`:

```yaml
# otel-collector-config.yaml (excerpt)
processors:
  transform/openinference:
    trace_statements:
      - context: span
        statements:
          - set(attributes["gen_ai.operation.kind"], "chat")
              where attributes["openinference.span.kind"] == "LLM"
          - set(attributes["gen_ai.request.model"], attributes["llm.model_name"])
              where attributes["llm.model_name"] != nil
          - set(attributes["gen_ai.usage.input_tokens"],  attributes["llm.token_count.prompt"])
          - set(attributes["gen_ai.usage.output_tokens"], attributes["llm.token_count.completion"])
          - set(attributes["gen_ai.input.messages"],  attributes["input.value"])
          - set(attributes["gen_ai.output.messages"], attributes["output.value"])
          - set(attributes["ai.observability.source"], "openinference")
```

### Trace structure in Dynatrace (after normalization)

```
messages.create  (LLM span — flat, no workflow/task hierarchy)
  gen_ai.operation.kind      = chat                     ← normalized
  gen_ai.system              = anthropic                ← normalized
  gen_ai.request.model       = claude-haiku-4-5-20251001
  gen_ai.usage.input_tokens  = 20
  gen_ai.usage.output_tokens = 225
  gen_ai.input.messages      = {...}                    ← normalized from input.value
  gen_ai.output.messages     = {...}                    ← normalized from output.value
  ai.observability.source    = openinference            ← source tag for DQL filtering
```

Unlike OpenLLMetry, there is no workflow/task hierarchy unless you manually add parent spans using the OTel tracer API.

### Data flow

```
app_openinference.py
  │  AnthropicInstrumentor patches anthropic client at init
  │
  └── LLM span created on client.messages.create()
      (OpenInference attribute conventions: llm.model_name, llm.token_count.*, etc.)
        │
        └── BatchSpanProcessor → OTLPSpanExporter
              → http://otel-collector:4318  (OTel Collector)
                  │
                  ├── transform/openinference processor
                  │     maps llm.* → gen_ai.*, sets ai.observability.source
                  │
                  └── otlphttp exporter
                        → DT_ENDPOINT/api/v2/otlp
                        → Dynatrace Grail → AI Observability Explorer
```

**Alternative — OpenPipeline (no Collector):** Set `OTEL_EXPORTER_OTLP_ENDPOINT=$DT_ENDPOINT/api/v2/otlp` and configure the same attribute mappings as a Dynatrace OpenPipeline rule on the server side.

---

## Attribute Convention Comparison

The same LLM call concept expressed in each convention:

| Concept | OneAgent | OpenLLMetry | OpenInference (raw) | After normalization |
|---|---|---|---|---|
| Model name | `gen_ai.request.model` | `gen_ai.request.model` | `llm.model_name` | `gen_ai.request.model` |
| Input tokens | `gen_ai.usage.input_tokens` | `gen_ai.usage.input_tokens` | `llm.token_count.prompt` | `gen_ai.usage.input_tokens` |
| Output tokens | `gen_ai.usage.output_tokens` | `gen_ai.usage.output_tokens` | `llm.token_count.completion` | `gen_ai.usage.output_tokens` |
| Prompt content | `gen_ai.prompt` | `gen_ai.input.messages` | `input.value` | `gen_ai.input.messages` |
| Response content | `gen_ai.completion` | `gen_ai.output.messages` | `output.value` | `gen_ai.output.messages` |
| Span kind | *(inferred)* | `gen_ai.operation.kind` | `openinference.span.kind` | `gen_ai.operation.kind` |
| Provider | `gen_ai.system` | `gen_ai.system` | `llm.provider` / `llm.system` | `gen_ai.system` |

---

## DQL Filtering by Source

Because all three methods ultimately produce `gen_ai.*` spans in Grail, you can query them together or separately:

```dql
-- All LLM spans across all three methods
fetch spans, from: now()-1h
| filter isNotNull(gen_ai.request.model)
| summarize count(), by: {service.name, gen_ai.request.model}

-- OpenInference only (source tag set by OTel Collector)
fetch spans, from: now()-1h
| filter attributes["ai.observability.source"] == "openinference"

-- OneAgent only (no OTLP service name — filter by process entity or service)
fetch spans, from: now()-1h
| filter isNotNull(gen_ai.request.model)
| filter not(isNotNull(attributes["ai.observability.source"]))
| filter service.name != "dt-ai-obs-openllmetry"
```

---

## When to Use Each

**OneAgent** — when you own the host/container platform and cannot or do not want to modify application code. Best for brownfield deployments: drop OneAgent on the host, enable the feature flags, done. No SDK dependency, no deployment change.

**OpenLLMetry** — when you want a structured trace hierarchy out of the box (`workflow → task → LLM`) and direct OTLP export with minimal code. Best when building or refactoring an AI agent where you control the codebase and want named workflows to appear in AI Observability.

**OpenInference** — when you are already using or want to use the OpenInference standard (common in the Python AI/ML ecosystem, e.g., with LlamaIndex, DSPy, Arize Phoenix). Requires more setup than OpenLLMetry and a normalization layer for Dynatrace, but gives you interoperability with the broader OpenInference tooling ecosystem.
