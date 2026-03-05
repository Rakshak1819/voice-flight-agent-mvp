from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.state import BookingResult, FlightOffer, TripRequest


class FlightProvider(ABC):
    name: str

    @abstractmethod
    def search_offers(self, trip_request: TripRequest) -> list[FlightOffer]:
        """Return normalized flight offers for a trip request."""

    @abstractmethod
    def book_offer(self, offer: FlightOffer, trip_request: TripRequest) -> BookingResult:
        """Execute booking for a selected offer."""
