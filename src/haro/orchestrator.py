import asyncio
import enum
import logging
from typing import AsyncIterator, Protocol

from websockets.exceptions import WebSocketException

from . import protocol
from .face_display import Expression, expression_for_emotion

logger = logging.getLogger(__name__)

# Exceptions that mean "the conversation with the server broke": a malformed or
# unknown server message, a socket-level failure, or any WebSocket protocol
# error. Each of these ends the turn abnormally and forces a reconnect.
_TURN_ABORT_ERRORS = (protocol.ProtocolError, OSError, WebSocketException)


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class AudioInputLike(Protocol):
    def frames(self) -> AsyncIterator[bytes]: ...


class WakeWordDetectorLike(Protocol):
    def process_frame(self, frame: bytes) -> bool: ...


class SilenceDetectorLike(Protocol):
    def process_frame(self, frame: bytes) -> bool: ...
    def reset(self) -> None: ...


class ServerClientLike(Protocol):
    async def connect_with_retry(self) -> None: ...
    async def send_hello(self, session_id: str) -> None: ...
    async def send_audio_frame(self, frame: bytes) -> None: ...
    async def send_end_of_speech(self) -> None: ...
    async def close(self) -> None: ...
    def receive_events(self) -> AsyncIterator[protocol.ServerEvent]: ...


class AudioOutputLike(Protocol):
    def play_chunk(self, chunk: bytes) -> None: ...
    def stop(self) -> None: ...


class FaceDisplayLike(Protocol):
    def show(self, expression: Expression) -> None: ...


class Orchestrator:
    def __init__(
        self,
        audio_input: AudioInputLike,
        wake_word: WakeWordDetectorLike,
        silence_detector: SilenceDetectorLike,
        server_client: ServerClientLike,
        audio_output: AudioOutputLike,
        face_display: FaceDisplayLike,
        response_timeout_s: float = 15.0,
        session_id: str = "haro-session",
    ) -> None:
        self._audio_input = audio_input
        self._wake_word = wake_word
        self._silence_detector = silence_detector
        self._server_client = server_client
        self._audio_output = audio_output
        self._face_display = face_display
        self._response_timeout_s = response_timeout_s
        self._session_id = session_id
        self.state = State.IDLE

    async def run(self) -> None:
        logger.info("starting orchestrator (session %s)", self._session_id)
        await self._server_client.connect_with_retry()
        await self._server_client.send_hello(self._session_id)
        self._face_display.show(Expression.IDLE)
        logger.info("ready, waiting for wake word")

        async for frame in self._audio_input.frames():
            if self.state == State.IDLE:
                if self._wake_word.process_frame(frame):
                    await self._enter_listening()
            elif self.state == State.LISTENING:
                try:
                    await self._server_client.send_audio_frame(frame)
                except _TURN_ABORT_ERRORS as exc:
                    logger.warning("lost connection while listening: %s", exc)
                    await self._abort_turn_and_reconnect()
                    continue
                if self._silence_detector.process_frame(frame):
                    await self._enter_thinking()

    async def _enter_listening(self) -> None:
        logger.info("wake word detected, entering LISTENING")
        self.state = State.LISTENING
        self._silence_detector.reset()
        self._face_display.show(Expression.LISTENING)

    async def _enter_thinking(self) -> None:
        logger.info("end of speech detected, entering THINKING")
        self.state = State.THINKING
        self._face_display.show(Expression.THINKING)
        try:
            await self._server_client.send_end_of_speech()
        except _TURN_ABORT_ERRORS as exc:
            logger.warning("failed to signal end of speech: %s", exc)
            await self._abort_turn_and_reconnect()
            return
        await self._handle_response()

    async def _handle_response(self) -> None:
        events = self._server_client.receive_events()
        needs_reconnect = False
        try:
            async with asyncio.timeout(self._response_timeout_s) as cm:
                async for event in events:
                    cm.reschedule(asyncio.get_running_loop().time() + self._response_timeout_s)
                    if isinstance(event, protocol.EmotionEvent):
                        logger.info("server reported emotion: %s", event.value)
                        self.state = State.SPEAKING
                        self._face_display.show(expression_for_emotion(event.value))
                    elif isinstance(event, protocol.AudioChunkEvent):
                        self.state = State.SPEAKING
                        await asyncio.to_thread(self._audio_output.play_chunk, event.data)
                    elif isinstance(event, protocol.ErrorEvent):
                        logger.warning("server reported error: %s", event.message)
                        self._face_display.show(Expression.ERROR)
                        needs_reconnect = True
                        break
                    elif isinstance(event, protocol.ResponseEndEvent):
                        logger.info("response complete")
                        break
        except TimeoutError:
            logger.warning(
                "response timed out waiting for server after %.1fs", self._response_timeout_s
            )
            self._face_display.show(Expression.ERROR)
            needs_reconnect = True
        except _TURN_ABORT_ERRORS as exc:
            logger.warning("response aborted: %s", exc)
            self._face_display.show(Expression.ERROR)
            needs_reconnect = True
        finally:
            try:
                await events.aclose()
            except Exception as exc:  # closing a broken stream must not mask the turn's outcome
                logger.debug("error closing event stream: %s", exc)
            try:
                await asyncio.to_thread(self._audio_output.stop)
            finally:
                self.state = State.IDLE
                self._face_display.show(Expression.IDLE)

        if needs_reconnect:
            await self._reconnect()

    async def _abort_turn_and_reconnect(self) -> None:
        """Return to IDLE after an abnormal turn end, then rebuild the connection.

        A fresh connection cannot carry stale audio or response_end events from
        the aborted turn into the next one.
        """
        self._face_display.show(Expression.ERROR)
        self._silence_detector.reset()
        self.state = State.IDLE
        await self._reconnect()
        self._face_display.show(Expression.IDLE)

    async def _reconnect(self) -> None:
        logger.info("reconnecting to server")
        try:
            await self._server_client.close()
        except Exception as exc:  # an already-broken socket may refuse to close cleanly
            logger.warning("error closing connection before reconnect: %s", exc)
        await self._server_client.connect_with_retry()
        await self._server_client.send_hello(self._session_id)
        logger.info("reconnected to server")
