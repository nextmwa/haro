from typing import Protocol


class OutputStreamLike(Protocol):
    def write(self, data: bytes) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class AudioOutput:
    def __init__(
        self,
        stream: OutputStreamLike | None = None,
        device: str | None = None,
        sample_rate: int = 24000,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._injected_stream = stream
        self._stream: OutputStreamLike | None = None
        self._started = False

    def _get_stream(self) -> OutputStreamLike:
        if self._injected_stream is not None:
            return self._injected_stream
        if self._stream is None:
            import sounddevice as sd

            self._stream = sd.RawOutputStream(
                samplerate=self._sample_rate, channels=1, dtype="int16", device=self._device,
            )
        return self._stream

    def play_chunk(self, chunk: bytes) -> None:
        stream = self._get_stream()
        if not self._started:
            stream.start()
            self._started = True
        stream.write(chunk)

    def stop(self) -> None:
        if self._started:
            stream = self._get_stream()
            stream.stop()
            stream.close()
            self._stream = None
            self._started = False
