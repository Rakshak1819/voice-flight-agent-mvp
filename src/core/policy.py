from __future__ import annotations

import re

from src.core.state import FlightOffer, TripRequest


_AFFIRMATIVE = {"yes", "y", "confirm", "confirmed", "book it", "do it"}
_NEGATIVE = {"no", "n", "cancel", "stop", "nope"}


def parse_yes_no(text: str) -> bool | None:
    normalized = text.strip().lower()
    if normalized in _AFFIRMATIVE:
        return True
    if normalized in _NEGATIVE:
        return False

    if re.search(r"\b(yes|book it|confirm|go ahead)\b", normalized):
        return True
    if re.search(r"\b(no|cancel|don't|do not)\b", normalized):
        return False
    return None


def parse_offer_selection(text: str, max_options: int) -> int | None:
    normalized = text.strip().lower()
    if "none" in normalized:
        return 0

    word_map = {"first": 1, "second": 2, "third": 3, "one": 1, "two": 2, "three": 3}
    for token, idx in word_map.items():
        if re.search(rf"\b{token}\b", normalized) and idx <= max_options:
            if token in {"first", "second", "third"}:
                return idx
            if re.search(r"\b(option|flight|choose|pick|take)\b", normalized):
                return idx

    match = re.search(r"\b([1-3])\b", normalized)
    if match:
        idx = int(match.group(1))
        if 1 <= idx <= max_options:
            return idx
    return None


def booking_readback(trip_request: TripRequest, offer: FlightOffer) -> str:
    passengers = trip_request.passengers or 1
    return (
        f"You selected {offer.carrier} flight {offer.flight_number} from {offer.origin} to {offer.destination}, "
        f"departing {offer.depart_time_local}, arriving {offer.arrive_time_local}, with {offer.stops} stop(s). "
        f"Cabin: {offer.cabin}. Passengers: {passengers}. Total price: ${offer.price_usd:.2f} {offer.currency}. "
        f"Refundable: {'yes' if offer.refundable else 'no'}. Confirm booking? yes/no"
    )


def can_attempt_booking(has_selection: bool, confirmation_text: str) -> tuple[bool, str]:
    if not has_selection:
        return False, "No offer selected."

    decision = parse_yes_no(confirmation_text)
    if decision is not True:
        return False, "Explicit yes confirmation is required before booking."

    return True, "OK"
