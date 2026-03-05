from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import wave
from pathlib import Path

try:  # pragma: no cover - optional dependency
    import numpy as np
    import sounddevice as sd
except Exception:  # pragma: no cover
    np = None
    sd = None

logger = logging.getLogger(__name__)


class OpenAISTT:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        sample_rate: int = 16_000,
        input_device: str | int | None = None,
        language: str | None = "en",
        prompt: str | None = None,
        min_record_seconds: float = 1.2,
        debug: bool = False,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.sample_rate = sample_rate
        self.input_device = input_device
        self.language = language
        self.prompt = prompt
        self.min_record_seconds = min_record_seconds
        self.debug = debug
        self._client = None

        if api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=api_key)
            except Exception as exc:  # pragma: no cover
                logger.warning("OpenAI STT client unavailable: %s", exc)

    @property
    def is_available(self) -> bool:
        return bool(self._client is not None and np is not None and sd is not None)

    @staticmethod
    def list_input_devices() -> list[str]:
        if sd is None:
            return []
        rows: list[str] = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                rows.append(f"[{idx}] {dev['name']}")
        return rows

    def transcribe_from_microphone(self) -> str:
        if not self.is_available:
            return ""

        selected_device = self._resolve_input_device()
        if self.debug:
            logger.info("OpenAI STT using input device: %s", selected_device if selected_device is not None else "default")

        print("Press Enter to start recording.")
        input()

        stop_event = threading.Event()
        frames: list[np.ndarray] = []

        def callback(indata, _frames, _time, status):
            if status:
                logger.warning("Microphone status: %s", status)
            frames.append(indata.copy())

        def wait_for_stop() -> None:
            input("Recording... press Enter to stop.\n")
            stop_event.set()

        stopper = threading.Thread(target=wait_for_stop, daemon=True)
        stopper.start()

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                callback=callback,
                device=selected_device,
            ):
                while not stop_event.is_set():
                    sd.sleep(100)
        except Exception as exc:  # pragma: no cover
            logger.warning("Microphone capture failed: %s", exc)
            return ""

        if not frames or np is None:
            return ""

        audio = np.concatenate(frames, axis=0)
        duration_sec = float(audio.shape[0]) / float(self.sample_rate)
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))

        if self.debug:
            logger.info("Recorded %.2fs audio, rms=%.1f", duration_sec, rms)

        if duration_sec < self.min_record_seconds:
            logger.info("Recording too short (%.2fs). Please speak a bit longer.", duration_sec)
            return ""

        wav_path = self._write_temp_wav(audio)
        if wav_path is None:
            return ""

        try:
            assert self._client is not None
            with wav_path.open("rb") as audio_file:
                request: dict[str, object] = {
                    "model": self.model,
                    "file": audio_file,
                }
                if self.language:
                    request["language"] = self.language
                if self.prompt:
                    request["prompt"] = self.prompt
                response = self._client.audio.transcriptions.create(**request)
            transcript = (getattr(response, "text", "") or "").strip()
            logger.info("OpenAI STT transcript: %s", transcript)

            if self._looks_like_false_positive(transcript, rms):
                logger.info("Low-confidence transcript suppressed; please try speaking closer to the mic.")
                return ""

            return transcript
        except Exception as exc:  # pragma: no cover
            logger.warning("OpenAI transcription failed: %s", exc)
            return ""
        finally:
            wav_path.unlink(missing_ok=True)

    def _write_temp_wav(self, audio: np.ndarray) -> Path | None:
        fd, raw_path = tempfile.mkstemp(prefix="openai_stt_", suffix=".wav")
        path = Path(raw_path)

        try:
            os.close(fd)
        except Exception:
            pass

        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio.tobytes())
            return path
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to write temp wav: %s", exc)
            path.unlink(missing_ok=True)
            return None

    def _resolve_input_device(self) -> str | int | None:
        if self.input_device is None:
            return None
        if sd is None:
            return None

        if isinstance(self.input_device, int):
            return self.input_device

        raw = self.input_device.strip()
        if raw.isdigit():
            return int(raw)

        needle = raw.lower()
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) <= 0:
                continue
            if needle in str(dev.get("name", "")).lower():
                return idx
        return None

    def _looks_like_false_positive(self, transcript: str, rms: float) -> bool:
        normalized = re.sub(r"[^a-z ]+", "", transcript.strip().lower())
        if not normalized:
            return True

        short_noise = {
            "you",
            "u",
            "uh",
            "huh",
            "yeah",
            "ya",
            "hmm",
            "mm",
        }
        if normalized in short_noise and rms < 300:
            return True

        if len(normalized.split()) <= 1 and len(normalized) <= 3 and rms < 250:
            return True

        return False
