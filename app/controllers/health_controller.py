from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    """Liveness plus a quick database probe; the API stays up when the database is down."""
    pool = getattr(request.app.state, "pool", None)
    database = "unavailable"
    if pool is not None:
        try:
            with pool.connection(timeout=1) as conn:
                conn.execute("SELECT 1")
            database = "ok"
        except Exception:
            database = "unavailable"
    return {"status": "ok", "database": database}
