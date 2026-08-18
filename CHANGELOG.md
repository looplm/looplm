# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Cross-tenant member management (critical).** `/api/projects/{project_id}/members` authorized
  against the `X-Project-Id` header while querying by the path parameter, so an owner or admin of
  any project could list, invite, modify and delete the members of any other project - including
  granting themselves admin. Every route in that router now resolves the project from the path
  via the new `get_path_project` / `require_path_project_admin` dependencies.
- **Read-only invitations no longer confer write access.** Accepting an invitation dropped
  `write_pages`, which landed `NULL`, and `require_write` treated `NULL` as legacy full write.
  The field is now carried over and `NULL` fails closed.
- **Refresh tokens are no longer accepted as access tokens.** `get_current_user` did not check
  the `type` claim, so a refresh token (and the GitHub OAuth state token, signed with the same
  key) authenticated every endpoint. A validly signed token with a malformed `sub` now returns
  401 instead of 500.
- **Refresh tokens rotate and can be revoked.** Refreshing consumes the presented token and
  issues a successor; replaying a consumed token revokes the whole rotation family. Added
  `POST /api/auth/logout`. Refresh lifetime is 2 days, down from 7.
- **Advisor endpoints are project-scoped.** `GET /api/advisor/{integration_id}/suggestions` and
  its siblings accepted any integration id, exposing another tenant's architecture analysis and
  writing analysis rows against integrations the caller did not own.
- **GitHub installation ids are bound to the project.** `/api/github/installations/{id}/repos`
  and `/branches` minted an installation token for any caller-supplied id, which with a shared
  instance-wide App exposed other tenants' private repositories. They now require the
  installation to be linked to the project or a short-lived grant issued by `/callback`.
  `POST`/`DELETE /api/github/installation`, `/auth-url` and `/callback` now require project admin.
- **Docker Compose no longer publishes the data plane.** Postgres, Redis and the API were bound
  to `0.0.0.0` with `looplm`/`looplm` and `looplm123`, and Docker's port publishing bypasses
  `ufw`/`firewalld`. All ports are now bound to `127.0.0.1`, passwords are required with no
  defaults, and Redis runs with `--requirepass`.
- **The default-secret startup guard is unconditional.** `DEBUG=true` used to bypass it, which
  made enabling debug, and with it traceback disclosure and SQL echo, the quickest way to
  silence the error.
- `/docs`, `/redoc` and `/openapi.json` are off unless `DOCS_ENABLED=true` (or `DEBUG=true`).
- The unused MinIO service was removed; no code has ever read `MINIO_*`.

### Upgrading

| Change | Action required |
| --- | --- |
| Startup guard now applies in debug too | Run `make secrets` and set `API_SECRET_KEY` |
| Replacing an existing `API_SECRET_KEY` | Set `ENCRYPTION_SECRET` to the **old** value, or stored integration credentials become undecryptable |
| Compose requires `POSTGRES_PASSWORD` and `REDIS_PASSWORD` | Add both to `.env`. An existing `postgres_data` volume keeps the password it was created with, so use that value or recreate the volume. Update `REDIS_URL` to `redis://:<password>@…` |
| Ports bound to loopback | Use `docker-compose.override.yml.example` for direct host access in development |
| API port no longer published | Reach the API through the web container's `/api/*` proxy |
| MinIO removed | None. The `minio_data` volume can be pruned |
| `/docs` off by default | Set `DOCS_ENABLED=true` to restore |
| Refresh tokens rotate | Clients must store the refresh token returned by each `/api/auth/refresh`; the old one is dead |
| Sessions issued before the upgrade | Refresh tokens minted before `refresh_sessions` existed have no session row and are rejected, so everyone signs in once after deploying |
| `write_pages` NULL now means read-only | Run `alembic upgrade head` - migration `092` materialises existing NULLs so nobody loses access |
| GitHub reconnect flow | Pass the `grant` from `/api/github/callback` to the installation lookups (the bundled web app already does) |

Migrations: `092` (backfill `write_pages`), `093` (add `refresh_sessions`).

## [0.1.0] - 2026-04-14

### Added

- Trace browser for inspecting spans, threads, and root causes from Langfuse and LangSmith
- Failure detection and root-cause analysis powered by LLM
- Evaluation runner with dataset management and run comparison
- Evaluator, prompt, and feedback management UI
- Fix suggestions and code-analysis follow-ups
- Batch evaluation mode via Azure OpenAI Batch API
- Top Questions analysis with PDF export
- Docker Compose setup for self-hosting (PostgreSQL, Redis, MinIO)
- OpenTofu modules for AWS, Azure, and GCP deployment
- CI pipeline with lint, typecheck, build, and Docker checks

[0.1.0]: https://github.com/looplm/looplm/releases/tag/v0.1.0
