.PHONY: up down build logs migrate seed dev help

# Start the full stack (DB + API) via Docker Compose
up:
	docker compose up --build -d
	@echo "API running at http://localhost:8000"

# Stop and remove containers
down:
	docker compose down

# Rebuild images without starting
build:
	docker compose build

# Follow logs for all services (or a specific one: make logs s=api)
logs:
	docker compose logs -f $(s)

# Run pending Alembic migrations inside the running API container
migrate:
	docker compose exec api uv run alembic upgrade head

# Seed the first admin user (requires ADMIN_PASSWORD in .env)
seed:
	docker compose exec api uv run python scripts/seed_admin.py

# Local dev mode: DB in Docker, API via uv (hot-reload)
dev:
	docker compose up db -d
	cd backend && uv run uvicorn app.main:app --reload

help:
	@echo ""
	@echo "  make up       — build and start the full stack"
	@echo "  make down     — stop containers"
	@echo "  make build    — rebuild images"
	@echo "  make logs     — follow all logs  (make logs s=api for one service)"
	@echo "  make migrate  — run Alembic migrations"
	@echo "  make seed     — seed the first admin user"
	@echo "  make dev      — DB in Docker + API with hot-reload"
	@echo ""
