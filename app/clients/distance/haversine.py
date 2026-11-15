from math import asin, cos, radians, sin, sqrt

from app.clients.distance.cities import Coordinates

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(a: Coordinates, b: Coordinates) -> float:
    """Great-circle (straight-line) distance; road distance is roughly this x 1.2."""
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(h))
