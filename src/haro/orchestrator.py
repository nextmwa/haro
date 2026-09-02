import asyncio
import enum
from typing import AsyncIterator, Protocol

from . import protocol
from .face_display import Expression, expression_for_emotion


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
        await self._server_client.connect_with_retry()
        await self._server_client.send_hello(self._session_id)
        self._face_display.show(Expression.IDLE)

        async for frame in self._audio_input.frames():
            if self.state == State.IDLE:
                if self._wake_word.process_frame(frame):
                    await self._enter_listening()
            elif self.state == State.LISTENING:
                await self._server_client.send_audio_frame(frame)
                if self._silence_detector.process_frame(frame):
                    await self._enter_thinking()

    async def _enter_listening(self) -> None:
        self.state = State.LISTENING
        self._silence_detector.reset()
        self._face_display.show(Expression.LISTENING)

    async def _enter_thinking(self) -> None:
        self.state = State.THINKING
        self._face_display.show(Expression.THINKING)
        await self._server_client.send_end_of_speech()
        await self._handle_response()

    async def _handle_response(self) -> None:
        events = self._server_client.receive_events()
        try:
            async with asyncio.timeout(self._response_timeout_s):
                async for event in events:
                    if isinstance(event, protocol.EmotionEvent):
                        self.state = State.SPEAKING
                        self._face_display.show(expression_for_emotion(event.value))
                    elif isinstance(event, protocol.AudioChunkEvent):
                        self.state = State.SPEAKING
                        self._audio_output.play_chunk(event.data)
                    elif isinstance(event, protocol.ErrorEvent):
                        self._face_display.show(Expression.ERROR)
                        break
                    elif isinstance(event, protocol.ResponseEndEvent):
                        break
        except TimeoutError:
            self._face_display.show(Expression.ERROR)
        finally:
            await events.aclose()
            self._audio_output.stop()
            self.state = State.IDLE
            self._face_display.show(Expression.IDLE)
