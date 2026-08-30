"""Small shared helpers for Court Complex GPS proximity checks."""

from math import asin, cos, radians, sin, sqrt


def distance_metres(latitude_a, longitude_a, latitude_b, longitude_b):
    """Return the great-circle distance between two coordinates in metres."""
    earth_radius_metres = 6_371_000
    lat_delta = radians(latitude_b - latitude_a)
    lon_delta = radians(longitude_b - longitude_a)
    haversine = (
        sin(lat_delta / 2) ** 2
        + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(lon_delta / 2) ** 2
    )
    return 2 * earth_radius_metres * asin(sqrt(haversine))
