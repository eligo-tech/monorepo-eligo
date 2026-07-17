"""Domain layer — self-contained packages (candidates, jobs, companies,
pipeline, matching, verification) plus shared ``common`` primitives.

Each domain follows the same file convention:
    models.py   — SQLAlchemy ORM (system-of-record tables)
    schemas.py  — Pydantic v2 request/response contracts
    service.py  — business logic (no framework coupling)
    router.py   — FastAPI APIRouter exposing the service
"""