from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from src.audio.stt_openai import OpenAISTT
from src.audio.stt_vosk import VoskSTT
from src.audio.tts import LocalTTS
from src.audio.tts_openai import OpenAITTS
from src.config import load_config
from src.core.dialog_manager import DialogManager
from src.core.state import SessionSnapshot, SessionState
from src.llm.client import LLMClient
from src.providers.mock_provider import MockFlightProvider


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


class STTBackend(Protocol):
    @property
    def is_available(self) -> bool:
        ...

    def transcribe_from_microphone(self) -> str:
        ...


class TTSBackend(Protocol):
    @property
    def available(self) -> bool:
        ...

    def speak(self, text: str) -> None:
        ...


def parse_input_mode_command(text: str) -> str | None:
    normalized = text.strip().lower()
    if not normalized:
        return None

    if normalized in {"/text", "text mode", "keyboard mode", "type mode"}:
        return "text"
    if normalized in {"/voice", "voice mode", "speech mode", "microphone mode"}:
        return "voice"
    if normalized in {"/mode", "mode help", "help mode"}:
        return "help"
    if normalized in {"/devices", "list devices", "microphone devices"}:
        return "devices"

    if "switch" in normalized and "text" in normalized:
        return "text"
    if "switch" in normalized and ("voice" in normalized or "speech" in normalized or "microphone" in normalized):
        return "voice"
    if re.search(r"\b(use|go to|change to)\b.*\b(text|keyboard|typing)\b", normalized):
        return "text"
    if re.search(r"\b(use|go to|change to)\b.*\b(voice|speech|microphone)\b", normalized):
        return "voice"

    return None


def save_session(state: SessionState, session_dir: Path) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    output_path = session_dir / file_name

    snapshot = SessionSnapshot(
        transcript=state.transcript,
        final_trip_request=state.trip_request,
        offers_shown=state.offers_shown,
        selected_offer=state.get_selected_offer(),
        booking_result=state.booking_result,
    )
    output_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _assistant_say(text: str, state: SessionState, tts: TTSBackend, llm_client: LLMClient) -> None:
    rendered = llm_client.naturalize(text) if llm_client.enabled else text
    print(f"Agent: {rendered}")
    state.add_turn("assistant", rendered)
    tts.speak(rendered)


def _prompt_startup_device(default_device: str | int | None) -> str | int | None:
    print("Microphone setup:")
    device_rows = OpenAISTT.list_input_devices()
    if device_rows:
        print("Available microphone devices:")
        for row in device_rows:
            print(f"  {row}")
    else:
        print("No microphone devices detected.")

    if default_device is not None:
        print(f"Current configured input device: {default_device}")

    raw = input("Choose microphone index/name for speech (Enter for default): ").strip()
    if not raw:
        return default_device
    if raw.lower() in {"default", "auto"}:
        return None
    if raw.isdigit():
        return int(raw)
    return raw


def _prompt_startup_mode(stt_available: bool, stt_reason: str) -> str:
    while True:
        default_mode = "speech" if stt_available else "text"
        raw = input(f"Input mode? [speech/text] (default: {default_mode}): ").strip().lower()
        if not raw:
            return "voice" if default_mode == "speech" else "text"
        if raw in {"speech", "voice", "mic", "microphone", "1"}:
            if stt_available:
                return "voice"
            print("Speech mode is unavailable in this session.")
            if stt_reason:
                print(f"STT reason: {stt_reason}")
            continue
        if raw in {"text", "keyboard", "typing", "2"}:
            return "text"
        print("Please enter 'speech' or 'text'.")


def _build_stt_backend(
    config: Any,
    input_device_override: str | int | None = None,
) -> tuple[STTBackend, str, str]:
    selected_input_device = config.audio_input_device if input_device_override is None else input_device_override
    if not config.stt_enabled:
        return VoskSTT(model_path=None), "none", "STT is disabled via STT_ENABLED=false."

    if config.openai_speech_enabled and config.openai_api_key:
        openai_stt = OpenAISTT(
            api_key=config.openai_api_key,
            model=config.openai_stt_model,
            input_device=selected_input_device,
            language=config.stt_language,
            prompt=config.stt_prompt,
            min_record_seconds=config.stt_min_record_seconds,
            debug=config.stt_debug,
        )
        if openai_stt.is_available:
            return openai_stt, "openai", ""

    vosk_stt = VoskSTT(model_path=config.vosk_model_path, input_device=selected_input_device)
    if vosk_stt.is_available:
        return vosk_stt, "vosk", ""

    reasons: list[str] = []
    if config.openai_speech_enabled and not config.openai_api_key:
        reasons.append("OPENAI_API_KEY is not set for OpenAI STT.")
    if config.vosk_model_path is None:
        reasons.append("VOSK_MODEL_PATH is not configured.")
    elif not config.vosk_model_path.exists():
        reasons.append(f"VOSK_MODEL_PATH not found: {config.vosk_model_path}")
    if not reasons:
        reasons.append("No STT backend available (missing dependencies or initialization failure).")
    return vosk_stt, "none", " ".join(reasons)


def _build_tts_backend(config: Any) -> tuple[TTSBackend, str]:
    if config.tts_enabled and config.openai_speech_enabled and config.openai_api_key:
        openai_tts = OpenAITTS(
            api_key=config.openai_api_key,
            model=config.openai_tts_model,
            voice=config.openai_tts_voice,
            enabled=True,
        )
        if openai_tts.available:
            return openai_tts, "openai"

    local_tts = LocalTTS(
        enabled=config.tts_enabled,
        piper_executable=config.piper_executable,
        piper_voice_model=config.piper_voice_model,
    )
    if local_tts.available:
        return local_tts, "local"
    return local_tts, "none"


def run_demo() -> None:
    setup_logging()
    config = load_config()

    provider = MockFlightProvider()
    llm_client = LLMClient(api_key=config.openai_api_key, model=config.openai_model)
    dialog = DialogManager(provider=provider, llm_client=llm_client)

    selected_input_device = _prompt_startup_device(config.audio_input_device)
    stt, stt_backend_name, stt_reason = _build_stt_backend(config, selected_input_device)
    tts, tts_backend_name = _build_tts_backend(config)

    stt_available = bool(config.stt_enabled and stt.is_available)
    input_mode = _prompt_startup_mode(stt_available, stt_reason)
    if input_mode == "voice":
        print(f"Speech mode enabled ({stt_backend_name.upper()} transcription).")
        print("Say '/text' anytime to switch to typing. Use '/devices' to list microphones.")
    else:
        print("Text mode enabled. Say '/voice' anytime to switch to microphone input.")
        if not stt_available and stt_reason:
            print(f"STT reason: {stt_reason}")

    if config.tts_enabled and not tts.available:
        print("TTS unavailable; running in text-only output mode.")
    elif config.tts_enabled:
        print(f"TTS backend: {tts_backend_name.upper()}.")

    session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    state = SessionState(session_id=session_id)

    opening = dialog.opening_message(state)
    _assistant_say(opening, state, tts, llm_client)

    done = False
    while not done:
        if input_mode == "voice":
            user_text = stt.transcribe_from_microphone()
            if not user_text:
                print("No speech detected. Type your response instead:")
                user_text = input("You: ").strip()
            else:
                print(f"You (transcribed): {user_text}")
        else:
            user_text = input("You (text): ").strip()

        if not user_text:
            continue

        mode_command = parse_input_mode_command(user_text)
        if mode_command == "text":
            input_mode = "text"
            print("Switched to text input mode. Say '/voice' to switch back.")
            continue
        if mode_command == "voice":
            if stt_available:
                input_mode = "voice"
                print("Switched to voice input mode.")
            else:
                print("Voice mode is unavailable in this session.")
                if stt_reason:
                    print(f"STT reason: {stt_reason}")
            continue
        if mode_command == "help":
            print("Input mode commands: '/text' for keyboard input, '/voice' for microphone input, '/devices' to list microphones.")
            continue
        if mode_command == "devices":
            device_rows = OpenAISTT.list_input_devices()
            if not device_rows:
                print("No microphone devices found.")
            else:
                print("Available microphone devices:")
                for row in device_rows:
                    print(f"  {row}")
            continue

        result = dialog.handle_user_text(user_text, state)
        for msg in result.messages:
            _assistant_say(msg, state, tts, llm_client)

        done = result.done

    output_path = save_session(state, config.session_dir)
    print(f"Session saved: {output_path}")


if __name__ == "__main__":
    run_demo()
