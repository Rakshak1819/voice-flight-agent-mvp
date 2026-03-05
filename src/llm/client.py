from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from src.core.state import TripRequest

logger = logging.getLogger(__name__)


class LlmSlotUpdate(BaseModel):
    trip_type: str | None = None
    origin: str | None = None
    destination: str | None = None
    depart_date: str | None = None
    return_date: str | None = None
    passengers: int | None = None
    cabin: str | None = None
    nonstop_preference: bool | None = None
    max_stops: int | None = None
    budget_usd: int | None = None
    time_window: str | None = None


class LLMClient:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._client = None
        if api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover - dependency may be missing
                logger.warning("OpenAI client unavailable: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def interpret_slot_updates(self, utterance: str, current_trip: TripRequest) -> dict[str, Any]:
        if not self.enabled:
            return {}

        system = (
            "Extract only flight-slot updates from the user utterance. "
            "Return strict JSON object only with fields: trip_type, origin, destination, depart_date, return_date, "
            "passengers, cabin, nonstop_preference, max_stops, budget_usd, time_window. "
            "Use null for missing fields. Dates must be YYYY-MM-DD."
        )
        user = {
            "utterance": utterance,
            "current_trip": current_trip.model_dump(),
        }

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user)},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            validated = LlmSlotUpdate(**parsed)
            return {k: v for k, v in validated.model_dump().items() if v is not None}
        except (ValidationError, json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Invalid LLM slot output, falling back to rules: %s", exc)
            return {}
        except Exception as exc:  # pragma: no cover - runtime API/network errors
            logger.warning("LLM parse failed, falling back to rules: %s", exc)
            return {}

    def naturalize(self, fallback_text: str) -> str:
        if not self.enabled:
            return fallback_text

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Rewrite the text to be concise, helpful, and spoken aloud. Keep factual details unchanged.",
                    },
                    {"role": "user", "content": fallback_text},
                ],
                temperature=0.3,
            )
            content = response.choices[0].message.content
            return content.strip() if content else fallback_text
        except Exception:
            return fallback_text
