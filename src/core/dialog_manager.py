from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from src.core.locations import normalize_location_text
from src.core.policy import booking_readback, can_attempt_booking, parse_offer_selection, parse_yes_no
from src.core.state import ConversationPhase, OfferSort, SessionState, TripRequest
from src.llm.client import LLMClient
from src.providers.base import FlightProvider

logger = logging.getLogger(__name__)


WORD_NUMBERS = {
    "zero": 0,
    "oh": 0,
    "o": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}

CARDINAL_WORDS = {
    **WORD_NUMBERS,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "twenty first": 21,
    "twenty second": 22,
    "twenty third": 23,
    "twenty fourth": 24,
    "twenty fifth": 25,
    "twenty sixth": 26,
    "twenty seventh": 27,
    "twenty eighth": 28,
    "twenty ninth": 29,
    "thirtieth": 30,
    "thirty first": 31,
}

MONTH_ALIASES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass
class DialogResult:
    messages: list[str]
    done: bool = False


@dataclass
class OfferBrowseIntent:
    request_more: bool = False
    sort: OfferSort | None = None
    require_refundable: bool | None = None
    require_cabin_bag: bool | None = None
    require_checked_bag: bool | None = None
    reset_filters: bool = False
    mentioned: bool = False


class DialogManager:
    REQUIRED_ORDER = ["trip_type", "origin", "destination", "depart_date", "return_date", "passengers"]

    SLOT_PROMPTS = {
        "trip_type": "Is this a one-way or round-trip flight?",
        "origin": "Where are you flying from? City, airport name, or code all work (example: Dallas, DFW).",
        "destination": "Where are you flying to? City, airport name, or code all work (example: Seattle, SEA).",
        "depart_date": "What is your departure date? You can say 2026-04-10, April 10, 04/10, or 'April tenth twenty twenty six'.",
        "return_date": "What is your return date? You can say it in numbers or words.",
        "passengers": "How many adult passengers are traveling?",
    }

    def __init__(self, provider: FlightProvider, llm_client: LLMClient | None = None) -> None:
        self.provider = provider
        self.llm_client = llm_client

    def opening_message(self, state: SessionState) -> str:
        next_slot = self._next_missing_required_slot(state.trip_request)
        intro = "I can help you find mock flight offers and complete a mock booking. You can say 'go back' anytime to correct the previous answer."
        question = self.SLOT_PROMPTS.get(next_slot, "Tell me about your trip.")
        return f"{intro} {question}"

    def handle_user_text(self, text: str, state: SessionState) -> DialogResult:
        cleaned = text.strip()
        state.add_turn("user", cleaned)

        if cleaned.lower() in {"quit", "exit", "stop"}:
            state.phase = ConversationPhase.CANCELLED
            return DialogResult(messages=["Session ended without booking."], done=True)

        if state.phase == ConversationPhase.COLLECTING_REQUIREMENTS:
            return self._handle_collecting(cleaned, state)
        if state.phase == ConversationPhase.AWAITING_SELECTION:
            return self._handle_selection(cleaned, state)
        if state.phase == ConversationPhase.AWAITING_CONFIRMATION:
            return self._handle_confirmation(cleaned, state)
        if state.phase in {ConversationPhase.COMPLETED, ConversationPhase.CANCELLED}:
            return DialogResult(messages=["Session already complete."], done=True)

        return DialogResult(messages=["I could not process that. Please try again."])

    def _handle_collecting(self, text: str, state: SessionState) -> DialogResult:
        if self._is_go_back_request(text):
            return self._go_back_one_question(state)

        next_slot = self._next_missing_required_slot(state.trip_request)
        updates = self._extract_slot_updates(text, state.trip_request, next_slot)

        if self._looks_like_help_request(text) and not updates:
            missing = state.trip_request.required_missing_slots()
            if not missing:
                return DialogResult(messages=["I already have the required details. Say 'search flights' to continue."])
            label = ", ".join(missing)
            return DialogResult(messages=[f"I still need: {label}. {self.SLOT_PROMPTS.get(missing[0], 'Please share the next detail.')}" ])

        validation_error = self._apply_updates(state, updates)
        if validation_error:
            return DialogResult(messages=[validation_error])

        missing = state.trip_request.required_missing_slots()
        if missing:
            slot = self._next_missing_required_slot(state.trip_request)
            return DialogResult(messages=[self.SLOT_PROMPTS.get(slot, "Please provide the next trip detail.")])

        if not state.preferences_prompted and not self._has_any_optional_preference(state.trip_request):
            if self._looks_like_skip_preferences(text):
                state.preferences_prompted = True
                return self._search_and_present_offers(state, reset_search=True)

            state.preferences_prompted = True
            return DialogResult(
                messages=[
                    "Any optional preferences before I search: cabin, nonstop, max stops, budget, or time window? You can also say 'skip'."
                ]
            )

        return self._search_and_present_offers(state, reset_search=True)

    def _handle_selection(self, text: str, state: SessionState) -> DialogResult:
        if self._is_go_back_request(text):
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return self._go_back_one_question(state)

        selection = parse_offer_selection(text, max_options=len(state.offers_shown))
        if selection == 0:
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return DialogResult(messages=["No option selected. Tell me what to change, or ask for more/cheaper flights."])

        if selection is not None:
            selected_offer = state.offers_shown[selection - 1]
            state.selected_offer_id = selected_offer.offer_id
            state.phase = ConversationPhase.AWAITING_CONFIRMATION
            return DialogResult(messages=[booking_readback(state.trip_request, selected_offer)])

        intent = self._parse_offer_browse_intent(text)
        if intent.mentioned:
            return self._handle_offer_browse_intent(intent, state)

        trip_updates = self._extract_slot_updates(text, state.trip_request, None)
        if trip_updates:
            validation_error = self._apply_updates(state, trip_updates)
            if validation_error:
                return DialogResult(messages=[validation_error])
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return self._search_and_present_offers(state, reset_search=True)

        return DialogResult(
            messages=[
                "You can choose option 1/2/3, ask for cheaper or faster flights, ask for flights with bags included, or say none."
            ]
        )

    def _handle_confirmation(self, text: str, state: SessionState) -> DialogResult:
        if self._is_go_back_request(text):
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return self._go_back_one_question(state)

        selection = parse_offer_selection(text, max_options=len(state.offers_shown))
        if selection is not None and selection > 0:
            selected_offer = state.offers_shown[selection - 1]
            state.selected_offer_id = selected_offer.offer_id
            return DialogResult(messages=[booking_readback(state.trip_request, selected_offer)])

        decision = parse_yes_no(text)
        if decision is True:
            selected_offer = state.get_selected_offer()
            can_book, reason = can_attempt_booking(has_selection=(selected_offer is not None), confirmation_text=text)
            if not can_book:
                return DialogResult(messages=[reason])
            if selected_offer is None:
                state.phase = ConversationPhase.AWAITING_SELECTION
                return DialogResult(messages=["No selected offer found. Please choose an option again."])

            result = self.provider.book_offer(selected_offer, state.trip_request)
            state.booking_result = result
            if result.success:
                state.phase = ConversationPhase.COMPLETED
                return DialogResult(
                    messages=[
                        f"Booking confirmed. Reference: {result.booking_reference}. Provider: {result.provider}. {result.message}"
                    ],
                    done=True,
                )
            state.phase = ConversationPhase.AWAITING_SELECTION
            return DialogResult(messages=[f"Booking failed: {result.message}. Please choose another option."])

        if decision is False:
            state.phase = ConversationPhase.AWAITING_SELECTION
            return DialogResult(messages=["Booking cancelled. Pick another option or ask for different flights."])

        intent = self._parse_offer_browse_intent(text)
        if intent.mentioned:
            state.phase = ConversationPhase.AWAITING_SELECTION
            return self._handle_offer_browse_intent(intent, state)

        trip_updates = self._extract_slot_updates(text, state.trip_request, None)
        if trip_updates:
            validation_error = self._apply_updates(state, trip_updates)
            if validation_error:
                return DialogResult(messages=[validation_error])
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return self._search_and_present_offers(state, reset_search=True)

        return DialogResult(messages=["Please say yes/no, pick another option, or tell me what to change."])

    def _handle_offer_browse_intent(self, intent: OfferBrowseIntent, state: SessionState) -> DialogResult:
        if not state.all_offers:
            return self._search_and_present_offers(state, reset_search=True)

        if intent.reset_filters:
            self._reset_offer_preferences(state)

        if intent.sort is not None:
            state.offer_sort = intent.sort
        if intent.require_refundable is not None:
            state.offer_require_refundable = intent.require_refundable
        if intent.require_cabin_bag is not None:
            state.offer_require_cabin_bag = intent.require_cabin_bag
        if intent.require_checked_bag is not None:
            state.offer_require_checked_bag = intent.require_checked_bag

        if intent.request_more and intent.sort is None and not intent.reset_filters:
            return self._present_offer_page(state, next_page=True)

        return self._present_offer_page(state, next_page=False)

    def _search_and_present_offers(self, state: SessionState, reset_search: bool) -> DialogResult:
        if reset_search or not state.all_offers:
            state.all_offers = self.provider.search_offers(state.trip_request)
            state.offer_cursor = 0
            state.selected_offer_id = None

        if not state.all_offers:
            state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
            return DialogResult(messages=["No offers found. Please adjust your dates, route, or budget."])

        state.phase = ConversationPhase.AWAITING_SELECTION
        return self._present_offer_page(state, next_page=False)

    def _present_offer_page(self, state: SessionState, next_page: bool) -> DialogResult:
        ranked = self._rank_filtered_offers(state)
        if not ranked:
            return DialogResult(
                messages=[
                    "No flights match that filter. You can say 'show all flights' or relax conditions like bag/refundable requirements."
                ]
            )

        page_size = 3
        wrapped = False
        start = state.offer_cursor + page_size if next_page else 0
        if start >= len(ranked):
            start = 0
            wrapped = next_page

        state.offer_cursor = start
        shown = ranked[start : start + page_size]
        state.offers_shown = shown

        heading = (
            "I do not have more flights matching those filters. Here are the best matching options again:"
            if wrapped
            else self._offer_heading(state, next_page)
        )
        messages = [heading]
        for idx, offer in enumerate(shown, start=1):
            messages.append(self._format_offer_line(idx, offer, state.offer_sort))

        option_list = "/".join(str(i) for i in range(1, len(shown) + 1))
        if len(ranked) > page_size:
            remaining = max(0, len(ranked) - (start + page_size))
            messages.append(
                f"Say option {option_list} to pick, 'more flights' for more options, or ask for cheaper/faster/fewer stops/bag/refundable flights. ({remaining} more match this filter)"
            )
        else:
            messages.append(
                f"Say option {option_list} to pick, or ask for cheaper/faster/fewer stops/bag/refundable flights."
            )

        return DialogResult(messages=messages)

    def _rank_filtered_offers(self, state: SessionState) -> list[Any]:
        filtered: list[Any] = []
        for offer in state.all_offers:
            if state.offer_require_refundable and not offer.refundable:
                continue
            if state.offer_require_cabin_bag is True and not offer.cabin_bag_included:
                continue
            if state.offer_require_cabin_bag is False and offer.cabin_bag_included:
                continue
            if state.offer_require_checked_bag is True and not offer.checked_bag_included:
                continue
            if state.offer_require_checked_bag is False and offer.checked_bag_included:
                continue
            filtered.append(offer)

        if state.offer_sort == "cheapest":
            return sorted(filtered, key=lambda o: (o.price_usd, o.stops, o.duration_minutes))
        if state.offer_sort == "fastest":
            return sorted(filtered, key=lambda o: (o.duration_minutes, o.stops, o.price_usd))
        if state.offer_sort == "fewest_stops":
            return sorted(filtered, key=lambda o: (o.stops, o.duration_minutes, o.price_usd))
        if state.offer_sort == "bag_friendly":
            return sorted(
                filtered,
                key=lambda o: (
                    o.price_usd + (0 if o.checked_bag_included else o.checked_bag_fee_usd) + (0 if o.cabin_bag_included else 25),
                    o.stops,
                    o.duration_minutes,
                ),
            )
        return sorted(filtered, key=lambda o: (o.stops, o.duration_minutes, o.price_usd))

    def _offer_heading(self, state: SessionState, next_page: bool) -> str:
        if next_page:
            return "Here are more flight options:"

        sort_text = {
            "balanced": "best overall options",
            "cheapest": "cheaper options",
            "fastest": "faster options",
            "fewest_stops": "options with fewer stops",
            "bag_friendly": "bag-friendly options",
        }[state.offer_sort]
        return f"I found {sort_text}:"

    def _format_offer_line(self, idx: int, offer: Any, sort_mode: OfferSort) -> str:
        bag_summary = (
            "cabin bag included" if offer.cabin_bag_included else "cabin bag extra"
        ) + ", " + (
            "checked bag included" if offer.checked_bag_included else f"checked bag +${offer.checked_bag_fee_usd:.0f}"
        )

        ranking_note = {
            "balanced": "balanced",
            "cheapest": "price-first",
            "fastest": "time-first",
            "fewest_stops": "stop-first",
            "bag_friendly": "bag-total-first",
        }[sort_mode]

        return (
            f"Option {idx}: ${offer.price_usd:.2f}, {offer.stops} stop(s), depart {offer.depart_time_local}, "
            f"duration {offer.duration_minutes} min, refundable={'yes' if offer.refundable else 'no'}, "
            f"bags: {bag_summary} ({ranking_note})."
        )

    def _apply_updates(self, state: SessionState, updates: dict[str, Any]) -> str | None:
        if not updates:
            return None

        payload = state.trip_request.model_dump()
        payload.update(updates)

        try:
            state.trip_request = TripRequest(**payload)
            logger.info("Updated slots: %s", updates)
            return None
        except ValidationError as exc:
            return f"I could not apply that update: {exc.errors()[0]['msg']}."
        except ValueError as exc:
            return f"I could not apply that update: {exc}."

    def _next_missing_required_slot(self, trip_request: TripRequest) -> str | None:
        missing = trip_request.required_missing_slots()
        if not missing:
            return None

        for slot in self.REQUIRED_ORDER:
            if slot in missing:
                if slot == "return_date" and trip_request.trip_type != "round_trip":
                    continue
                return slot
        return missing[0]

    def _extract_slot_updates(self, text: str, current: TripRequest, next_slot: str | None) -> dict[str, Any]:
        llm_updates: dict[str, Any] = {}
        if self.llm_client and self.llm_client.enabled:
            llm_updates = self.llm_client.interpret_slot_updates(text, current)

        rule_updates = self._extract_slot_updates_rules(text, current)
        # If deterministic rules already extracted something for this turn,
        # prefer them and ignore LLM slot updates to avoid noisy cross-slot overwrites.
        if rule_updates:
            llm_updates = {}
        if next_slot:
            rule_updates.update(self._capture_contextual_slot_input(text, next_slot, rule_updates))

        merged = {**llm_updates, **rule_updates}
        return self._normalize_slot_updates(merged)

    def _capture_contextual_slot_input(
        self,
        text: str,
        next_slot: str,
        existing_updates: dict[str, Any],
    ) -> dict[str, Any]:
        if next_slot in existing_updates:
            return {}

        normalized = text.strip().lower()
        if not normalized or normalized in {"skip", "none", "no preference"}:
            return {}

        if next_slot in {"origin", "destination"}:
            if re.search(r"\bfrom\b|\bto\b", normalized):
                return {}
            if re.fullmatch(r"\d+", normalized):
                return {}
            cleaned = self._clean_place(text)
            if cleaned:
                return {next_slot: cleaned}

        if next_slot in {"depart_date", "return_date"}:
            parsed_dates = self._extract_date_candidates(text)
            if parsed_dates:
                return {next_slot: parsed_dates[0]}

        if next_slot == "passengers":
            passengers = self._extract_passenger_count(normalized)
            if passengers is not None:
                return {"passengers": passengers}

        if next_slot == "trip_type":
            trip_type = self._extract_trip_type(normalized)
            if trip_type:
                return {"trip_type": trip_type}

        return {}

    def _extract_slot_updates_rules(self, text: str, current: TripRequest) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        normalized = text.strip().lower()

        trip_type = self._extract_trip_type(normalized)
        if trip_type:
            updates["trip_type"] = trip_type

        route1 = re.search(
            r"from\s+([a-zA-Z0-9 .'/&-]+?)\s+to\s+([a-zA-Z0-9 .'/&-]+?)(?:\s+on\s+|\s+for\s+|$)",
            text,
            re.IGNORECASE,
        )
        route2 = re.search(
            r"to\s+([a-zA-Z0-9 .'/&-]+?)\s+from\s+([a-zA-Z0-9 .'/&-]+?)(?:\s+on\s+|\s+for\s+|$)",
            text,
            re.IGNORECASE,
        )
        route3 = re.search(
            r"^\s*([a-zA-Z0-9 .'/&-]{2,}?)\s+to\s+([a-zA-Z0-9 .'/&-]{2,}?)(?:\s+on\s+|\s+for\s+|$)",
            text,
            re.IGNORECASE,
        )

        if route1:
            updates["origin"] = self._clean_place(route1.group(1))
            updates["destination"] = self._clean_place(route1.group(2))
        elif route2:
            updates["destination"] = self._clean_place(route2.group(1))
            updates["origin"] = self._clean_place(route2.group(2))
        elif route3 and "from " not in normalized:
            updates["origin"] = self._clean_place(route3.group(1))
            updates["destination"] = self._clean_place(route3.group(2))

        origin_match = re.search(r"\bfrom\s+([a-zA-Z0-9 .'/&-]+)$", text, re.IGNORECASE)
        if origin_match and "origin" not in updates and "to" not in normalized:
            updates["origin"] = self._clean_place(origin_match.group(1))

        destination_match = re.search(r"\bto\s+([a-zA-Z0-9 .'/&-]+)$", text, re.IGNORECASE)
        if destination_match and "destination" not in updates and "from" not in normalized:
            updates["destination"] = self._clean_place(destination_match.group(1))

        parsed_dates = self._extract_date_candidates(text)
        if parsed_dates:
            current_trip_type = updates.get("trip_type") or current.trip_type
            if len(parsed_dates) >= 2 and current_trip_type == "round_trip":
                updates.setdefault("depart_date", parsed_dates[0])
                updates.setdefault("return_date", parsed_dates[1])
            else:
                if re.search(r"\b(return|back)\b", normalized):
                    updates.setdefault("return_date", parsed_dates[-1])
                elif current.trip_type == "round_trip" and current.depart_date and not current.return_date:
                    updates.setdefault("return_date", parsed_dates[0])
                else:
                    updates.setdefault("depart_date", parsed_dates[0])

        passengers = self._extract_passenger_count(normalized)
        if passengers is not None:
            updates["passengers"] = passengers

        cabin = self._extract_cabin(normalized)
        if cabin:
            updates["cabin"] = cabin

        if re.search(r"\b(non\s?stop|direct)\b", normalized):
            if re.search(r"\b(no|not|without)\s+(non\s?stop|direct)\b", normalized):
                updates["nonstop_preference"] = False
            else:
                updates["nonstop_preference"] = True
                updates.setdefault("max_stops", 0)

        max_stops = self._extract_max_stops(normalized)
        if max_stops is not None:
            updates["max_stops"] = max_stops

        budget = self._extract_budget(normalized)
        if budget is not None:
            updates["budget_usd"] = budget

        time_window = self._extract_time_window(normalized)
        if time_window:
            updates["time_window"] = time_window

        if normalized in {"skip", "no preference", "none"}:
            return {}

        return updates

    def _parse_offer_browse_intent(self, text: str) -> OfferBrowseIntent:
        normalized = text.strip().lower()
        intent = OfferBrowseIntent()

        if not normalized:
            return intent

        if re.search(r"\b(show all|reset|start over|any flight|all flights)\b", normalized):
            intent.mentioned = True
            intent.reset_filters = True

        if re.search(r"\b(more|next|another|other options|other flights|more flights)\b", normalized):
            intent.mentioned = True
            intent.request_more = True

        if re.search(r"\b(cheap|cheaper|lowest|low cost|budget)\b", normalized):
            intent.mentioned = True
            intent.sort = "cheapest"

        if re.search(r"\b(fastest|quickest|shortest)\b", normalized):
            intent.mentioned = True
            intent.sort = "fastest"

        if re.search(r"\b(nonstop|direct|fewer stops|fewest stops|least stops|less stops)\b", normalized):
            intent.mentioned = True
            intent.sort = "fewest_stops"

        if re.search(r"\b(refundable|flexible|flex fare)\b", normalized):
            intent.mentioned = True
            intent.require_refundable = True
        if re.search(r"\b(non refundable|non-refundable|not refundable)\b", normalized):
            intent.mentioned = True
            intent.require_refundable = False

        has_cabin_bag = re.search(r"\b(cabin bag|carry on|carry-on)\b", normalized)
        has_checked_bag = re.search(r"\b(checked bag|check in bag|check-in bag|luggage)\b", normalized)

        if has_cabin_bag:
            intent.mentioned = True
            if re.search(r"\b(without|no)\s+(cabin bag|carry on|carry-on)\b", normalized):
                intent.require_cabin_bag = False
            else:
                intent.require_cabin_bag = True

        if has_checked_bag:
            intent.mentioned = True
            if re.search(r"\b(without|no)\s+(checked bag|check in bag|check-in bag|luggage)\b", normalized):
                intent.require_checked_bag = False
            else:
                intent.require_checked_bag = True

        if (has_cabin_bag or has_checked_bag) and re.search(r"\b(cheap|cheaper|lowest|low cost|budget)\b", normalized):
            intent.sort = "bag_friendly"

        return intent

    def _extract_date_candidates(self, text: str) -> list[str]:
        normalized = text.lower()
        parsed: list[str] = []
        today = date.today()

        for match in re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", normalized):
            try:
                datetime.strptime(match, "%Y-%m-%d")
                parsed.append(match)
            except ValueError:
                continue

        spaced_iso_matches = re.findall(r"\b(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\b", normalized)
        for year_s, month_s, day_s in spaced_iso_matches:
            try:
                dt = date(int(year_s), int(month_s), int(day_s))
                parsed.append(dt.strftime("%Y-%m-%d"))
            except ValueError:
                continue

        slash_matches = re.findall(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", normalized)
        for month_s, day_s, year_s in slash_matches:
            month = int(month_s)
            day_num = int(day_s)
            year = int(year_s) if year_s else today.year
            if year < 100:
                year += 2000
            try:
                dt = date(year, month, day_num)
                parsed.append(dt.strftime("%Y-%m-%d"))
            except ValueError:
                continue

        months = "|".join(MONTH_ALIASES.keys())
        month_day_pattern = re.compile(rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b", re.IGNORECASE)
        for month, day_s, year_s in month_day_pattern.findall(text):
            candidate_year = int(year_s) if year_s else today.year
            raw = f"{month} {day_s} {candidate_year}"
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    dt = datetime.strptime(raw, fmt).date()
                    parsed.append(dt.strftime("%Y-%m-%d"))
                    break
                except ValueError:
                    continue

        # Voice/STT-friendly month/day parsing for utterances like:
        # "april tenth twenty twenty six", "the tenth of april", "ten april 2026"
        token_stream = re.findall(r"[a-z0-9]+", normalized)
        for idx, token in enumerate(token_stream):
            if token not in MONTH_ALIASES:
                continue
            month_num = MONTH_ALIASES[token]

            # month-first phrase: "<month> <day phrase> [year phrase]"
            day_val: int | None = None
            day_tokens_used = 0
            for width in (3, 2, 1):
                phrase_tokens = token_stream[idx + 1 : idx + 1 + width]
                if not phrase_tokens:
                    continue
                if width > 1 and len(phrase_tokens) >= 2:
                    first_day = self._parse_number_phrase(phrase_tokens[0])
                    second_token = phrase_tokens[1]
                    if (
                        first_day is not None
                        and 1 <= first_day <= 31
                        and (
                            second_token in {"nineteen", "twenty", "two", "thousand"}
                            or re.fullmatch(r"\d{4}", second_token)
                        )
                    ):
                        continue
                phrase = " ".join(phrase_tokens)
                maybe_day = self._parse_number_phrase(phrase)
                if maybe_day is not None and 1 <= maybe_day <= 31:
                    day_val = maybe_day
                    day_tokens_used = width
                    break

            # day-first phrase: "<day phrase> of <month>" or "<day phrase> <month>"
            if day_val is None:
                lookback = token_stream[max(0, idx - 4) : idx]
                cleaned_lookback = [t for t in lookback if t not in {"the", "of"}]
                for width in (3, 2, 1):
                    phrase_tokens = cleaned_lookback[-width:]
                    if not phrase_tokens:
                        continue
                    phrase = " ".join(phrase_tokens)
                    maybe_day = self._parse_number_phrase(phrase)
                    if maybe_day is not None and 1 <= maybe_day <= 31:
                        day_val = maybe_day
                        break

            if day_val is None:
                continue

            # Parse optional year tokens after month + day tokens.
            year_start = idx + 1 + day_tokens_used
            year_tokens = token_stream[year_start : year_start + 5]
            year_val = self._parse_spoken_year_tokens(year_tokens)
            if year_val is None:
                year_val = today.year

            try:
                dt = date(year_val, month_num, day_val)
                parsed.append(dt.strftime("%Y-%m-%d"))
            except ValueError:
                continue

        if "today" in normalized:
            parsed.append(today.strftime("%Y-%m-%d"))
        if "day after tomorrow" in normalized:
            parsed.append((today + timedelta(days=2)).strftime("%Y-%m-%d"))
        elif "tomorrow" in normalized:
            parsed.append((today + timedelta(days=1)).strftime("%Y-%m-%d"))

        for weekday_name, weekday_idx in WEEKDAYS.items():
            if f"next {weekday_name}" in normalized:
                delta = (weekday_idx - today.weekday()) % 7
                delta = 7 if delta == 0 else delta
                parsed.append((today + timedelta(days=delta)).strftime("%Y-%m-%d"))

        deduped: list[str] = []
        seen: set[str] = set()
        for value in parsed:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    def _parse_number_phrase(self, phrase: str) -> int | None:
        cleaned = phrase.strip().lower().replace("-", " ")
        cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return None

        if cleaned.isdigit():
            return int(cleaned)

        if cleaned in ORDINAL_WORDS:
            return ORDINAL_WORDS[cleaned]

        tokens = cleaned.split()
        # Handle STT-style digit words: "two zero two six", "oh five".
        if tokens and all(token in WORD_NUMBERS for token in tokens):
            if len(tokens) >= 3:
                digits = "".join(str(WORD_NUMBERS[token]) for token in tokens)
                return int(digits)
            if len(tokens) == 2 and tokens[0] in {"zero", "oh", "o"}:
                return WORD_NUMBERS[tokens[1]]

        total = 0
        current = 0
        used_any = False

        for token in tokens:
            if token in ORDINAL_WORDS:
                current += ORDINAL_WORDS[token]
                used_any = True
                continue
            if token in CARDINAL_WORDS:
                val = CARDINAL_WORDS[token]
                if val >= 20 and val % 10 == 0:
                    # twenty + six
                    if current and current < 20:
                        current += val
                    else:
                        current = current + val
                else:
                    current += val
                used_any = True
                continue
            if token == "hundred":
                current = (current or 1) * 100
                used_any = True
                continue
            if token == "thousand":
                current = (current or 1) * 1000
                total += current
                current = 0
                used_any = True
                continue
            if token == "and":
                continue
            return None

        if not used_any:
            return None
        return total + current

    def _parse_spoken_year_tokens(self, tokens: list[str]) -> int | None:
        if not tokens:
            return None

        # Prefer explicit 4-digit year in nearby tokens.
        for token in tokens:
            if re.fullmatch(r"\d{4}", token):
                value = int(token)
                if 1900 <= value <= 2100:
                    return value

        phrase = " ".join(tokens).strip()
        if not phrase:
            return None

        # "twenty twenty six" => 2026, "twenty nineteen" => 2019
        if tokens[0] == "twenty" and len(tokens) >= 2:
            suffix = self._parse_number_phrase(" ".join(tokens[1:]))
            if suffix is not None and 0 <= suffix <= 99:
                return 2000 + suffix

        # "two thousand twenty six"
        value = self._parse_number_phrase(phrase)
        if value is None:
            return None

        if 1900 <= value <= 2100:
            return value
        if 0 <= value <= 99:
            return 2000 + value
        return None

    def _extract_trip_type(self, normalized: str) -> str | None:
        if re.search(r"\bround[\W_]*trip\b|\breturn[\W_]*trip\b|\breturn[\W_]*flight\b", normalized):
            return "round_trip"
        if re.search(r"\bone[\W_]*way\b|\bsingle[\W_]*trip\b|\boneway\b", normalized):
            return "one_way"
        return None

    def _extract_passenger_count(self, normalized: str) -> int | None:
        if re.search(r"\bjust me\b", normalized):
            return 1

        pax_digits = re.search(r"\b(\d+)\s*(adult|adults|passenger|passengers|people|person)\b", normalized)
        if pax_digits:
            return int(pax_digits.group(1))

        bare_digits = re.fullmatch(r"\s*(\d+)\s*", normalized)
        if bare_digits:
            return int(bare_digits.group(1))

        for word, value in WORD_NUMBERS.items():
            if re.search(rf"\b{word}\s*(adult|adults|passenger|passengers|people|person)\b", normalized):
                return value

        fallback_for = re.search(r"\bfor\s+(\d+)\b", normalized)
        if fallback_for:
            return int(fallback_for.group(1))

        return None

    def _extract_cabin(self, normalized: str) -> str | None:
        if re.search(r"\b(premium economy|premium)\b", normalized):
            return "premium_economy"
        if re.search(r"\b(business|biz|business class)\b", normalized):
            return "business"
        if re.search(r"\b(first|first class)\b", normalized):
            return "first"
        if re.search(r"\b(economy|coach|main cabin)\b", normalized):
            return "economy"
        return None

    def _extract_max_stops(self, normalized: str) -> int | None:
        direct = re.search(r"\bnon\s?stop|direct\b", normalized)
        if direct and not re.search(r"\b(no|not|without)\s+(non\s?stop|direct)\b", normalized):
            return 0

        max_stops = re.search(r"\b(?:max(?:imum)?|up to)?\s*(\d)\s*stop", normalized)
        if max_stops:
            value = int(max_stops.group(1))
            if value in (0, 1, 2):
                return value

        return None

    def _extract_budget(self, normalized: str) -> int | None:
        budget = re.search(r"\$\s*(\d+)", normalized) or re.search(r"\b(\d+)\s*usd\b", normalized)
        if budget:
            return int(budget.group(1))

        budget_alt = re.search(r"\b(?:under|below|less than|max|at most|up to)\s+(\d+)\b", normalized)
        if budget_alt:
            return int(budget_alt.group(1))

        return None

    def _extract_time_window(self, normalized: str) -> str | None:
        if re.search(r"\bmorning\b", normalized):
            return "morning"
        if re.search(r"\bafternoon\b", normalized):
            return "afternoon"
        if re.search(r"\b(evening|night|red eye|red-eye)\b", normalized):
            return "evening"
        if re.search(r"\b(anytime|any time|no time preference|time doesn.t matter|time does not matter)\b", normalized):
            return "any"
        return None

    def _looks_like_help_request(self, text: str) -> bool:
        normalized = text.strip().lower()
        return bool(re.search(r"\b(help|what do you need|what next|not sure|how do i answer)\b", normalized))

    def _looks_like_skip_preferences(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {"skip", "none", "no preference", "no preferences", "anything is fine"}

    def _has_any_optional_preference(self, trip_request: TripRequest) -> bool:
        return any(
            [
                trip_request.cabin != "economy",
                trip_request.nonstop_preference is not None,
                trip_request.max_stops is not None,
                trip_request.budget_usd is not None,
                trip_request.time_window is not None,
            ]
        )

    def _reset_offer_preferences(self, state: SessionState) -> None:
        state.offer_sort = "balanced"
        state.offer_require_refundable = False
        state.offer_require_cabin_bag = None
        state.offer_require_checked_bag = None
        state.offer_cursor = 0

    def _normalize_slot_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in updates.items():
            if value is None:
                continue

            if key == "trip_type":
                trip_type = self._extract_trip_type(str(value).strip().lower())
                if trip_type:
                    normalized[key] = trip_type
                continue

            if key in {"origin", "destination"}:
                cleaned = self._clean_place(str(value))
                if cleaned:
                    normalized[key] = cleaned
                continue

            if key in {"depart_date", "return_date"}:
                parsed = self._extract_date_candidates(str(value))
                if parsed:
                    normalized[key] = parsed[0]
                else:
                    normalized[key] = str(value).strip()
                continue

            if key == "passengers":
                if isinstance(value, int):
                    normalized[key] = value
                else:
                    count = self._extract_passenger_count(str(value).strip().lower())
                    if count is not None:
                        normalized[key] = count
                continue

            if key == "cabin":
                cabin = self._extract_cabin(str(value).strip().lower())
                if cabin:
                    normalized[key] = cabin
                continue

            if key == "nonstop_preference":
                if isinstance(value, bool):
                    normalized[key] = value
                else:
                    lowered = str(value).strip().lower()
                    if lowered in {"yes", "true", "1"}:
                        normalized[key] = True
                    elif lowered in {"no", "false", "0"}:
                        normalized[key] = False
                continue

            if key == "max_stops":
                try:
                    stops = int(value)
                    if stops in (0, 1, 2):
                        normalized[key] = stops
                except (TypeError, ValueError):
                    extracted = self._extract_max_stops(str(value).strip().lower())
                    if extracted is not None:
                        normalized[key] = extracted
                continue

            if key == "budget_usd":
                try:
                    normalized[key] = int(value)
                except (TypeError, ValueError):
                    extracted = self._extract_budget(str(value).strip().lower())
                    if extracted is not None:
                        normalized[key] = extracted
                continue

            if key == "time_window":
                lowered = str(value).strip().lower()
                extracted = self._extract_time_window(lowered)
                if extracted:
                    normalized[key] = extracted
                continue

            normalized[key] = value
        return normalized

    def _is_go_back_request(self, text: str) -> bool:
        normalized = text.strip().lower()
        return bool(re.search(r"\b(go back|back up|previous|last answer|undo)\b", normalized))

    def _go_back_one_question(self, state: SessionState) -> DialogResult:
        required_slots = self._required_slots_for_current_trip(state.trip_request)
        first_missing = self._next_missing_required_slot(state.trip_request)

        if first_missing is None:
            target_slot = required_slots[-1]
        else:
            idx = required_slots.index(first_missing)
            if idx == 0:
                return DialogResult(messages=[self.SLOT_PROMPTS["trip_type"]])
            target_slot = required_slots[idx - 1]

        payload = state.trip_request.model_dump()
        payload[target_slot] = None
        if target_slot in {"trip_type", "depart_date"}:
            payload["return_date"] = None

        state.trip_request = TripRequest(**payload)
        state.phase = ConversationPhase.COLLECTING_REQUIREMENTS
        state.selected_offer_id = None
        state.offers_shown = []
        state.all_offers = []
        state.preferences_prompted = False
        return DialogResult(messages=[f"Okay, let's correct that. {self.SLOT_PROMPTS[target_slot]}"])

    def _required_slots_for_current_trip(self, trip_request: TripRequest) -> list[str]:
        slots = ["trip_type", "origin", "destination", "depart_date"]
        if trip_request.trip_type == "round_trip":
            slots.append("return_date")
        slots.append("passengers")
        return slots

    @staticmethod
    def _clean_place(value: str) -> str:
        compact = re.sub(r"\s+", " ", value.strip(" .,"))
        return normalize_location_text(compact)
