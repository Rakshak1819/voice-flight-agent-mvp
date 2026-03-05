from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TripType = Literal["one_way", "round_trip"]
CabinType = Literal["economy", "premium_economy", "business", "first"]
TimeWindow = Literal["morning", "afternoon", "evening", "any"]
OfferSort = Literal["balanced", "cheapest", "fastest", "fewest_stops", "bag_friendly"]


class ConversationPhase(str, Enum):
    COLLECTING_REQUIREMENTS = "collecting_requirements"
    AWAITING_SELECTION = "awaiting_selection"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TripRequest(BaseModel):
    trip_type: TripType | None = None
    origin: str | None = None
    destination: str | None = None
    depart_date: str | None = None
    return_date: str | None = None
    passengers: int | None = None
    cabin: CabinType = "economy"
    nonstop_preference: bool | None = None
    max_stops: int | None = None
    budget_usd: int | None = None
    time_window: TimeWindow | None = None

    @field_validator("passengers")
    @classmethod
    def validate_passengers(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value < 1:
            raise ValueError("passengers must be >= 1")
        if value > 9:
            raise ValueError("passengers must be <= 9 for MVP")
        return value

    @field_validator("max_stops")
    @classmethod
    def validate_max_stops(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in (0, 1, 2):
            raise ValueError("max_stops must be one of 0/1/2")
        return value

    @field_validator("depart_date", "return_date")
    @classmethod
    def validate_date_format(cls, value: str | None) -> str | None:
        if value is None:
            return value
        datetime.strptime(value, "%Y-%m-%d")
        return value

    @model_validator(mode="after")
    def validate_round_trip_fields(self) -> "TripRequest":
        if self.trip_type == "round_trip" and not self.return_date:
            # return_date is only strictly required when all required slots are checked.
            return self
        if self.depart_date and self.return_date:
            depart = datetime.strptime(self.depart_date, "%Y-%m-%d").date()
            ret = datetime.strptime(self.return_date, "%Y-%m-%d").date()
            if ret < depart:
                raise ValueError("return_date must be on or after depart_date")
        return self

    def required_missing_slots(self) -> list[str]:
        required = ["trip_type", "origin", "destination", "depart_date", "passengers"]
        if self.trip_type == "round_trip":
            required.append("return_date")

        missing: list[str] = []
        for slot in required:
            value = getattr(self, slot)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(slot)
        return missing


class FlightOffer(BaseModel):
    offer_id: str
    provider: str
    carrier: str
    flight_number: str
    origin: str
    destination: str
    depart_time_local: str
    arrive_time_local: str
    duration_minutes: int
    stops: int
    cabin: CabinType
    price_usd: float
    refundable: bool
    cabin_bag_included: bool = True
    checked_bag_included: bool = False
    checked_bag_fee_usd: float = 0.0
    currency: str = "USD"


class BookingResult(BaseModel):
    success: bool
    provider: str = "mock"
    booking_reference: str | None = None
    message: str


class TranscriptTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    text: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


class SessionState(BaseModel):
    session_id: str
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    phase: ConversationPhase = ConversationPhase.COLLECTING_REQUIREMENTS
    preferences_prompted: bool = False
    trip_request: TripRequest = Field(default_factory=TripRequest)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    all_offers: list[FlightOffer] = Field(default_factory=list)
    offers_shown: list[FlightOffer] = Field(default_factory=list)
    offer_sort: OfferSort = "balanced"
    offer_require_refundable: bool = False
    offer_require_cabin_bag: bool | None = None
    offer_require_checked_bag: bool | None = None
    offer_cursor: int = 0
    selected_offer_id: str | None = None
    booking_result: BookingResult | None = None

    def add_turn(self, role: Literal["user", "assistant", "system"], text: str) -> None:
        self.transcript.append(TranscriptTurn(role=role, text=text))

    def get_selected_offer(self) -> FlightOffer | None:
        if not self.selected_offer_id:
            return None
        for offer in self.all_offers:
            if offer.offer_id == self.selected_offer_id:
                return offer
        for offer in self.offers_shown:
            if offer.offer_id == self.selected_offer_id:
                return offer
        return None


class SessionSnapshot(BaseModel):
    transcript: list[TranscriptTurn]
    final_trip_request: TripRequest
    offers_shown: list[FlightOffer]
    selected_offer: FlightOffer | None
    booking_result: BookingResult | None
