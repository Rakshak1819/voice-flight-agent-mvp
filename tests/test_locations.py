from src.core.dialog_manager import DialogManager
from src.core.locations import normalize_location_text
from src.core.state import SessionState
from src.providers.mock_provider import MockFlightProvider


def test_normalize_code_and_airport_name() -> None:
    assert normalize_location_text("DFW") == "Dallas/Fort Worth (DFW)"
    assert normalize_location_text("Seattle-Tacoma International Airport") == "Seattle-Tacoma (SEA)"


def test_route_parsing_supports_code_to_code() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("DFW to SEA", state)

    assert state.trip_request.origin == "Dallas/Fort Worth (DFW)"
    assert state.trip_request.destination == "Seattle-Tacoma (SEA)"


def test_contextual_airport_name_answer_for_origin() -> None:
    manager = DialogManager(provider=MockFlightProvider(), llm_client=None)
    state = SessionState(session_id="test_session")

    manager.handle_user_text("one-way", state)
    manager.handle_user_text("John F Kennedy International Airport", state)

    assert state.trip_request.origin == "New York JFK (JFK)"
