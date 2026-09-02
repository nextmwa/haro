import asyncio
from typing import AsyncIterator

from .framing import FrameBuffer


class AudioInput:
    def __init__(self, frame_size_bytes: int, device: str | None = None, sample_rate: int = 16000) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._buffer = FrameBuffer(frame_size_bytes)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _callback(self, indata, frames, time_info, status) -> None:
        for frame in self._buffer.push(bytes(indata)):
            self._loop.call_soon_threadsafe(self._queue.put_nowait, frame)

    def start(self) -> None:
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self._stream = sd.RawInputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            yield frame
