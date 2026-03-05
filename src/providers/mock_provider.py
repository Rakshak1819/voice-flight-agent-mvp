from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from src.core.state import BookingResult, FlightOffer, TripRequest
from src.providers.base import FlightProvider


def _stable_seed(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def normalize_offer(raw_offer: dict[str, object]) -> FlightOffer:
    return FlightOffer(
        offer_id=str(raw_offer["offer_id"]),
        provider=str(raw_offer.get("provider", "mock")),
        carrier=str(raw_offer["carrier"]),
        flight_number=str(raw_offer["flight_number"]),
        origin=str(raw_offer["origin"]),
        destination=str(raw_offer["destination"]),
        depart_time_local=str(raw_offer["depart_time_local"]),
        arrive_time_local=str(raw_offer["arrive_time_local"]),
        duration_minutes=int(raw_offer["duration_minutes"]),
        stops=int(raw_offer["stops"]),
        cabin=str(raw_offer["cabin"]),
        price_usd=float(raw_offer["price_usd"]),
        refundable=bool(raw_offer["refundable"]),
        cabin_bag_included=bool(raw_offer.get("cabin_bag_included", True)),
        checked_bag_included=bool(raw_offer.get("checked_bag_included", False)),
        checked_bag_fee_usd=float(raw_offer.get("checked_bag_fee_usd", 0.0)),
        currency=str(raw_offer.get("currency", "USD")),
    )


class MockFlightProvider(FlightProvider):
    name = "mock"

    def search_offers(self, trip_request: TripRequest) -> list[FlightOffer]:
        key = "|".join(
            [
                trip_request.origin or "UNK",
                trip_request.destination or "UNK",
                trip_request.depart_date or "1970-01-01",
                trip_request.return_date or "",
                str(trip_request.passengers or 1),
                trip_request.cabin,
                str(trip_request.max_stops) if trip_request.max_stops is not None else "2",
                trip_request.time_window or "any",
            ]
        )
        seed = _stable_seed(key)

        passengers = trip_request.passengers or 1
        base_price = 180 + (seed % 220)
        depart = datetime.strptime(trip_request.depart_date or "2026-01-01", "%Y-%m-%d")

        offers_raw: list[dict[str, object]] = []
        carriers = ["SkyJet", "AeroWays", "CloudAir", "JetNova", "BlueConnect", "WingSpan"]
        for idx, carrier in enumerate(carriers, start=1):
            stops = min((idx - 1) % 3, 2)
            if trip_request.nonstop_preference is True:
                stops = 0
            if trip_request.max_stops is not None:
                stops = min(stops, trip_request.max_stops)

            hour_offsets = [6, 8, 11, 13, 17, 20]
            depart_time = depart + timedelta(hours=hour_offsets[(idx - 1) % len(hour_offsets)])
            duration = 120 + idx * 37 + (seed % 25)
            arrive_time = depart_time + timedelta(minutes=duration)
            price = (base_price + idx * 49) * passengers

            if trip_request.budget_usd and price > trip_request.budget_usd:
                price = max(99, trip_request.budget_usd - (idx * 15))

            cabin_bag_included = idx not in (5, 6)
            checked_bag_included = idx in (1, 4)
            checked_bag_fee_usd = 0.0 if checked_bag_included else float(25 + idx * 8)
            if not cabin_bag_included:
                price -= 12

            offers_raw.append(
                {
                    "offer_id": f"MOCK-{seed % 10000:04d}-{idx}",
                    "provider": self.name,
                    "carrier": carrier,
                    "flight_number": f"{carrier[:2].upper()}{200 + idx}",
                    "origin": trip_request.origin or "UNK",
                    "destination": trip_request.destination or "UNK",
                    "depart_time_local": depart_time.strftime("%Y-%m-%d %H:%M"),
                    "arrive_time_local": arrive_time.strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": duration,
                    "stops": stops,
                    "cabin": trip_request.cabin,
                    "price_usd": float(price),
                    "refundable": idx in (1, 3),
                    "cabin_bag_included": cabin_bag_included,
                    "checked_bag_included": checked_bag_included,
                    "checked_bag_fee_usd": checked_bag_fee_usd,
                    "currency": "USD",
                }
            )

        return [normalize_offer(o) for o in offers_raw]

    def book_offer(self, offer: FlightOffer, trip_request: TripRequest) -> BookingResult:
        if not offer.offer_id.startswith("MOCK-"):
            return BookingResult(
                success=False,
                provider=self.name,
                message="Booking failed: unsupported offer id.",
            )

        ref_suffix = _stable_seed(offer.offer_id + (trip_request.depart_date or "")) % 100000
        return BookingResult(
            success=True,
            provider=self.name,
            booking_reference=f"MB{ref_suffix:05d}",
            message="Mock booking successful.",
        )
