# resumecraft backend — initialization design

Date: 2026-10-24
Status: Approved (design review passed)

## Goal

Initialize a Python backend for resumecraft with:

- **FastAPI** HTTP API (structure reference: SSKF-AI `src/sskf`)
- **LangChain** LLM service layer (OpenAI-compatible)
- **Celery** background worker (structure reference: AI-Hodai `src/hodai`)
- **Supabase Postgres** via SQLAlchemy async (connection reference: resumebloom `backend`)

Scope: full skeleton wired end-to-end plus one example domain feature (resume
generation job) proving all pieces work together. Real domain features come later.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| DB access | SQLAlchemy async + Supabase Postgres (supavisor pooler in prod; local compose postgres in dev) — not supabase-py/PostgREST |
| LLM provider | LangChain `ChatOpenAI` against OpenAI-compatible endpoint (env-configurable `base_url` works with OpenAI, LiteLLM proxy, etc.) |
| Auth | Supabase JWT (HS256 local dev secret; RS256/JWKS-ready for prod) |
| Package layout | Single shared package, two entrypoints (API + worker), SSKF/Hodai pattern |
| Tooling | uv, Python 3.13, ruff + mypy + import-linter + pytest, Makefile |
| Local infra | docker-compose (postgres:16, redis:7) for dev; env-switch to Supabase/managed Redis for staging/prod |

## 1. Project layout

```
resumecraft/
├── pyproject.toml            # uv, hatchling, all quality-gate config
├── .python-version           # 3.13
├── .env.example
├── Makefile
├── alembic.ini
├── docker-compose.yml        # dev only: postgres, redis
├── alembic/                  # async env.py, versions/
├── docs/plans/               # dated design/plan docs (this file)
├── src/resumecraft/
│   ├── main.py               # FastAPI app factory + lifespan
│   ├── core/
│   │   ├── config.py         # pydantic-settings, lru_cache get_settings()
│   │   ├── logging.py        # structlog setup
│   │   ├── security.py       # Supabase JWT validation → CurrentUser
│   │   ├── enums.py          # JobType, JobStatus
│   │   ├── celery_app.py     # Celery("resumecraft", include=[...]) factory
│   │   └── celery_config.py  # broker/queue/retry/worker tuning from settings
│   ├── api/
│   │   ├── deps.py           # Annotated aliases: DbSession, CurrentUser, JobSvc...
│   │   └── v1/
│   │       ├── router.py     # aggregate router
│   │       ├── health.py     # GET /health, GET /health/db (no auth)
│   │       ├── jobs.py       # GET /jobs/{id} polling
│   │       └── resumes.py    # POST /resumes/generate (example feature)
│   ├── db/
│   │   ├── base.py           # DeclarativeBase, naming conventions
│   │   ├── session.py        # async engine + sessionmaker + get_session dep
│   │   ├── models/           # job.py, resume.py
│   │   └── repositories/     # job.py, resume.py (module-level async functions)
│   ├── ai/llm/
│   │   └── client.py         # ChatOpenAI factory from settings
│   ├── services/             # business logic, owns DB commits
│   │   ├── resume_service.py # generate() using LLM + structured output
│   │   └── job_service.py   # create job, set task id, fetch owner-scoped
│   ├── schemas/              # Pydantic DTOs: requests, responses, llm_outputs
│   ├── prompts/              # module-level prompt constants per use case
│   └── worker/
│       └── tasks/
│           ├── __init__.py   # re-exports all tasks for discovery
│           ├── _runner.py    # run_job_task lifecycle
│           └── generate_resume.py
└── tests/
```

## 2. Configuration (`core/config.py`)

Single `Settings(BaseSettings)` with env prefix `RC_`, `.env` backed,
`@lru_cache` `get_settings()`. `SecretStr` for all keys.

- `database_host/port/user/password/name` — components, not DSN (SSKF pattern:
  passwords with special chars must never be URL-parsed); `database_url`
  property builds `postgresql+asyncpg://...`; `database_use_ssl: bool = false`
  (true for Supabase supavisor pooler).
- `redis_url` — `redis://localhost:6379/0` dev; managed Redis in prod.
- `celery_result_backend_url`, `celery_max_retries = 3`, `celery_soft_time_limit`,
  `celery_hard_time_limit`, `celery_concurrency`.
- `openai_api_key`, `openai_base_url`, `llm_model` — per-purpose model override
  pattern reserved (`LLM_MODEL` is the single model for now).
- `supabase_url`, `supabase_jwt_secret` (HS256 dev), `supabase_jwks_url`
  (optional, RS256 prod).
- `app_env` (dev/staging/prod), `log_level`.

`.env.example` documents every variable with sensible dev defaults.

## 3. FastAPI app

- App factory `create_app()` + `lifespan`: warmup (engine pre-ping), teardown
  (engine disposal). uvicorn target `resumecraft.main:app`; docs at
  `/api/v1/docs`, disabled in prod.
- All routes under `/api/v1`; single aggregate router in `api/v1/router.py`.
- Dependencies as `Annotated` aliases in `api/deps.py`; services constructed
  per-request.
- **Auth** (`core/security.py`): validate Supabase JWT bearer token — HS256
  with dev secret, RS256 via JWKS when `RC_SUPABASE_JWKS_URL` is set. Returns
  `CurrentUser` (Pydantic: `user_id: UUID`). `GET /health*` is public.

## 4. DB layer

- `db/session.py`: `create_async_engine(settings.database_url,
  pool_pre_ping=True)` + `async_sessionmaker`. Dev: compose postgres
  (`localhost:5432`). Prod: Supabase supavisor pooler (port 6543,
  `sslmode=require`). `NullPool` when running serverless (documented, not
  default).
- `db/models/job.py`: `id UUID PK default gen_random_uuid()`, `user_id UUID`,
  `type JobType`, `status JobStatus` (PENDING/RUNNING/COMPLETED/FAILED/
  CANCELLED), `progress float default 0`, `input JSONB`, `result JSONB
  nullable`, `error text nullable`, `celery_task_id text nullable`,
  `created_at/updated_at TIMESTAMPTZ default now()`.
- `db/models/resume.py`: `id`, `user_id`, `title`, `content JSONB`, timestamps.
- Alembic async migrations: `make revision`, `make migrate`. Schema-change
  discipline (model edit → revision → migrate) documented in CLAUDE.md.
- Repositories: module-level async functions, one module per table, explicit
  `user_id` scoping on reads (defensive alongside any RLS).

## 5. LLM service layer

- `ai/llm/client.py`: `get_chat_model(settings)` returns a configured
  `ChatOpenAI` (api_key, base_url, model from settings). No provider
  abstraction yet — one adapter, swap later if needed.
- Structured output via `model.with_structured_output(PydanticModel)` with
  Pydantic schemas in `schemas/` (e.g. `GeneratedResume`).
- Prompts: module-level string constants in `prompts/`, co-located per use
  case.
- Rule: only `services/` call the LLM. Worker tasks and endpoints never touch
  LangChain classes directly.

## 6. Celery worker

- `core/celery_app.py`: `Celery("resumecraft", include=["resumecraft.worker.tasks"])`
  + `configure_celery(app, settings)`. Run:
  `celery -A resumecraft.core.celery_app worker --loglevel=info`.
- `core/celery_config.py`: Redis broker + result backend; `default` queue with
  reserved `priority` queue; `task_acks_late=True`,
  `task_reject_on_worker_lost=True`, `task_track_started=True`, JSON-only
  serialization, UTC, global `task_autoretry_for=(Exception,)` with
  settings-driven `max_retries` and 60s delay, soft/hard time limits from
  settings, `worker_prefetch_multiplier=1`, `worker_max_tasks_per_child=20`,
  `result_expires=86400`, task events on.
- Tasks: thin shells; frozen name strings
  `"resumecraft.worker.tasks.<x>"`; each task re-exported from
  `worker/tasks/__init__.py` or it won't register. Business logic lives in
  `services/`.
- `worker/tasks/_runner.py::run_job_task`: per-task-invocation async engine
  (created/disposed in `finally`, Hodai pattern), fetch Job, PENDING→RUNNING,
  call `service.work(job, update_progress)`, write COMPLETED/FAILED, treat
  `SoftTimeLimitExceeded` as distinct timeout outcome. Per-task
  `dont_autoretry_for` for domain errors that shouldn't retry.
- API → worker decoupling: endpoints call `celery_app.send_task(<name>)` and
  store the returned id via `job_service.set_celery_task_id()`. Task names are
  a frozen contract.

## 7. Example feature: resume generation job

Flow (proves API → DB → broker → worker → LLM → DB):

1. `POST /api/v1/resumes/generate` (auth) validates input (e.g. raw resume
   text + target role).
2. Insert `Job(PENDING, type=generate_resume, input)`; commit.
3. `celery_app.send_task("resumecraft.worker.tasks.generate_resume",
   kwargs={"job_id": ...})`; save `celery_task_id` on the Job.
4. Return `202` with `job_id`.
5. Worker task → `run_job_task` → `ResumeService.generate(input,
   update_progress)` → prompt → `ChatOpenAI.with_structured_output(
   GeneratedResume)` → write `Job.result` + insert `Resume` row.
6. Client polls `GET /api/v1/jobs/{job_id}` (owner-scoped) for status,
   progress, and result.

## 8. Infra & Makefile

- `docker-compose.yml`: `postgres:16` (db for dev), `redis:7`. API and worker
  run on host: `make dev` (uvicorn --reload), `make worker` (celery).
- Makefile targets: `dev`, `worker`, `test`, `lint` (ruff), `typecheck`
  (mypy), `imports` (import-linter), `migrate`, `revision`, `up`, `down`.
- Import-linter contracts (enforced in `pyproject.toml`, `make imports`):
  - `api` layer may not be imported by anything.
  - `services` may not import `api` or `worker`.
  - `ai` is independent of business logic (`services`, `api`, `worker`).
  - `worker` may import `services`, `db`, `ai`, `core` — never `api`.

## 9. Testing

- pytest, markers: `llm`, `network`, `db` — excluded by default.
- Unit: services with mocked LLM client; `_runner` lifecycle with mocked
  session/engine.
- API: httpx `AsyncClient` against the app with auth dependency overridden.
- conftest mirrors SSKF/resumebloom patterns (fixtures for settings, session,
  auth user).

## 10. Conventions doc

A `CLAUDE.md` at project root documents: layering rules, schema-change
discipline, frozen task-name contract, how to run API/worker/migrations, and
env switching dev↔Supabase.

## Out of scope (future)

- Additional domain features (analysis, tailoring, cover letters, templates)
- Vector stores / RAG, tracing (Langfuse), guardrails
- Deployment pipeline (Railway/Vercel), CI
- Rate limiting, billing, multi-tenant RLS policies