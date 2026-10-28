# CLAUDE.md

Backend for resumecraft: FastAPI API + Celery worker + LangChain LLM services,
backed by Postgres (SQLAlchemy async), with local JWT auth. Design spec and
plans live in `docs/plans/`.

## Commands

```bash
uv sync                       # install deps (Python 3.13, uv)
make up                       # start dev postgres (localhost:5434) + redis (6379)
make migrate                  # alembic upgrade head
make dev                      # run API:  uvicorn resumecraft.main:app --reload
make worker                  # run Celery worker
make test                     # pytest (llm/network/db markers excluded)
make lint                     # ruff format --check + ruff check
make format                   # ruff format + autofix
make typecheck                # mypy
make imports                  # import-linter (layering contracts)
make revision m="msg"         # alembic autogenerate revision
```

Quality gate before every commit: `make format lint typecheck imports test`.

## Architecture

Single shared package `src/resumecraft/` with two process entrypoints:

- **API**: `resumecraft.main:app` (uvicorn). Routes under `/api/v1`, app factory
  + lifespan (engine init/pre-ping, disposal).
- **Worker**: `resumecraft.core.celery_app:celery_app` (celery -A). Redis
  broker, single `default` queue.

Layering (enforced by import-linter in `pyproject.toml`):

```
api/v1  →  services  →  repositories  →  models
              ↓                        ai/llm, prompts  (isolated)
worker/tasks → services (thin shells, never import api)
```

Rules:
- `api` is the outermost layer — nothing imports it except `main.py`.
- `services/` own DB commits; repositories only flush.
- Only `services/` call the LLM (`ai/llm/client.py`, LangChain ChatOpenAI
  against any OpenAI-compatible endpoint).
- `rendering/` renders ParsedResume → PDF (rendercv + typst, in-process).
  Ported from resumebloom's `app.components.render` — keep conversions in sync.
  `services/render_service.py` owns the endpoint flow (validate options →
  load resume → convert → `generate_pdf_bytes` in a worker thread).
- `worker` never imports `api`.

## Auth

Local JWT auth (SSKF-AI pattern, simplified): `POST /auth/register` (bcrypt
password, 201 UserOut), `POST /auth/login` (HS256 TokenOut signed with
`RC_JWT_SECRET_KEY`), `GET /auth/me`. `core/security.py` owns hashing and token
create/decode; `api/deps.py::get_current_user` raises `AuthenticationError`
(401 via the central handler). Passwords:
bcrypt cost 12, 72-byte input limit enforced in the schema (422 over a 500).
Login failures share one message ("Incorrect email or password") and an unknown
email costs a decoy bcrypt verify so response time is not an oracle.

## Errors

Centralized: domain errors are raised anywhere, translated to
HTTP in exactly one place. Every error response has one shape:
`{"error": {"code": ..., "message": ..., "details": {...}}}`.

- `core/exceptions.py` — framework-free hierarchy (`ResumeCraftError` base with
  `code`/`status_code`/`message`/`details`, subclasses per condition, e.g.
  `NotFoundError("task", id)` → 404 `task_not_found`). Services and the worker
  raise these; they must not import FastAPI. `code` is a frozen client-facing
  contract — never rename one.
- `api/errors.py` — `register_exception_handlers` maps the hierarchy, FastAPI's
  `RequestValidationError`, Starlette `HTTPException` (routing 404/405), and
  unhandled crashes (generic 500, no internals leaked) onto the envelope.
  4xx logs a warning, 5xx logs a traceback; 401 always carries
  `WWW-Authenticate: Bearer`.
- Routers/deps raise domain errors only — no try/except-to-HTTPException
  mapping in endpoint code.

## Celery conventions

- Tasks are thin shells over services, wrapped in
  `worker/tasks/_runner.py::run_task` (fresh engine per task, Task row status
  lifecycle PENDING → RUNNING → COMPLETED/FAILED, progress callbacks,
  SoftTimeLimitExceeded recorded as timeout).
- Task names are a **frozen contract**: `resumecraft.worker.tasks.<x>`. Never
  rename existing tasks (in-flight messages + `send_task` calls reference them
  by string).
- Every task must be re-exported from `worker/tasks/__init__.py` or Celery
  won't register it.
- The API enqueues via `celery_app.send_task(<name>)` and stores the returned
  id on `Task.celery_task_id`.
- New task type: add `TaskType` member → schema → service → task (via
  `run_task`) → endpoint.

## Schema changes

1. Edit models in `src/resumecraft/db/models/`.
2. `make revision m="describe change"` (requires `make up` — autogenerate
   against dev postgres).
3. `make migrate`, verify.
4. Update `docs/database.dbml` to match — models and migrations are the source
   of truth; the dbml is only the diagram, but it must never drift from them.

Migrations are async (`alembic/env.py`); DSN comes from settings, never
hardcoded. JSON columns use `JSONVariant` (JSONB on Postgres, JSON on sqlite so
tests run on aiosqlite).

## Configuration

`core/config.py`, pydantic-settings, env prefix `RC_`, `.env` backed. See
`.env.example`. All fields have defaults — the package imports with no env.

- **Local dev**: docker compose postgres (host port 5434 — 5432/5433 are taken
  by system postgres) + redis.

## Testing

- pytest, `asyncio_mode=auto`. Default suite runs fully offline on in-memory
  sqlite (`db_session` fixture in `tests/conftest.py`).
- Markers: `db` (needs compose postgres + migrations), `llm` (real LLM call),
  `network`, `render` (real rendercv/typst pipeline). Excluded by default;
  run with `uv run pytest -m db`.
- LLM is always mocked in unit tests via `get_chat_model` monkeypatching;
  API tests override `get_session`/`get_current_user` dependencies and stub
  `send_task`.
