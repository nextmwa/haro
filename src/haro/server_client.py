import asyncio
from typing import AsyncIterator, Protocol

from . import protocol


class WebSocketLike(Protocol):
    async def send(self, data) -> None: ...
    async def recv(self): ...
    async def close(self) -> None: ...


async def _default_connector(url: str) -> WebSocketLike:
    import websockets

    return await websockets.connect(url)


class ServerClient:
    def __init__(self, url: str, connector=None) -> None:
        self._url = url
        self._connector = connector if connector is not None else _default_connector
        self._connection: WebSocketLike | None = None

    async def connect(self) -> None:
        self._connection = await self._connector(self._url)

    async def connect_with_retry(
        self,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        sleep=asyncio.sleep,
    ) -> None:
        backoff = initial_backoff
        while True:
            try:
                await self.connect()
                return
            except OSError:
                await sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def send_hello(self, session_id: str) -> None:
        await self._connection.send(protocol.encode_hello(session_id))

    async def send_audio_frame(self, frame: bytes) -> None:
        await self._connection.send(frame)

    async def send_end_of_speech(self) -> None:
        await self._connection.send(protocol.encode_end_of_speech())

    async def receive_events(self) -> AsyncIterator[protocol.ServerEvent]:
        while True:
            message = await self._connection.recv()
            if isinstance(message, bytes):
                yield protocol.AudioChunkEvent(data=message)
            else:
                yield protocol.parse_server_message(message)
