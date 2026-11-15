"""OpenRouteService: geocoding and driving distance (https://openrouteservice.org)."""

from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.clients.distance.cities import Coordinates

METERS_PER_MILE = Decimal("1609.344")
BASE_URL = "https://api.openrouteservice.org"


class RoutingError(Exception):
    """The routing service failed (network, quota, bad response)."""


class RoutingClient(Protocol):
    def geocode(self, city: str) -> Coordinates | None: ...
    def driving_miles(self, origin: Coordinates, destination: Coordinates) -> Decimal: ...


class OrsClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=10.0)
        self._headers = {"Authorization": api_key}

    def geocode(self, city: str) -> Coordinates | None:
        data = self._request(
            "GET",
            "/geocode/search",
            params={"text": city, "boundary.country": "US", "layers": "locality", "size": 1},
        )
        features = data.get("features") or []
        if not features:
            return None
        lon, lat = features[0]["geometry"]["coordinates"][:2]
        return (float(lat), float(lon))

    def driving_miles(self, origin: Coordinates, destination: Coordinates) -> Decimal:
        # ORS expects [lon, lat] pairs.
        body = {"coordinates": [[origin[1], origin[0]], [destination[1], destination[0]]]}
        data = self._request("POST", "/v2/directions/driving-car", json=body)
        try:
            meters = Decimal(str(data["routes"][0]["summary"]["distance"]))
        except (KeyError, IndexError, TypeError) as error:
            raise RoutingError(f"unexpected ORS response: {error!r}") from error
        return (meters / METERS_PER_MILE).quantize(Decimal("0.1"))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, headers=self._headers, **kwargs)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RoutingError(f"ORS {method} {path} failed: {error}") from error
        if not isinstance(data, dict):
            raise RoutingError("unexpected ORS response shape")
        return data
