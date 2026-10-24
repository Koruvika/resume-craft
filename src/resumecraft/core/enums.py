from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    GENERATE_RESUME = "generate_resume"
    # Kept in sync with the DB enum (migration 0004; Postgres cannot drop enum
    # values). Reserved for a future raw-text/PDF parse flow — no task yet.
    PARSE_RESUME = "parse_resume"
