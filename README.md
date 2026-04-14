# LoopLM

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Node](https://img.shields.io/badge/node-20%2B-339933)](https://nodejs.org)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB)](https://www.python.org)

**LLM debugging and evaluation platform** for self-hosted teams. LoopLM connects to your existing observability stack, imports traces and prompts, runs evaluations, and helps you move from failures to concrete fixes.

## What It Does

- Browse traces, spans, and threads from platforms such as Langfuse and LangSmith
- Detect failures and inspect root causes
- Run evaluations against datasets and compare runs over time
- Manage evaluators, prompts, feedback, and experiments
- Generate fix suggestions and code-analysis follow-ups

## Architecture

```text
LangSmith / Langfuse / other sources
                |
                v
      Python connector layer
                |
                v
 FastAPI API + PostgreSQL + Redis + MinIO
                |
                v
        Next.js frontend
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 20+
- pnpm 9+
- Python 3.12+
- Poetry

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Services:

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- MinIO console: `http://localhost:9001`

### Local Development

1. Install workspace dependencies:

```bash
pnpm install
cd apps/api
poetry install --with dev
cd ../..
```

2. Copy the example environment and adjust values as needed:

```bash
cp .env.example .env
```

3. Start local infrastructure:

```bash
make infra
```

4. Run the API and web app in separate terminals:

```bash
make api
make web
```

Local URLs:

- Frontend: `http://localhost:3100`
- API: `http://localhost:8000`

Stop everything with:

```bash
make stop
```

### Manual Start

Backend:

```bash
cd apps/api
poetry install --with dev
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
pnpm install
cd apps/web
pnpm dev
```

## Configuration

Copy `.env.example` to `.env`. The most important settings are:

- `API_SECRET_KEY`: required outside debug mode
- `DATABASE_URL`, `REDIS_URL`: backend infrastructure
- `NEXT_PUBLIC_API_URL`: frontend API origin
- `ANALYSIS_LLM_PROVIDER`: `openai` or `azure_openai`
- `OPENAI_API_KEY` or `AZURE_OPENAI_*`: analysis/evaluator provider credentials
- `LANGFUSE_*`, `LANGSMITH_API_KEY`, `LANGCHAIN_*`: connector credentials
- `EVAL_TARGET_ENDPOINT`: target application endpoint for running evals

Optional frontend metadata:

- `NEXT_PUBLIC_REPOSITORY_URL`: public repository link shown on the landing page

## Development Notes

- `make api` uses `poetry run uvicorn`
- `make web` starts the Next.js app on port `3100`
- Alembic is available under `apps/api/alembic`
- The app still accepts legacy eval and dataset import formats for backwards compatibility

## Quality Checks

From the repo root:

```bash
pnpm lint
pnpm typecheck
pnpm build
```

For the API:

```bash
cd apps/api
poetry run ruff check .
poetry run pytest
```

## Project Structure

```text
apps/
  api/         FastAPI backend
  web/         Next.js frontend
connectors/    Provider connectors
packages/      Shared TypeScript packages
infra/         Dockerfiles and OpenTofu modules
scripts/       Seed and smoke-test helpers
```

## Open Source Notes

- The repo is intended for self-hosting today
- Legacy import compatibility is preserved, but new defaults are product-agnostic
- Secrets are not committed; use `.env.example` as the starting point for local setup

## License

MIT

## Contributing

See `CONTRIBUTING.md`.

## Security

Report security issues to `timtreskatis@gmail.com` or see `SECURITY.md`.
