"""Trips: turn sparse sightings into stays, trips and honest gaps.

Purpose    : Local segmentation of one device's observations into the rows a
             "where was my son today" view needs. Nothing here talks to the
             network except the opt-in `routing` module.
Outputs    : See `findplus.trips.service.trips_payload`.
"""

from findplus.trips.models import Fix, Gap, Stay, TripLeg
from findplus.trips.segment import SegmentParams, segment

__all__ = ["Fix", "Gap", "SegmentParams", "Stay", "TripLeg", "segment"]
