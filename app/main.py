"""FastAPI application factory and lifespan (database pool + service wiring)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.controllers import (
    carrier_admin_controller,
    carrier_api_controller,
    city_admin_controller,
    city_api_controller,
    health_controller,
    quote_admin_controller,
    quote_controller,
    rules_admin_controller,
)
from app.db import create_pool
from app.dependencies import build_services
from app.errors import register_error_handlers
from app.views import STATIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = create_pool(settings.database_url)
    app.state.pool = pool
    app.state.services = build_services(settings, pool)
    try:
        yield
    finally:
        pool.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Carrier Selection API",
        version="0.1.0",
        description="Selects the best container carrier with deterministic rules; Jev handles semantic checks.",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(health_controller.router)
    app.include_router(quote_controller.router)
    app.include_router(carrier_api_controller.router)
    app.include_router(city_api_controller.router)
    app.include_router(carrier_admin_controller.router)
    app.include_router(quote_admin_controller.router)
    app.include_router(rules_admin_controller.router)
    app.include_router(city_admin_controller.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/admin/carriers")

    return app


app = create_app()
