.PHONY: dev infra web api stop stop-infra logs secrets release-patch release-minor release-major

# Start everything: infra in Docker + web and api locally with hot reload
dev: infra web api

# Print a ready-to-paste secret block for .env (run before the first boot)
secrets:
	@python3 -c 'import secrets; \
print("API_SECRET_KEY=" + secrets.token_urlsafe(48)); \
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24)); \
print("REDIS_PASSWORD=" + secrets.token_urlsafe(24))'
	@echo "# Replacing an existing API_SECRET_KEY? Set ENCRYPTION_SECRET to the old value."

# Start only Docker services (postgres, redis)
infra:
	docker compose up -d postgres redis
	@echo "Waiting for postgres..."
	@until docker compose exec postgres pg_isready -U $${POSTGRES_USER:-looplm} > /dev/null 2>&1; do sleep 0.5; done
	@echo "Waiting for redis..."
	@until docker compose exec redis sh -c 'redis-cli -a "$$REDIS_PASSWORD" ping' > /dev/null 2>&1; do sleep 0.5; done
	@echo "Infrastructure ready."

# Start Next.js dev server (hot reload)
web:
	@-lsof -ti:3100 | xargs kill -9 2>/dev/null || true
	pnpm dev:web &

# Start FastAPI dev server (hot reload)
api:
	@-lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	cd apps/api && poetry run uvicorn app.main:app --reload --port 8000 &

# Stop everything
stop: stop-infra
	@-pkill -f "next dev" 2>/dev/null || true
	@-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@echo "All processes stopped."

# Stop only Docker services
stop-infra:
	docker compose down

# Tail logs from Docker services
logs:
	docker compose logs -f postgres redis

# Cut a release (bump manifests, tag, push — triggers Docker Hub publish)
release-patch:
	@bash scripts/release.sh patch

release-minor:
	@bash scripts/release.sh minor

release-major:
	@bash scripts/release.sh major
