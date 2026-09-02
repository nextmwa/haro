import logging
from typing import Protocol

import numpy as np

from .framing import FrameBuffer

logger = logging.getLogger(__name__)


class WakeWordModel(Protocol):
    def predict(self, frame: np.ndarray) -> dict[str, float]: ...


class WakeWordDetector:
    def __init__(
        self,
        model: WakeWordModel,
        model_name: str,
        threshold: float = 0.5,
        frame_size_bytes: int = 2560,
    ) -> None:
        self._model = model
        self._model_name = model_name
        self._threshold = threshold
        self._buffer = FrameBuffer(frame_size_bytes)

    def process_frame(self, frame: bytes) -> bool:
        triggered = False
        for chunk in self._buffer.push(frame):
            samples = np.frombuffer(chunk, dtype=np.int16)
            scores = self._model.predict(samples)
            score = scores.get(self._model_name, 0.0)
            if score >= self._threshold:
                logger.info(
                    "wake word %r detected (score %.3f >= %.3f)",
                    self._model_name,
                    score,
                    self._threshold,
                )
                triggered = True
        return triggered
