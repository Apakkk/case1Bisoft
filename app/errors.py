"""Domain errors -> HTTP responses, in one place. Error payloads: {"error": CODE, "detail": ...}."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.clients.distance.chain import UnknownLocationError
from app.repositories.carrier_repository import DuplicateCarrierError, InvalidCarrierError
from app.selection.rules import RulesError
from app.services.carrier_service import CarrierNotFoundError, CarrierValidationError
from app.services.quote_service import InvalidOrderError


def _error(status_code: int, code: str, detail: object, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "detail": detail, **extra})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnknownLocationError)
    async def unknown_location(_: Request, exc: UnknownLocationError) -> JSONResponse:
        suggestions = [{"name": place.name, "state": place.state} for place in exc.suggestions]
        return _error(
            422, "UNKNOWN_LOCATION", exc.detail, city=exc.city, problem=exc.problem.value, suggestions=suggestions
        )

    @app.exception_handler(InvalidOrderError)
    async def invalid_order(_: Request, exc: InvalidOrderError) -> JSONResponse:
        return _error(422, "INVALID_ORDER", str(exc))

    @app.exception_handler(CarrierValidationError)
    async def invalid_carrier(_: Request, exc: CarrierValidationError) -> JSONResponse:
        return _error(422, "INVALID_CARRIER", exc.errors)

    @app.exception_handler(InvalidCarrierError)
    async def carrier_constraint(_: Request, exc: InvalidCarrierError) -> JSONResponse:
        return _error(422, "INVALID_CARRIER", str(exc))

    @app.exception_handler(DuplicateCarrierError)
    async def duplicate_carrier(_: Request, exc: DuplicateCarrierError) -> JSONResponse:
        return _error(status.HTTP_409_CONFLICT, "DUPLICATE_CARRIER", str(exc))

    @app.exception_handler(CarrierNotFoundError)
    async def carrier_not_found(_: Request, exc: CarrierNotFoundError) -> JSONResponse:
        return _error(status.HTTP_404_NOT_FOUND, "CARRIER_NOT_FOUND", str(exc))

    @app.exception_handler(RulesError)
    async def invalid_rules(_: Request, exc: RulesError) -> JSONResponse:
        return _error(500, "INVALID_RULES", f"config/rules.yaml is invalid: {exc}")
