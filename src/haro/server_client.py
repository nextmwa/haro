import asyncio
import logging
from typing import AsyncIterator, Protocol

from websockets.exceptions import WebSocketException

from . import protocol

logger = logging.getLogger(__name__)


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
        attempt = 0
        while True:
            attempt += 1
            try:
                await self.connect()
            except (OSError, WebSocketException) as exc:
                logger.warning(
                    "connection attempt %d to %s failed (%s); retrying in %.1fs",
                    attempt,
                    self._url,
                    exc,
                    backoff,
                )
                await sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            else:
                logger.info("connected to %s (attempt %d)", self._url, attempt)
                return

    async def close(self) -> None:
        if self._connection is not None:
            logger.info("closing connection to %s", self._url)
            await self._connection.close()
            self._connection = None

    async def send_hello(self, session_id: str) -> None:
        if self._connection is None:
            raise RuntimeError("not connected")
        await self._connection.send(protocol.encode_hello(session_id))

    async def send_audio_frame(self, frame: bytes) -> None:
        if self._connection is None:
            raise RuntimeError("not connected")
        await self._connection.send(frame)

    async def send_end_of_speech(self) -> None:
        if self._connection is None:
            raise RuntimeError("not connected")
        await self._connection.send(protocol.encode_end_of_speech())

    async def receive_events(self) -> AsyncIterator[protocol.ServerEvent]:
        if self._connection is None:
            raise RuntimeError("not connected")
        while True:
            message = await self._connection.recv()
            if isinstance(message, bytes):
                yield protocol.AudioChunkEvent(data=message)
            else:
                yield protocol.parse_server_message(message)
