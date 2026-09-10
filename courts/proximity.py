"""Shared, server-authoritative helpers for Court Complex GPS proximity checks."""

from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Iterable, Optional

from django.conf import settings


VERIFICATION_NORMAL_RADIUS = "normal_radius"
VERIFICATION_ACCURACY_ASSISTED = "accuracy_assisted"
VERIFICATION_USER_CONFIRMED_AMBIGUOUS = "user_confirmed_ambiguous"
VERIFICATION_OUT_OF_RANGE = "out_of_range"
VERIFICATION_AMBIGUOUS = "ambiguous_venue"


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


def valid_accuracy_metres(value) -> Optional[float]:
    """Return a safe browser accuracy value, or None for missing/invalid input.

    Missing or invalid accuracy deliberately has no tolerance effect, retaining
    the established strict-radius behaviour for legacy or malformed requests.
    """
    if value in (None, ""):
        return None
    try:
        accuracy = float(value)
    except (TypeError, ValueError):
        return None
    return accuracy if isfinite(accuracy) and accuracy >= 0 else None


@dataclass(frozen=True)
class ProximityAssessment:
    """The server's complete decision for one selected physical Court Complex."""

    outcome: str
    distance_metres: float
    configured_radius_metres: float
    effective_radius_metres: float
    reported_accuracy_metres: Optional[float]
    overlapping_complexes: tuple

    @property
    def allowed(self) -> bool:
        return self.outcome in {
            VERIFICATION_NORMAL_RADIUS,
            VERIFICATION_ACCURACY_ASSISTED,
            VERIFICATION_USER_CONFIRMED_AMBIGUOUS,
        }

    @property
    def used_accuracy_assistance(self) -> bool:
        return self.outcome in {
            VERIFICATION_ACCURACY_ASSISTED,
            VERIFICATION_USER_CONFIRMED_AMBIGUOUS,
        }


def _physical_complexes(candidates: Optional[Iterable] = None):
    """Return only physical complexes from the provided candidates or database."""
    if candidates is None:
        from courts.models import CourtComplex

        candidates = CourtComplex.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
        ).order_by("id")
    return tuple(complex_ for complex_ in candidates if complex_.has_coordinates())


def assess_court_proximity(
    *,
    latitude: float,
    longitude: float,
    selected_complex,
    reported_accuracy=None,
    candidate_complexes: Optional[Iterable] = None,
    venue_confirmed: bool = False,
) -> ProximityAssessment:
    """Assess one browser position against an existing physical Court Complex.

    The configured Court Complex radius is never changed.  A valid browser
    accuracy is a one-request uncertainty allowance only.  If an
    accuracy-assisted reading plausibly overlaps more than one physical venue,
    the caller must obtain an explicit user choice before allowing it.

    ``candidate_complexes`` may narrow ambiguity choices for a caller with an
    existing venue authorization boundary (for example Friendly creation).  It
    must contain only venues the caller may actually select.
    """
    configured_radius = float(settings.PFC_FRIENDLY_COURT_PROXIMITY_METERS)
    distance = distance_metres(
        float(latitude),
        float(longitude),
        float(selected_complex.latitude),
        float(selected_complex.longitude),
    )
    accuracy = valid_accuracy_metres(reported_accuracy)

    if distance <= configured_radius:
        return ProximityAssessment(
            outcome=VERIFICATION_NORMAL_RADIUS,
            distance_metres=distance,
            configured_radius_metres=configured_radius,
            effective_radius_metres=configured_radius,
            reported_accuracy_metres=accuracy,
            overlapping_complexes=(selected_complex,),
        )

    # Invalid or absent accuracy intentionally falls back to the strict
    # established radius check.
    if accuracy is None:
        return ProximityAssessment(
            outcome=VERIFICATION_OUT_OF_RANGE,
            distance_metres=distance,
            configured_radius_metres=configured_radius,
            effective_radius_metres=configured_radius,
            reported_accuracy_metres=None,
            overlapping_complexes=(),
        )

    effective_radius = configured_radius + accuracy
    if distance > effective_radius:
        return ProximityAssessment(
            outcome=VERIFICATION_OUT_OF_RANGE,
            distance_metres=distance,
            configured_radius_metres=configured_radius,
            effective_radius_metres=effective_radius,
            reported_accuracy_metres=accuracy,
            overlapping_complexes=(),
        )

    # The point is outside the normal physical radius but its stated horizontal
    # uncertainty can include the selected Court Complex.  Find every physical
    # venue whose own configured radius has the same overlap.  Virtual venues
    # never enter this calculation.
    physical_complexes = _physical_complexes(candidate_complexes)
    overlapping = tuple(
        complex_
        for complex_ in physical_complexes
        if distance_metres(
            float(latitude),
            float(longitude),
            float(complex_.latitude),
            float(complex_.longitude),
        ) <= configured_radius + accuracy
    )

    # Ensure the selected Court Complex is represented even when a caller
    # supplied a lazily evaluated candidate collection that did not include it.
    if selected_complex not in overlapping:
        overlapping = (selected_complex,) + overlapping

    if len(overlapping) > 1 and not venue_confirmed:
        outcome = VERIFICATION_AMBIGUOUS
    elif len(overlapping) > 1:
        outcome = VERIFICATION_USER_CONFIRMED_AMBIGUOUS
    else:
        outcome = VERIFICATION_ACCURACY_ASSISTED

    return ProximityAssessment(
        outcome=outcome,
        distance_metres=distance,
        configured_radius_metres=configured_radius,
        effective_radius_metres=effective_radius,
        reported_accuracy_metres=accuracy,
        overlapping_complexes=overlapping,
    )


def assessment_payload(assessment: ProximityAssessment):
    """Return caller-safe diagnostic metadata without exposing other users."""
    return {
        "verification_outcome": assessment.outcome,
        "distance_metres": round(assessment.distance_metres, 1),
        "configured_radius_metres": round(assessment.configured_radius_metres, 1),
        "effective_radius_metres": round(assessment.effective_radius_metres, 1),
        "reported_accuracy_metres": (
            round(assessment.reported_accuracy_metres, 1)
            if assessment.reported_accuracy_metres is not None
            else None
        ),
        "venues": [
            {"id": complex_.pk, "name": complex_.name}
            for complex_ in assessment.overlapping_complexes
        ],
    }
