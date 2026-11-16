"""FastAPI application factory and lifespan (database pool + service wiring)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import Auth, install_auth
from app.config import get_settings
from app.controllers import (
    auth_controller,
    carrier_admin_controller,
    carrier_api_controller,
    city_admin_controller,
    city_api_controller,
    health_controller,
    home_controller,
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


def _show_app_logs() -> None:
    """Print the app's INFO lines (one per Jev request, table reloads) beside uvicorn's; WARNING and up already show."""
    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)


def create_app() -> FastAPI:
    _show_app_logs()
    app = FastAPI(
        title="Carrier Selection API",
        version="0.1.0",
        description="Selects the best container carrier with deterministic rules; Jev handles semantic checks.",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    install_auth(app, Auth.from_settings(get_settings()))
    app.include_router(auth_controller.router)
    app.include_router(health_controller.router)
    app.include_router(quote_controller.router)
    app.include_router(carrier_api_controller.router)
    app.include_router(city_api_controller.router)
    app.include_router(carrier_admin_controller.router)
    app.include_router(quote_admin_controller.router)
    app.include_router(rules_admin_controller.router)
    app.include_router(city_admin_controller.router)
    app.include_router(home_controller.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
