from typing import Protocol

from .framing import FrameBuffer


class WakeWordModel(Protocol):
    def predict(self, frame) -> dict[str, float]: ...


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
            scores = self._model.predict(chunk)
            if scores.get(self._model_name, 0.0) >= self._threshold:
                triggered = True
        return triggered
