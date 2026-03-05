from __future__ import annotations

import logging
import platform
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class OpenAITTS:
    def __init__(self, api_key: str | None, model: str, voice: str, enabled: bool = True) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.enabled = enabled
        self._client = None

        if enabled and api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover
                logger.warning("OpenAI TTS client unavailable: %s", exc)

    @property
    def available(self) -> bool:
        return bool(self.enabled and self._client is not None)

    def speak(self, text: str) -> None:
        if not text or not self.available:
            return

        fd, raw_path = tempfile.mkstemp(prefix="openai_tts_", suffix=".wav")
        audio_path = Path(raw_path)
        try:
            import os

            os.close(fd)
        except Exception:
            pass

        try:
            assert self._client is not None
            response = self._client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="wav",
            )
            response.stream_to_file(audio_path)
            self._play_wav(audio_path)
        except Exception as exc:  # pragma: no cover
            logger.warning("OpenAI TTS failed: %s", exc)
        finally:
            audio_path.unlink(missing_ok=True)

    def _play_wav(self, wav_path: Path) -> None:
        system = platform.system().lower()

        if system == "windows":
            import winsound

            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
            return

        if system == "darwin":
            subprocess.run(["afplay", str(wav_path)], check=True)
            return

        subprocess.run(["aplay", str(wav_path)], check=True)
