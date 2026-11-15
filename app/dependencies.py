"""The single place where implementations are wired to interfaces (tests override the getters)."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from app.clients.distance.chain import DistanceProvider
from app.clients.distance.cities import load_city_directory
from app.clients.distance.ors import OrsClient
from app.clients.distance.static_table import load_static_table
from app.clients.jev_client import JevClient, TypesafeJevClient
from app.config import Settings
from app.db import Pool
from app.repositories.carrier_repository import PostgresCarrierRepository
from app.repositories.distance_cache_repository import PostgresDistanceCache
from app.repositories.rules_repository import FileRulesRepository, RulesStore
from app.selection.rules import RuleSet
from app.services.carrier_service import CarrierService
from app.services.quote_service import QuoteService
from app.services.rules_service import RulesService


@dataclass(frozen=True, slots=True)
class Services:
    quotes: QuoteService
    carriers: CarrierService
    rules: RulesStore


def build_distance_provider(config_dir: Path, settings: Settings, pool: Pool | None) -> DistanceProvider:
    table = load_static_table(config_dir / "distances.yaml")
    cities = load_city_directory(config_dir / "cities.csv", config_dir / "city_aliases.yaml", table.city_names())
    cache = PostgresDistanceCache(pool.connection) if pool is not None else None
    routing = OrsClient(settings.ors_api_key.get_secret_value()) if settings.ors_api_key else None
    return DistanceProvider(cities, table, cache, routing)


def build_jev_client(settings: Settings) -> JevClient | None:
    """No key -> no Jev: free-text fields ask for input and carrier notes are flagged for review."""
    if settings.typesafe_api_key is None:
        return None
    return TypesafeJevClient(
        api_key=settings.typesafe_api_key.get_secret_value(),
        model=settings.jev_model,
        timeout=settings.jev_timeout_seconds,
    )


def build_services(settings: Settings, pool: Pool) -> Services:
    rules = FileRulesRepository(settings.rules_path)
    distances = build_distance_provider(settings.config_dir, settings, pool)
    carriers = PostgresCarrierRepository(pool.connection)
    jev = build_jev_client(settings)
    return Services(
        quotes=QuoteService(carriers, distances, rules, jev),
        carriers=CarrierService(carriers, distances, rules, jev),
        rules=rules,
    )


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def get_quote_service(request: Request) -> QuoteService:
    return get_services(request).quotes


def get_carrier_service(request: Request) -> CarrierService:
    return get_services(request).carriers


def get_rules(request: Request) -> RuleSet:
    return get_services(request).rules.get()


def get_rules_service(request: Request) -> RulesService:
    return RulesService(get_services(request).rules)
