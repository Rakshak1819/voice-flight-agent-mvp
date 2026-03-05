# Voice Flight Agent MVP

Local microphone voice demo for a flight-booking assistant using a mock provider. It supports OpenAI speech/text by default (when `OPENAI_API_KEY` is set) with offline and text-only fallbacks.

## What This MVP Does
- Captures user turns from microphone with OpenAI STT when API key is configured, otherwise Vosk STT when available.
- Falls back to keyboard input if STT dependencies/models are missing.
- Runs a slot-filling dialog to collect flight request details.
- Accepts origin/destination as city names, airport names, or IATA codes (for example `Dallas`, `Dallas Fort Worth International Airport`, `DFW`).
- Accepts more natural phrasing for dates, passengers, cabin, budget, and stops (for example `04/10`, `two adults`, `coach`, `under 500`, `direct`).
- Accepts natural trip-type phrases in speech/text (`one way`, `one-way`, `round trip`, `round-trip`) without requiring underscore formats.
- Searches deterministic mock offers and presents top options with bag details.
- Lets users ask for more flights or refined options (`cheaper`, `faster`, `fewer stops`, `with checked bag`, `with cabin bag`, `refundable`).
- Supports correction flow with `go back` to return to the previous required question and fix mistakes.
- Requires explicit confirmation before mock booking.
- Speaks agent responses using OpenAI TTS when configured, otherwise Piper/`pyttsx3` if available.
- Saves a structured session JSON in `data/sessions/` at end of run.

## What This MVP Does Not Do
- No real airline booking.
- No payments.
- No handling of raw card data.

## Project Structure
- `README.md`
- `requirements.txt`
- `.env.example`
- `src/`
- `scripts/`
- `data/`
- `tests/`

## Architecture Overview
```text
+-------------------+      +-----------------------+
| Mic / Keyboard UI | ---> | audio.stt_openai      |
+-------------------+      +-----------------------+
           |                          |
           v                          v
+----------------------------------------------------+
| core.dialog_manager (slot filling + flow control)  |
|  - core.policy (confirmation guardrails)           |
|  - llm.client (optional OpenAI parsing/naturalize) |
+----------------------------------------------------+
           |
           v
+-----------------------+      +-----------------------+
| providers.base        | ---> | providers.mock_provider|
+-----------------------+      +-----------------------+
           |
           v
+-----------------------+      +-----------------------+
| audio.tts_openai      |      | data/sessions/*.json  |
+-----------------------+      +-----------------------+
```

## Setup
1. Create virtual environment:
```bash
python -m venv .venv
```

2. Activate:
- Windows PowerShell:
```powershell
.\.venv\Scripts\Activate.ps1
```
- macOS/Linux:
```bash
source .venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
```
On Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

5. Optional model/tool setup:
- OpenAI speech (recommended):
  - Set `OPENAI_API_KEY`.
  - Keep `OPENAI_SPEECH_ENABLED=true`.
  - Optional: customize `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`.
- Offline fallback:
  - Vosk model download: https://alphacephei.com/vosk/models
    - Set `VOSK_MODEL_PATH` to extracted model directory.
  - Piper voices: https://github.com/rhasspy/piper
    - Set `PIPER_EXECUTABLE` and `PIPER_VOICE_MODEL`.

## Run
```bash
.venv/Scripts/python scripts/run_local_demo.py
```

### Runtime Behavior
- If OpenAI speech + mic dependencies are available:
  - Press Enter to start recording.
  - Press Enter again to stop and transcribe.
- If OpenAI STT is unavailable and Vosk is configured:
  - The app automatically falls back to Vosk.
- If unavailable:
  - The app prompts for typed text.
- If OpenAI/Piper/pyttsx3 TTS are unavailable:
  - Agent replies are printed only.
- At any required-question step, user can say `go back` to revise the previous answer.
- Input mode can be switched anytime:
  - `'/text'` or `switch to text mode`
  - `'/voice'` or `switch to voice mode`
- If transcription quality is poor:
  - use `'/devices'` to list microphones
  - set `AUDIO_INPUT_DEVICE` in `.env` to the desired index or partial name
  - enable `STT_DEBUG=true` to log recording duration and audio level

## Guardrails Implemented
- Booking is attempted only after:
  - valid option selection,
  - explicit `yes` confirmation.
- Before booking, agent reads back:
  - itinerary details,
  - passenger count,
  - total price,
  - refundability.
- Agent never reports booking success unless booking tool returns `success=true`.

## Tests
```bash
pytest -q
```

## Add Duffel Later
Implement a new provider in `src/providers/duffel_provider.py` that conforms to `FlightProvider` in `src/providers/base.py`:
- `search_offers(trip_request) -> list[FlightOffer]`
- `book_offer(offer, trip_request) -> BookingResult`

Then swap provider construction in `src/app.py`.

## Upgrade Path to OpenAI Agents SDK
1. Keep `DialogManager` as orchestration entrypoint initially.
2. Convert provider/policy/search/booking actions into explicit tool functions under `src/tools/`.
3. Replace direct turn loop with Agents SDK runner and tool registry.
4. Reuse `core/state.py` models as canonical session schema.
5. Keep STT/TTS adapters unchanged as transport layer wrappers.
