# Voice Flight Agent MVP - Project Documentation

## 1. Project Overview

`voice-flight-agent-mvp` is a local, modular Python MVP for a voice-enabled flight-booking assistant.

It is designed to:
- collect trip requirements through natural conversation,
- search mock flight offers,
- present ranked options,
- require explicit confirmation,
- perform a mock booking,
- persist full session output to JSON,
- support both speech and keyboard interaction,
- stay easy to extend (Duffel provider, Twilio channel, OpenAI Agents SDK).

The system is intentionally payment-free and does not process raw card data.

## 2. What the Project Does

### Core capabilities
- Input from microphone or keyboard (user-selectable at startup).
- STT pipeline with OpenAI STT (preferred) and Vosk fallback.
- TTS pipeline with OpenAI TTS (preferred) and local fallback (Piper, then `pyttsx3`).
- Rule-based dialog manager with optional LLM assistance for slot extraction and response naturalization.
- Slot-filling for flight request fields:
  - `trip_type`, `origin`, `destination`, `depart_date`, `return_date`, `passengers`
  - optional: `cabin`, `nonstop_preference`, `max_stops`, `budget_usd`, `time_window`
- Offer browsing/refinement:
  - cheaper, fastest, fewer stops, refundable, bag-friendly, more flights, reset filters
- Confirmation guardrails before booking.
- Session save to `data/sessions/session_<timestamp>.json`.

### What it does not do
- No real booking APIs.
- No payments.
- No PII hardening / production security layer.
- No web UI (CLI demo only).

## 3. Repository Structure and File-by-File Purpose

```text
voice-flight-agent-mvp/
  README.md
  PROJECT_DOCUMENTATION.md
  requirements.txt
  .env.example
  scripts/
    run_local_demo.py
  src/
    __init__.py
    app.py
    config.py
    audio/
      __init__.py
      stt_openai.py
      stt_vosk.py
      tts_openai.py
      tts.py
    core/
      __init__.py
      state.py
      policy.py
      locations.py
      dialog_manager.py
    llm/
      __init__.py
      client.py
    providers/
      __init__.py
      base.py
      mock_provider.py
  data/
    sample_session.json
    sessions/
      session_*.json
  tests/
    test_slot_filling.py
    test_policy.py
    test_offer_normalization.py
    test_locations.py
    test_app_mode_switch.py
```

### Top-level files
- `README.md`: quickstart + user-facing usage notes.
- `requirements.txt`: minimal dependency set.
- `.env.example`: all configurable runtime variables.
- `scripts/run_local_demo.py`: runnable entrypoint wrapper calling `src.app.run_demo()`.

### App wiring
- `src/config.py`:
  - Loads `.env` if present.
  - Builds strongly typed `AppConfig` dataclass.
  - Resolves path/env toggles for STT/TTS and model selection.

- `src/app.py`:
  - Main runtime orchestrator.
  - Startup wizard:
    - lists/selects microphone device,
    - asks `speech` vs `text` mode.
  - Builds STT/TTS backends with fallback chain.
  - Starts conversation loop and command handling (`/text`, `/voice`, `/mode`, `/devices`).
  - Saves session snapshot JSON at end.

### Audio modules
- `src/audio/stt_openai.py`:
  - Push-to-talk mic capture using `sounddevice`.
  - Sends recorded WAV to OpenAI transcription endpoint.
  - Supports language/prompt/min-duration/debug settings.
  - Includes false-positive suppression (e.g., noisy single-word artifacts like `you`).
  - Provides device listing and partial-name device matching.

- `src/audio/stt_vosk.py`:
  - Offline STT fallback using Vosk model + microphone capture.
  - Uses same push-to-talk UX pattern.

- `src/audio/tts_openai.py`:
  - OpenAI TTS synthesis to WAV.
  - OS-native playback (`winsound`, `afplay`, `aplay`).

- `src/audio/tts.py`:
  - Local TTS fallback.
  - First choice: Piper executable + voice model.
  - Final fallback: `pyttsx3`.

### Core conversation modules
- `src/core/state.py`:
  - Pydantic models for all state contracts:
    - `TripRequest`, `FlightOffer`, `BookingResult`, `SessionState`, `SessionSnapshot`, etc.
  - Validation rules:
    - passenger bounds,
    - stop count bounds,
    - date format checks,
    - return date after depart date.

- `src/core/policy.py`:
  - Confirmation policy and safety gate:
    - yes/no parsing,
    - offer selection parsing,
    - readback text generation,
    - booking gating (`explicit yes` + selected offer required).

- `src/core/locations.py`:
  - Location normalization utility.
  - Handles city names, airport names, IATA codes, alias mapping.
  - Returns canonical labels like `Dallas/Fort Worth (DFW)`.

- `src/core/dialog_manager.py`:
  - Main conversation brain.
  - State-machine phases:
    - collecting requirements,
    - awaiting offer selection,
    - awaiting booking confirmation,
    - completed/cancelled.
  - Handles:
    - slot extraction,
    - contextual short-answer capture,
    - corrections (`go back`),
    - offer ranking/filter browsing,
    - selection + confirmation + booking call.
  - Rich date parsing for natural speech/text.

### LLM integration
- `src/llm/client.py`:
  - Optional OpenAI text client.
  - If enabled:
    - interprets utterances into strict JSON slot updates,
    - can naturalize assistant text for spoken style.
  - Always validated through Pydantic schema.
  - Fallback to deterministic rules on any parse/API failure.

### Provider abstraction
- `src/providers/base.py`:
  - `FlightProvider` interface with typed methods:
    - `search_offers(trip_request)`
    - `book_offer(offer, trip_request)`

- `src/providers/mock_provider.py`:
  - Deterministic mock search + mock book implementation.
  - Normalizes offers into `FlightOffer` model.
  - Supports bag and refundable attributes for filtering use-cases.

### Tests
- `tests/test_slot_filling.py`:
  - flow coverage for slot collection,
  - corrections,
  - natural utterance parsing,
  - spoken-date parsing,
  - offer refinement,
  - confirmation edge case with noisy LLM updates.

- `tests/test_policy.py`:
  - booking gating and offer-selection parser behavior.

- `tests/test_offer_normalization.py`:
  - raw->typed offer conversion checks.

- `tests/test_locations.py`:
  - location normalization and route parsing.

- `tests/test_app_mode_switch.py`:
  - mode-switch command parsing behavior.

## 4. End-to-End Data Flow

```text
User (Voice or Text)
  -> app.py runtime loop
    -> STT backend (OpenAI STT or Vosk) [if voice]
    -> utterance text
    -> DialogManager.handle_user_text()
       -> rule extraction (+ optional LLM slot updates)
       -> TripRequest / SessionState update (Pydantic-validated)
       -> provider.search_offers() when required slots complete
       -> ranked offers + follow-up prompts
       -> provider.book_offer() only after explicit confirmation
    -> assistant response text
    -> optional TTS (OpenAI or local)
  -> session snapshot persisted to JSON
```

### State updates through the loop
1. User turn is appended to transcript.
2. Current phase determines handler path.
3. Handler extracts updates and validates them.
4. Required slots complete -> offer search.
5. Offer selection -> readback.
6. Explicit `yes` -> booking.
7. End state is written to disk.

## 5. Conversation Engine Internals

## 5.1 State machine
- `COLLECTING_REQUIREMENTS`
- `AWAITING_SELECTION`
- `AWAITING_CONFIRMATION`
- `COMPLETED`
- `CANCELLED`

Transitions are explicit and driven in `DialogManager`.

## 5.2 Required slot ordering
The manager asks missing required slots in priority order:
1. `trip_type`
2. `origin`
3. `destination`
4. `depart_date`
5. `return_date` (only for round trip)
6. `passengers`

## 5.3 Slot extraction strategy
For each user utterance:
1. Optional LLM extraction (`llm.client`) if enabled.
2. Deterministic regex/rule extraction.
3. If rules found anything, they override LLM extraction (to prevent noisy cross-slot updates).
4. Contextual short-answer capture for the currently asked slot.
5. Normalization pass (`trip_type`, location labels, dates, counts, enum-like values).
6. Pydantic validation before commit.

## 5.4 Natural input support
The parser is intentionally permissive for variations such as:
- Trip type: `one way`, `one-way`, `round trip`, `return flight`.
- Route styles:
  - `from Dallas to Seattle`
  - `Dallas to Seattle`
  - `to Seattle from Dallas`
- Passengers:
  - `2 adults`, `just me`, `for 3`
- Cabin:
  - `coach`, `business class`, `premium`
- Stops:
  - `nonstop`, `direct`, `max 1 stop`
- Budget:
  - `$500`, `under 600`, `500 usd`
- Time window:
  - `morning`, `afternoon`, `night`, `any time`

## 5.5 Date parsing behavior
The date parser supports:
- ISO: `2026-04-10`
- Spoken spaced ISO: `2026 4 10`
- Slash: `04/10`, `04/10/26`
- Month words: `April 10`, `Apr 10th, 2026`
- Spoken forms:
  - `April tenth twenty twenty six`
  - `the tenth of April`
  - `ten April 2026`
- Relative forms:
  - `today`, `tomorrow`, `day after tomorrow`
  - `next Monday`

## 5.6 Corrections and rewind
- User can say `go back`, `previous`, `undo`, etc.
- The system clears the previous required slot and re-prompts.
- If rewinding trip type or departure date, dependent return date is cleared.
- Offer cache and selection are reset to avoid stale selection errors.

## 5.7 Offer browsing and refinement
In selection/confirmation phases, users can ask for:
- more flights,
- cheaper flights,
- fastest flights,
- fewer-stop/direct flights,
- refundable flights,
- cabin/checked bag requirements,
- reset/show all flights.

Sorting modes:
- `balanced`
- `cheapest`
- `fastest`
- `fewest_stops`
- `bag_friendly`

Pagination is 3 offers per page.

## 6. Guardrails and Safety Logic

Implemented guardrails:
- Booking is blocked unless an offer is selected.
- Booking is blocked unless confirmation parser detects explicit yes.
- Pre-book readback includes:
  - route,
  - times,
  - stops,
  - cabin,
  - passengers,
  - total price,
  - refundable flag.
- Booking success message is shown only when provider returns `success=True`.

No payment behavior exists in this codebase.

## 7. Audio Runtime and Mode Switching

## 7.1 Startup prompts
Before dialog starts, `app.py` asks:
1. microphone device (index/name/default),
2. input mode (`speech` or `text`).

If speech is unavailable, the app explains the STT reason and defaults to text mode.

## 7.2 Runtime mode commands
Supported in-session commands:
- `/text` -> switch to keyboard mode
- `/voice` -> switch to microphone mode (if STT available)
- `/mode` -> show mode help
- `/devices` -> list microphone devices

Natural phrases like `switch to text mode` also work.

## 7.3 STT backend selection order
1. OpenAI STT (if enabled + API key + deps), else
2. Vosk STT (if model configured + deps), else
3. text fallback.

## 7.4 TTS backend selection order
1. OpenAI TTS (if enabled + API key), else
2. local TTS (Piper, then `pyttsx3`), else
3. print-only output.

## 8. Session Persistence Format

At session end, app writes:
- `data/sessions/session_<UTC timestamp>.json`

Snapshot structure (`SessionSnapshot`):
- `transcript`: ordered list of user/assistant/system turns with UTC timestamps
- `final_trip_request`: normalized final trip object
- `offers_shown`: most recent displayed page of offers
- `selected_offer`: selected offer object (if any)
- `booking_result`: booking result payload (if attempted)

`data/sample_session.json` provides a minimal reference shape.

## 9. Configuration Reference

Environment variables (from `AppConfig` / `.env.example`):

- OpenAI / LLM:
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `OPENAI_SPEECH_ENABLED`
  - `OPENAI_STT_MODEL`
  - `OPENAI_TTS_MODEL`
  - `OPENAI_TTS_VOICE`

- STT control:
  - `STT_ENABLED`
  - `STT_LANGUAGE`
  - `STT_PROMPT`
  - `STT_MIN_RECORD_SECONDS`
  - `STT_DEBUG`
  - `AUDIO_INPUT_DEVICE`
  - `VOSK_MODEL_PATH`

- TTS control:
  - `TTS_ENABLED`
  - `PIPER_EXECUTABLE`
  - `PIPER_VOICE_MODEL`

## 10. How to Run (Developer Setup)

## 10.1 Create and activate venv

Windows PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
python -m venv .venv
source .venv/bin/activate
```

## 10.2 Install dependencies
```bash
pip install -r requirements.txt
```

## 10.3 Configure env
```bash
cp .env.example .env
```
(Windows: `Copy-Item .env.example .env`)

## 10.4 Run demo
```bash
python scripts/run_local_demo.py
```

## 10.5 Run tests
```bash
pytest -q
```

## 11. Key Features Summary

- Dual interaction mode: voice + text with runtime switching.
- Device selection at startup and device listing command.
- Strong natural language support for slot filling.
- Flexible airport/city/code normalization.
- Spoken-date parsing improvements for STT-style phrasing.
- Offer refinement conversation (cheaper/faster/bags/refundable/more).
- Correction flow (`go back`).
- Guarded booking confirmation.
- Structured session export for debugging/audit/demo replay.
- Clean provider interface for future real API integration.

## 12. Extensibility Roadmap

## 12.1 Add Duffel provider
Create `src/providers/duffel_provider.py` implementing `FlightProvider`:
- `search_offers(trip_request) -> list[FlightOffer]`
- `book_offer(offer, trip_request) -> BookingResult`

Integration points:
- Instantiate Duffel provider in `src/app.py`.
- Keep `FlightOffer` normalization strict in provider adapter.
- Reuse `DialogManager` and policy unchanged.

## 12.2 Add hotels/cars
Recommended structure:
- add `src/providers/hotel_base.py`, `car_base.py` (or a generic product tool layer),
- split `DialogManager` into intent router + product-specific managers,
- keep `SessionState` as canonical transcript + interaction state.

## 12.3 Migrate to Twilio
Keep current core intact and replace transport edges:
- input edge: Twilio audio/text webhook -> utterance text,
- output edge: Twilio voice/SMS responses,
- conversation core (`DialogManager`, providers, policy) remains reusable.

## 12.4 Upgrade to OpenAI Agents SDK
- Convert search/book/filter actions into explicit tools.
- Keep Pydantic state models as tool I/O contracts.
- Move orchestration from manual loop to SDK runner.
- Keep STT/TTS adapters as channel-specific wrappers.

## 13. Known Limits / MVP Tradeoffs

- CLI UX only; no async multi-user session service.
- Route/date parsing is robust but still heuristic.
- LLM extraction is optional and constrained to slot JSON only.
- Mock provider pricing is deterministic synthetic data.
- No persistence layer beyond session JSON files.

## 14. Troubleshooting Guide

- "Voice mode unavailable":
  - check `STT_ENABLED=true`.
  - set `OPENAI_API_KEY` for OpenAI STT, or set valid `VOSK_MODEL_PATH`.
  - ensure `sounddevice` and `numpy` are installed.

- Poor transcription quality:
  - run `/devices` and pick a better mic.
  - set `AUDIO_INPUT_DEVICE`.
  - enable `STT_DEBUG=true`.
  - speak longer than `STT_MIN_RECORD_SECONDS`.

- No speech output:
  - verify `TTS_ENABLED=true`.
  - with OpenAI: check API key and model/voice vars.
  - with local TTS: verify Piper path/model or `pyttsx3` install.

- Date not understood:
  - use explicit date forms like `2026-04-10` or `April 10, 2026`.

## 15. Quick Mental Model

This project is organized as:
- `app.py` = runtime shell + IO backends
- `dialog_manager.py` = conversation orchestration and state transitions
- `policy.py` = booking safety rules
- `providers/*` = search/book tools
- `state.py` = typed schema contracts

That separation is the main reason this MVP is easy to maintain and upgrade.
