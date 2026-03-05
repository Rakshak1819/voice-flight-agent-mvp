from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import numpy as np
    import sounddevice as sd
    from vosk import KaldiRecognizer, Model, SetLogLevel
except Exception:  # pragma: no cover - optional dependency
    np = None
    sd = None
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None


class VoskSTT:
    def __init__(
        self,
        model_path: Path | None,
        sample_rate: int = 16_000,
        input_device: str | int | None = None,
    ) -> None:
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.input_device = input_device
        self._model = None

        if SetLogLevel is not None:
            SetLogLevel(-1)

        if self.is_available:
            try:
                self._model = Model(str(self.model_path))
                logger.info("Loaded Vosk model from %s", self.model_path)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to load Vosk model: %s", exc)

    @property
    def is_available(self) -> bool:
        return bool(np is not None and sd is not None and Model is not None and self.model_path and self.model_path.exists())

    def transcribe_from_microphone(self) -> str:
        if self._model is None or np is None or sd is None or KaldiRecognizer is None:
            return ""

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

        selected_device = self._resolve_input_device()

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

        if not frames:
            return ""

        audio = np.concatenate(frames, axis=0).tobytes()
        recognizer = KaldiRecognizer(self._model, self.sample_rate)
        recognizer.AcceptWaveform(audio)
        result = json.loads(recognizer.FinalResult())
        text = (result.get("text") or "").strip()
        logger.info("STT transcript: %s", text)
        return text

    def _resolve_input_device(self) -> str | int | None:
        if self.input_device is None or sd is None:
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
