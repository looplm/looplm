# Langfuse Connector

Pulls traces from a [Langfuse](https://langfuse.com) instance (cloud or self-hosted) and normalizes them into LoopLM's unified trace schema.

## How it works

1. **Authentication** — Uses Langfuse's Basic Auth (`public_key` as username, `secret_key` as password) against the `/api/public/` REST API.
2. **Trace listing** — `GET /api/public/traces` with `fromTimestamp` for incremental sync and `orderBy=timestamp.asc` to resume from where we left off.
3. **Trace detail** — `GET /api/public/traces/{traceId}` returns the full trace including observations (spans/generations/events) and scores.
4. **Normalization** — Each Langfuse trace and its observations are mapped to `NormalizedTrace` / `NormalizedSpan` Pydantic models. Status is inferred from observation levels (`ERROR` → failure, `WARNING` → degraded, else success).
5. **Sync** — `sync(since)` orchestrates the full flow: fetch trace list → fetch details → normalize → return.

## Quick start

```python
from datetime import datetime, timezone
from connectors.langfuse import LangfuseConnector, LangfuseConfig

config = LangfuseConfig(
    base_url="https://cloud.langfuse.com",
    public_key="pk-lf-...",
    secret_key="sk-lf-...",
)

async with LangfuseConnector(config=config) as connector:
    # Verify credentials
    await connector.test_connection()

    # Pull & normalize traces from the last 24 hours
    since = datetime(2025, 1, 14, tzinfo=timezone.utc)
    traces = await connector.sync(since)

    for trace in traces:
        print(f"{trace.id} — {trace.status} — {len(trace.spans)} spans")
```

## Configuration

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `base_url` | No | `https://cloud.langfuse.com` | Langfuse instance URL |
| `public_key` | Yes | — | API public key (Basic Auth username) |
| `secret_key` | Yes | — | API secret key (Basic Auth password) |

## Models

- **`LangfuseConfig`** — Connection settings (Pydantic).
- **`NormalizedTrace`** — Unified trace: id, name, input/output, status, spans, metadata, tags, timestamps, latency, cost.
- **`NormalizedSpan`** — Single observation: id, parent_id, name, type, model, tokens, duration, status.

## Error handling

- HTTP retries (3 attempts) via `httpx.AsyncHTTPTransport`.
- Failed detail fetches during `sync()` are logged and skipped — partial results are returned.
- All HTTP errors surface as `httpx.HTTPStatusError`.

## Running tests

```bash
cd apps/api
poetry install --with dev
poetry run pytest ../../connectors/langfuse/tests/ -v
```
