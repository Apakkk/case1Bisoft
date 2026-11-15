"""OrsClient against httpx.MockTransport: no network, real request/response handling."""

import json
from decimal import Decimal

import httpx
import pytest

from app.clients.distance.ors import BASE_URL, OrsClient, RoutingError
from app.models.city import City


def client(handler: httpx.MockTransport) -> OrsClient:
    return OrsClient("test-key", httpx.Client(base_url=BASE_URL, transport=handler))


def test_driving_distance_is_converted_from_meters_to_miles() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"routes": [{"summary": {"distance": 46830.9}}]})

    miles = client(httpx.MockTransport(handle)).driving_miles((25.7617, -80.1918), (26.1224, -80.1373))

    assert miles == Decimal("29.1")
    assert seen["auth"] == "test-key"
    assert seen["body"] == {"coordinates": [[-80.1918, 25.7617], [-80.1373, 26.1224]]}  # [lon, lat]


def test_geocode_returns_lat_lon() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["text"] == "Ocala"
        return httpx.Response(200, json={"features": [{"geometry": {"coordinates": [-82.1401, 29.1872]}}]})

    assert client(httpx.MockTransport(handle)).geocode("Ocala") == (29.1872, -82.1401)


def test_geocode_without_match_returns_none() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": []})

    assert client(httpx.MockTransport(handle)).geocode("Atlantis") is None


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_become_routing_errors(status: int) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "nope"})

    with pytest.raises(RoutingError):
        client(httpx.MockTransport(handle)).driving_miles((0, 0), (1, 1))


def feature(name: str, state: str | None, lon: float, lat: float) -> dict[str, object]:
    properties: dict[str, object] = {"name": name, "label": f"{name}, {state}, USA"}
    if state is not None:
        properties["region_a"] = state
    return {"properties": properties, "geometry": {"coordinates": [lon, lat]}}


def test_autocomplete_asks_for_us_cities_only_and_reads_name_state_coordinates() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        seen["path"] = request.url.path
        features = [feature("Orlando", "FL", -81.3792, 28.5383), feature("Orland Park", "IL", -87.85, 41.63)]
        return httpx.Response(200, json={"features": features})

    cities = client(httpx.MockTransport(handle)).autocomplete("orl")

    assert seen["path"] == "/geocode/autocomplete"
    assert (seen["text"], seen["boundary.country"], seen["layers"]) == ("orl", "US", "locality")
    assert cities == [City("Orlando", "FL", 28.5383, -81.3792), City("Orland Park", "IL", 41.63, -87.85)]


def test_autocomplete_skips_malformed_features_and_tolerates_a_missing_state() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        broken = {"properties": {"name": "Broken"}}  # no geometry
        features = [broken, feature("", "FL", 0, 0), feature("Boca Raton", None, -80.1, 26.4)]
        return httpx.Response(200, json={"features": features})

    assert client(httpx.MockTransport(handle)).autocomplete("boca") == [City("Boca Raton", "", 26.4, -80.1)]


def test_autocomplete_errors_become_routing_errors() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "quota"})

    with pytest.raises(RoutingError):
        client(httpx.MockTransport(handle)).autocomplete("boca")


def test_autocomplete_drops_the_official_prefix() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        features = [feature("City of Boca Raton", "FL", -80.1, 26.4), feature("Town of Palm Beach", "FL", -80.0, 26.7)]
        return httpx.Response(200, json={"features": features})

    names = [c.name for c in client(httpx.MockTransport(handle)).autocomplete("boca")]

    assert names == ["Boca Raton", "Palm Beach"]
