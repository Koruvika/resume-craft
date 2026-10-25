.PHONY: dev worker test lint format typecheck imports migrate revision up down

dev:
	uv run uvicorn resumecraft.main:app --reload

worker:
	uv run celery -A resumecraft.core.celery_app worker --loglevel=info

test:
	uv run pytest

lint:
	uv run ruff format --check . && uv run ruff check .

format:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy

imports:
	uv run lint-imports

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d

down:
	docker compose down
