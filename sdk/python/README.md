# LoopLM Python SDK

Push LLM traces to your LoopLM instance directly from your app — no Langfuse or
LangSmith required.

## Install

```bash
pip install looplm
# or, from this repo:
pip install -e sdk/python
```

## Quickstart

1. In LoopLM, create a **LoopLM Tracing** integration and mint an **ingest key**
   (Settings → Integrations). Copy the key — it's shown only once.
2. Instrument your code:

```python
from looplm import LoopLM

client = LoopLM(api_key="llm_sk_...", base_url="https://your-looplm-host")

with client.trace("chat", input={"question": "What is LoopLM?"}, user_id="u-1") as t:
    with t.span("llm", name="answer", model="gpt-4o") as s:
        # ... your model call ...
        s.set_tokens(input=120, output=80)
        s.set_output({"answer": "An LLM debugging platform."})

    with t.span("tool", name="search") as s:   # nested spans build the tree
        s.set_output({"hits": 3})

    t.set_output({"answer": "An LLM debugging platform."})
```

Traces are buffered and flushed in the background; nothing blocks your request
path, and delivery failures are logged rather than raised. Call
`client.flush()` to force delivery (e.g. in short scripts) — it also runs
automatically at process exit.

## Concepts

- **Trace** — one end-to-end execution. Sent as a single payload when the
  `with` block exits.
- **Span** — a step inside a trace (`llm`, `tool`, `retriever`, `chain`,
  `agent`). Nesting `with t.span(...)` blocks sets the parent automatically.
- **Status** — a trace/span that exits with an exception is recorded as failed.

## Decorator

```python
@client.trace_fn("handle_request", run_type="endpoint")
def handle_request(payload):
    ...
```
