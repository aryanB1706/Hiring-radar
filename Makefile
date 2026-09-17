COMPOSE ?= docker compose

.PHONY: up down logs db-up redis-up migrate test lint fmt

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api

db-up:
	$(COMPOSE) up -d postgres

redis-up:
	$(COMPOSE) up -d redis

migrate:
	cd backend && .venv/bin/alembic upgrade head

test:
	cd backend && .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
