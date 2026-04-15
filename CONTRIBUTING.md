# Contributing to LoopLM

Thanks for contributing. This project is a monorepo with a FastAPI backend and a Next.js frontend.

## Getting Set Up

Follow the Quick Start in `README.md` for prerequisites and local dev.

## Monorepo Notes

The API depends on local connectors via a path dependency in `apps/api/pyproject.toml`:

- `looplm-connectors = { path = "../../connectors", develop = true }`

If you extract the API into a standalone repo, replace this with a published package or a relative path in your fork.

## Branches and PRs

- Branch from `main` and keep PRs focused.
- Link issues where possible.
- Include tests or a clear explanation when tests are not applicable.

## Commit Message Style

Prefer Conventional Commits:

- `feat: add langsmith sync retries`
- `fix: handle empty trace spans`
- `docs: update architecture overview`
- `chore: bump deps`

## Tests, Lint, Typecheck

From the repo root:

- `pnpm lint`
- `pnpm typecheck`
- `pnpm build`

API tests:

- `cd apps/api`
- `poetry install --with dev`
- `poetry run ruff check .`
- `poetry run pytest`

## Adding a Connector

High-level steps:

- Create `connectors/<provider>/connector.py` implementing `BaseConnector` in `connectors/base.py`.
- Add a new enum value in `apps/api/app/models/base.py` under `IntegrationType`.
- Wire the connector in `apps/api/app/services/sync_service.py` and anywhere else a connector is selected.
- Update the integration UI in `apps/web/src/components/integrations-panel.tsx`.
- Add tests under `connectors/<provider>/tests` or `apps/api/tests`.
