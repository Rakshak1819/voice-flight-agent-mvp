from src.core.policy import can_attempt_booking, parse_offer_selection


def test_confirmation_requires_selection_and_yes() -> None:
    allowed, reason = can_attempt_booking(has_selection=False, confirmation_text="yes")
    assert not allowed
    assert "No offer selected" in reason

    allowed, reason = can_attempt_booking(has_selection=True, confirmation_text="no")
    assert not allowed
    assert "Explicit yes" in reason

    allowed, _ = can_attempt_booking(has_selection=True, confirmation_text="yes")
    assert allowed


def test_offer_selection_parser() -> None:
    assert parse_offer_selection("option 2", 3) == 2
    assert parse_offer_selection("the second one", 3) == 2
    assert parse_offer_selection("I will take flight three", 3) == 3
    assert parse_offer_selection("none of these", 3) == 0
    assert parse_offer_selection("option 9", 3) is None
