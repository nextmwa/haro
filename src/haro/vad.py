from typing import Protocol

import webrtcvad

from .framing import FrameBuffer


class VadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class SilenceDetector:
    def __init__(
        self,
        sample_rate: int = 16000,
        vad_frame_duration_ms: int = 30,
        silence_duration_ms: int = 800,
        aggressiveness: int = 2,
        vad: VadLike | None = None,
    ) -> None:
        self._vad = vad if vad is not None else webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        frame_size_bytes = int(sample_rate * vad_frame_duration_ms / 1000) * 2  # 16-bit mono
        self._buffer = FrameBuffer(frame_size_bytes)
        self._silence_frames_needed = max(1, silence_duration_ms // vad_frame_duration_ms)
        self._consecutive_silence = 0

    def reset(self) -> None:
        self._consecutive_silence = 0
        self._buffer.clear()

    def process_frame(self, frame: bytes) -> bool:
        triggered = False
        for chunk in self._buffer.push(frame):
            if self._vad.is_speech(chunk, self._sample_rate):
                self._consecutive_silence = 0
            else:
                self._consecutive_silence += 1
            if self._consecutive_silence >= self._silence_frames_needed:
                triggered = True
        return triggered
