COMPOSE ?= docker compose

.PHONY: up down logs test lint fmt

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api

test:
	cd backend && .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
