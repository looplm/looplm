.PHONY: dev infra web api stop stop-infra logs

# Start everything: infra in Docker + web and api locally with hot reload
dev: infra web api

# Start only Docker services (postgres, redis, minio)
infra:
	docker compose up -d postgres redis minio
	@echo "Waiting for postgres..."
	@until docker compose exec postgres pg_isready -U looplm > /dev/null 2>&1; do sleep 0.5; done
	@echo "Waiting for redis..."
	@until docker compose exec redis redis-cli ping > /dev/null 2>&1; do sleep 0.5; done
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
	docker compose logs -f postgres redis minio
