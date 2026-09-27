COMPOSE ?= docker compose
VENV_BIN ?= $(CURDIR)/backend/.venv/bin
PYTHON ?= $(VENV_BIN)/python
PYTEST ?= $(VENV_BIN)/pytest
RUFF ?= $(VENV_BIN)/ruff

.PHONY: help up down logs test lint fmt

help:
	@echo "Available commands:"
	@echo "  make up       - Start all containers in the background"
	@echo "  make down     - Stop and remove all containers"
	@echo "  make logs     - Follow logs from running containers"
	@echo "  make test     - Run backend tests with pytest"
	@echo "  make lint     - Run code quality checks (ruff check and format check)"
	@echo "  make fmt      - Format and fix code with ruff"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:
	cd backend && $(PYTEST)

lint:
	$(RUFF) check backend
	$(RUFF) format --check backend

fmt:
	$(RUFF) check --fix backend
	$(RUFF) format backend
