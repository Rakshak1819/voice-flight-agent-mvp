from src.core.dialog_manager import DialogManager
from src.core.state import ConversationPhase, SessionState
from src.providers.mock_provider import MockFlightProvider


def test_slot_filling_and_offer_flow() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("round trip", state)
    manager.handle_user_text("from Boston to Seattle", state)
    manager.handle_user_text("2026-04-10", state)
    manager.handle_user_text("2026-04-15", state)

    result = manager.handle_user_text("2 adults", state)
    assert state.phase == ConversationPhase.COLLECTING_REQUIREMENTS
    assert "optional preferences" in result.messages[0].lower()

    result = manager.handle_user_text("skip", state)
    assert state.phase == ConversationPhase.AWAITING_SELECTION
    assert len(state.offers_shown) == 3
    assert "option 1" in " ".join(result.messages).lower()


def test_correction_updates_depart_date() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text(
        "one way from New York to Miami on 2026-05-01 for 1 adult",
        state,
    )

    # Optional prompt then search
    manager.handle_user_text("skip", state)
    assert state.phase == ConversationPhase.AWAITING_SELECTION

    manager.handle_user_text("actually make it 2026-05-02", state)
    assert state.trip_request.depart_date == "2026-05-02"
    assert state.phase == ConversationPhase.AWAITING_SELECTION


def test_keyboard_short_answers_fill_origin_destination() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("Dallas", state)
    manager.handle_user_text("Seattle", state)

    assert state.trip_request.origin == "Dallas"
    assert state.trip_request.destination == "Seattle"


def test_natural_one_way_input_parses_multiple_slots() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text(
        "I need a one-way flight from DFW to Seattle-Tacoma International Airport on 04/10 for two adults in coach under 500 in the morning",
        state,
    )

    assert state.trip_request.trip_type == "one_way"
    assert state.trip_request.origin == "Dallas/Fort Worth (DFW)"
    assert state.trip_request.destination == "Seattle-Tacoma (SEA)"
    assert state.trip_request.depart_date.endswith("-04-10")
    assert state.trip_request.passengers == 2
    assert state.trip_request.cabin == "economy"
    assert state.trip_request.budget_usd == 500
    assert state.trip_request.time_window == "morning"


def test_offer_refinement_cheaper_and_more() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text(
        "one-way from Boston to Seattle on 2026-04-10 for 1 adult",
        state,
    )
    manager.handle_user_text("skip", state)
    assert state.phase == ConversationPhase.AWAITING_SELECTION
    first_page_offer_ids = [offer.offer_id for offer in state.offers_shown]

    result = manager.handle_user_text("show me cheaper flights with checked bag", state)
    assert state.phase == ConversationPhase.AWAITING_SELECTION
    assert "options" in result.messages[0].lower()
    assert state.offer_sort == "bag_friendly"
    assert state.offer_require_checked_bag is True

    result = manager.handle_user_text("more flights", state)
    assert state.phase == ConversationPhase.AWAITING_SELECTION
    heading = result.messages[0].lower()
    assert "more flight options" in heading or "do not have more flights" in heading
    second_page_offer_ids = [offer.offer_id for offer in state.offers_shown]

    if "more flight options" in heading:
        assert second_page_offer_ids != first_page_offer_ids


def test_spoken_date_phrase_parses_for_departure() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("DFW", state)
    manager.handle_user_text("SEA", state)
    manager.handle_user_text("April tenth twenty twenty six", state)

    assert state.trip_request.depart_date == "2026-04-10"


def test_spoken_round_trip_dates_parse_both_slots() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text(
        "round trip from Boston to Seattle leaving the tenth of April 2026 and returning April twentieth twenty twenty six for one adult",
        state,
    )

    assert state.trip_request.depart_date == "2026-04-10"
    assert state.trip_request.return_date == "2026-04-20"


def test_go_back_rewinds_previous_required_question() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("Dallas", state)
    manager.handle_user_text("Seattle", state)

    result = manager.handle_user_text("go back", state)
    assert "correct that" in result.messages[0].lower()
    assert state.trip_request.destination is None
    assert state.trip_request.origin == "Dallas"

    manager.handle_user_text("Portland", state)
    assert state.trip_request.destination == "Portland"


def test_trip_type_parses_speech_punctuation_variant() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("One. Way.", state)
    assert state.trip_request.trip_type == "one_way"


class _FakeLLMClient:
    enabled = True

    def interpret_slot_updates(self, utterance, current_trip):  # type: ignore[no-untyped-def]
        return {"trip_type": "one way"}


def test_llm_trip_type_value_is_normalized() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=_FakeLLMClient())
    state = SessionState(session_id="test_session")

    result = manager.handle_user_text("one way", state)
    assert state.trip_request.trip_type == "one_way"
    assert "flying from" in result.messages[0].lower()


class _NoisyLLMClient:
    enabled = True

    def interpret_slot_updates(self, utterance, current_trip):  # type: ignore[no-untyped-def]
        return {"trip_type": "one way", "cabin": "economy"}


def test_confirmation_yes_not_overridden_by_llm_slot_updates() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=_NoisyLLMClient())
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way from DFW to SEA on 2026-04-10 for 1 adult", state)
    manager.handle_user_text("skip", state)
    manager.handle_user_text("option 1", state)
    result = manager.handle_user_text("yes", state)

    assert result.done is True
    assert state.booking_result is not None
    assert state.booking_result.success is True


def test_date_phrase_march_8th_does_not_crash() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("Dallas", state)
    manager.handle_user_text("Seattle", state)
    result = manager.handle_user_text("March 8th", state)

    assert state.trip_request.depart_date is not None
    assert state.trip_request.depart_date.endswith("-03-08")
    assert "passengers" in result.messages[0].lower()
