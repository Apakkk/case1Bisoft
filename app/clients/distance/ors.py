"""OpenRouteService: geocoding and driving distance (https://openrouteservice.org)."""

import re
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.clients.distance.cities import Coordinates
from app.models.city import City

METERS_PER_MILE = Decimal("1609.344")
BASE_URL = "https://api.openrouteservice.org"
AUTOCOMPLETE_PAGE_SIZE = 10  # ORS/Pelias returns at most this many; fewer means the list is complete
AUTOCOMPLETE_TIMEOUT_SECONDS = 3.0  # suggestions are only useful while the user is still typing
_OFFICIAL_PREFIX = re.compile(r"^(?:city|town|village|borough) of\s+", re.IGNORECASE)  # 'City of Boca Raton'


class RoutingError(Exception):
    """The routing service failed (network, quota, bad response)."""


class RoutingClient(Protocol):
    def geocode(self, city: str) -> Coordinates | None: ...
    def driving_miles(self, origin: Coordinates, destination: Coordinates) -> Decimal: ...


class PlaceSearch(Protocol):
    def autocomplete(self, text: str) -> list[City]: ...


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

    def autocomplete(self, text: str) -> list[City]:
        """US cities and towns whose name starts like `text` (layers=locality: no districts, streets or venues)."""
        data = self._request(
            "GET",
            "/geocode/autocomplete",
            params={"text": text, "boundary.country": "US", "layers": "locality"},
            timeout=AUTOCOMPLETE_TIMEOUT_SECONDS,
        )
        cities = []
        for feature in data.get("features") or []:
            try:
                properties = feature["properties"]
                lon, lat = feature["geometry"]["coordinates"][:2]
                name = _OFFICIAL_PREFIX.sub("", str(properties["name"]).strip())
                state = str(properties.get("region_a") or "").strip()
                city = City(name=name, state=state, lat=float(lat), lon=float(lon))
            except (KeyError, IndexError, TypeError, ValueError):
                continue  # skip a malformed feature instead of losing the whole list
            if name:
                cities.append(city)
        return cities

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
