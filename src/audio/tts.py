from __future__ import annotations

import logging
import os
import platform
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None


class LocalTTS:
    def __init__(self, enabled: bool, piper_executable: str | None, piper_voice_model: Path | None) -> None:
        self.enabled = enabled
        self.piper_executable = piper_executable
        self.piper_voice_model = piper_voice_model
        self._engine = None

    @property
    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._piper_ready():
            return True
        return pyttsx3 is not None

    def speak(self, text: str) -> None:
        if not text:
            return

        if not self.enabled:
            return

        if self._piper_ready() and self._speak_with_piper(text):
            return

        if self._speak_with_pyttsx3(text):
            return

        logger.info("TTS unavailable; text output only.")

    def _piper_ready(self) -> bool:
        if not self.piper_executable or not self.piper_voice_model:
            return False
        return Path(self.piper_executable).exists() and self.piper_voice_model.exists()

    def _speak_with_piper(self, text: str) -> bool:
        wav_path = None
        try:
            fd, tmp_file = tempfile.mkstemp(prefix="piper_", suffix=".wav")
            os.close(fd)
            wav_path = Path(tmp_file)
            cmd = [
                str(self.piper_executable),
                "--model",
                str(self.piper_voice_model),
                "--output_file",
                str(wav_path),
            ]
            subprocess.run(cmd, input=text, text=True, check=True, capture_output=True)
            return self._play_wav(wav_path)
        except Exception as exc:
            logger.warning("Piper TTS failed: %s", exc)
            return False
        finally:
            if wav_path and wav_path.exists():
                wav_path.unlink(missing_ok=True)

    def _play_wav(self, wav_path: Path) -> bool:
        system = platform.system().lower()
        try:
            if system == "windows":
                import winsound

                winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
                return True

            if system == "darwin":
                subprocess.run(["afplay", str(wav_path)], check=True)
                return True

            subprocess.run(["aplay", str(wav_path)], check=True)
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("Audio playback failed: %s", exc)
            return False

    def _speak_with_pyttsx3(self, text: str) -> bool:
        if pyttsx3 is None:
            return False

        try:
            if self._engine is None:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 175)
            self._engine.say(text)
            self._engine.runAndWait()
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("pyttsx3 failed: %s", exc)
            return False
