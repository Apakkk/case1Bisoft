"""OrsClient against httpx.MockTransport: no network, real request/response handling."""

import json
from decimal import Decimal

import httpx
import pytest

from app.clients.distance.ors import BASE_URL, OrsClient, RoutingError


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
