from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    data_dir: Path
    session_dir: Path
    openai_api_key: str | None
    openai_model: str
    openai_speech_enabled: bool
    openai_stt_model: str
    openai_tts_model: str
    openai_tts_voice: str
    stt_language: str | None
    stt_prompt: str | None
    stt_min_record_seconds: float
    stt_debug: bool
    audio_input_device: str | int | None
    vosk_model_path: Path | None
    piper_executable: str | None
    piper_voice_model: Path | None
    tts_enabled: bool
    stt_enabled: bool


def load_config() -> AppConfig:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    data_dir = project_root / "data"
    session_dir = data_dir / "sessions"

    vosk_model_raw = os.getenv("VOSK_MODEL_PATH", "").strip()
    piper_voice_raw = os.getenv("PIPER_VOICE_MODEL", "").strip()
    input_device_raw = os.getenv("AUDIO_INPUT_DEVICE", "").strip()
    if input_device_raw.isdigit():
        input_device: str | int | None = int(input_device_raw)
    else:
        input_device = input_device_raw or None

    return AppConfig(
        project_root=project_root,
        data_dir=data_dir,
        session_dir=session_dir,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_speech_enabled=(os.getenv("OPENAI_SPEECH_ENABLED", "true").strip().lower() == "true"),
        openai_stt_model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe"),
        openai_tts_model=os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
        openai_tts_voice=os.getenv("OPENAI_TTS_VOICE", "alloy"),
        stt_language=(os.getenv("STT_LANGUAGE", "en").strip() or None),
        stt_prompt=(os.getenv("STT_PROMPT", "").strip() or None),
        stt_min_record_seconds=float(os.getenv("STT_MIN_RECORD_SECONDS", "1.2")),
        stt_debug=(os.getenv("STT_DEBUG", "false").strip().lower() == "true"),
        audio_input_device=input_device,
        vosk_model_path=Path(vosk_model_raw) if vosk_model_raw else None,
        piper_executable=(os.getenv("PIPER_EXECUTABLE") or "").strip() or None,
        piper_voice_model=Path(piper_voice_raw) if piper_voice_raw else None,
        tts_enabled=(os.getenv("TTS_ENABLED", "true").strip().lower() == "true"),
        stt_enabled=(os.getenv("STT_ENABLED", "true").strip().lower() == "true"),
    )
