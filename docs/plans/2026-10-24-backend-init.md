# Backend Init Implementation Plan

> **For agentic workers:** Executed inline (executing-plans style) on 2026-10-24. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize the resumecraft Python backend: FastAPI + LangChain (OpenAI-compatible) + Celery worker + SQLAlchemy async against Supabase Postgres, with one example feature (resume generation job) proving the full stack.

**Architecture:** Single shared package (`src/resumecraft/`) with two entrypoints — FastAPI app (`main.py`) and Celery worker (`core/celery_app.py`). Layering enforced by import-linter: `api → services → db`, `ai` isolated, `worker` never imports `api`. API enqueues Celery tasks by frozen name string; worker correlates via `Job.celery_task_id`.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLAlchemy[asyncio] + asyncpg + Alembic, Celery[redis], LangChain + langchain-openai, pydantic-settings, structlog, PyJWT, ruff/mypy/import-linter/pytest.

**Spec:** `docs/plans/2026-10-24-backend-init-design.md`

## Global Constraints

- Env prefix `RC_`; all Settings fields have defaults so the package imports with no `.env`.
- DB DSN built from components (never URL-parse passwords); `database_url` property.
- Celery task names frozen: `resumecraft.worker.tasks.<x>`; all tasks re-exported from `worker/tasks/__init__.py`.
- Services own DB commits; repositories only flush.
- Only `services/` call the LLM.
- JSON columns use `JSON().with_variant(JSONB(), "postgresql")` so tests run on aiosqlite.
- Tests: default addopts exclude markers `llm`, `network`, `db`.
- Each task ends with `make format lint typecheck imports test` green + commit.

## Tasks

### Task 1: Project scaffolding & toolchain
Files: `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, `Makefile`, `docker-compose.yml`, `src/resumecraft/__init__.py`, `tests/test_smoke.py`.
Verify: `uv sync`, `make lint`, `make typecheck`, `make imports`, `make test` green on empty package.
Commit: `chore: project scaffolding and toolchain`

### Task 2: Core config + logging
Files: `src/resumecraft/core/{__init__,config,logging}.py`, `tests/test_config.py`.
Interfaces: `Settings` (RC_ prefix; DB components + `database_url` property; redis/celery/openai/supabase fields), `get_settings()` (lru_cache), `configure_logging(settings)`.
Verify: unit tests for defaults, env overrides, DSN quoting of special-char passwords.
Commit: `feat(core): settings and logging`

### Task 3: DB foundation
Files: `core/enums.py` (JobStatus, JobType), `db/base.py` (Base, JSONVariant, TimestampMixin), `db/session.py` (init_engine/get_session/dispose_engine), `db/models/{__init__,job,resume}.py`, `alembic.ini`, `alembic/env.py` (async), `alembic/script.py.mako`, `alembic/versions/0001_init_schema.py` (hand-written), `tests/test_models.py`, `tests/test_migrations.py` (db marker).
Verify: model metadata tests; `make up && make migrate` against compose postgres; db-marked connect test.
Commit: `feat(db): models, async session, alembic migrations`

### Task 4: JWT auth core
Files: `schemas/{__init__,auth}.py` (CurrentUser), `core/security.py` (decode_supabase_token, AuthConfigError), `tests/test_security.py`.
Verify: HS256 decode of Supabase-style token (`sub` → UUID); rejects expired/wrong secret; raises AuthConfigError when unconfigured; JWKS branch present for prod.
Commit: `feat(core): supabase jwt token validation`

### Task 5: FastAPI app shell
Files: `main.py` (create_app + lifespan), `api/deps.py` (DbSession, SettingsDep, get_current_user, CurrentUserDep), `api/v1/{router,health}.py`, `tests/test_health.py`.
Verify: `GET /api/v1/health` 200 without DB; lifespan pre-ping warns (not crashes) when DB down; auth dep raises 401 without token.
Commit: `feat(api): fastapi app shell with health endpoints`

### Task 6: LLM client + schemas + prompts
Files: `ai/llm/client.py` (get_chat_model), `prompts/resume.py` (GENERATE_RESUME_PROMPT), `schemas/resume.py` (GenerateResumeRequest, GeneratedResume), `schemas/job.py` (JobAcceptedResponse, JobResponse), `tests/test_llm_client.py`, `tests/test_schemas.py`.
Verify: get_chat_model builds ChatOpenAI from settings and raises without key; request validation (min_length); prompt formats cleanly.
Commit: `feat(ai): langchain client, schemas, prompts`

### Task 7: Job repository + service
Files: `db/repositories/{__init__,job}.py`, `services/{__init__,job_service}.py`, `tests/conftest.py` (settings cache clearer, aiosqlite db_session), `tests/test_job_service.py`.
Verify: create/fetch/owner-scope/attach_task_id against aiosqlite.
Commit: `feat(db): job repository and service`

### Task 8: Resume repository + service
Files: `db/repositories/resume.py`, `services/resume_service.py` (generate with structured output + progress callback), `tests/test_resume_service.py` (LLM mocked).
Verify: generate persists Resume row, calls progress at 0.2/0.7/1.0, returns GeneratedResume.
Commit: `feat(services): resume generation service`

### Task 9: Celery worker
Files: `core/celery_config.py`, `core/celery_app.py` (create_celery, celery_app), `worker/tasks/{__init__,_runner,generate_resume}.py`, `tests/test_celery_config.py`, `tests/test_runner.py` (aiosqlite session_factory).
Interfaces: `run_job_flow(session_factory, job_id, work)`, `run_job_task(job_id, work)`, `WorkFn = Callable[[AsyncSession, Job, ProgressFn], Awaitable[dict]]`.
Verify: flow completes/marks FAILED/marks timeout on SoftTimeLimitExceeded/raises JobNotFoundError; task registered under frozen name.
Commit: `feat(worker): celery app, job runner, generate_resume task`

### Task 10: API endpoints
Files: `api/v1/{resumes,jobs}.py`, wire into `api/v1/router.py`, conftest `client` fixture (session + auth overrides, send_task monkeypatched), `tests/test_api_resumes.py`, `tests/test_api_jobs.py`.
Verify: POST /resumes/generate → 202 + job row with celery_task_id; 422 on bad input; 401 without token; GET /jobs/{id} owner-scoped (200/404).
Commit: `feat(api): resume generation and job polling endpoints`

### Task 11: CLAUDE.md + final verification
Files: `CLAUDE.md`.
Verify: full gate green; `make up && make migrate` works end-to-end against compose; docs committed.
Commit: `docs: claude.md conventions`
