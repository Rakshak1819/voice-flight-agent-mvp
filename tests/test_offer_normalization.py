from src.providers.mock_provider import normalize_offer


def test_offer_normalization_types() -> None:
    raw = {
        "offer_id": "MOCK-0001-1",
        "provider": "mock",
        "carrier": "SkyJet",
        "flight_number": "SK201",
        "origin": "Boston",
        "destination": "Seattle",
        "depart_time_local": "2026-04-10 08:00",
        "arrive_time_local": "2026-04-10 11:05",
        "duration_minutes": "185",
        "stops": "0",
        "cabin": "economy",
        "price_usd": "299.5",
        "refundable": True,
        "cabin_bag_included": True,
        "checked_bag_included": False,
        "checked_bag_fee_usd": "35",
        "currency": "USD",
    }

    offer = normalize_offer(raw)
    assert offer.duration_minutes == 185
    assert offer.stops == 0
    assert offer.price_usd == 299.5
    assert offer.cabin == "economy"
    assert offer.cabin_bag_included is True
    assert offer.checked_bag_included is False
    assert offer.checked_bag_fee_usd == 35.0
