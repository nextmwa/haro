class FrameBuffer:
    def __init__(self, frame_size_bytes: int) -> None:
        if frame_size_bytes <= 0:
            raise ValueError("frame_size_bytes must be positive")
        self._frame_size = frame_size_bytes
        self._buffer = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while len(self._buffer) >= self._frame_size:
            frames.append(bytes(self._buffer[: self._frame_size]))
            del self._buffer[: self._frame_size]
        return frames

    def clear(self) -> None:
        self._buffer.clear()
