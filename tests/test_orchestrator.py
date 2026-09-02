import asyncio

from haro import protocol
from haro.face_display import Expression
from haro.orchestrator import Orchestrator, State

NOISE = b"noise"
WAKE = b"wake"
SPEECH = b"speech"
SILENCE = b"silence"


class FakeAudioInput:
    def __init__(self, frame_sequence: list[bytes]) -> None:
        self._frame_sequence = frame_sequence

    async def frames(self):
        for frame in self._frame_sequence:
            yield frame


class FakeWakeWord:
    def process_frame(self, frame: bytes) -> bool:
        return frame == WAKE


class FakeSilenceDetector:
    def __init__(self) -> None:
        self.reset_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1

    def process_frame(self, frame: bytes) -> bool:
        return frame == SILENCE


class FakeServerClient:
    def __init__(self, events: list) -> None:
        self._events = events
        self.hello_calls: list[str] = []
        self.sent_frames: list[bytes] = []
        self.end_of_speech_calls = 0

    async def connect_with_retry(self) -> None:
        pass

    async def send_hello(self, session_id: str) -> None:
        self.hello_calls.append(session_id)

    async def send_audio_frame(self, frame: bytes) -> None:
        self.sent_frames.append(frame)

    async def send_end_of_speech(self) -> None:
        self.end_of_speech_calls += 1

    async def receive_events(self):
        for event in self._events:
            yield event


class FakeAudioOutput:
    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.stop_calls = 0

    def play_chunk(self, chunk: bytes) -> None:
        self.played.append(chunk)

    def stop(self) -> None:
        self.stop_calls += 1


class FakeFaceDisplay:
    def __init__(self) -> None:
        self.shown: list[Expression] = []

    def show(self, expression: Expression) -> None:
        self.shown.append(expression)


async def test_full_conversation_turn_happy_path():
    audio_input = FakeAudioInput([NOISE, WAKE, SPEECH, SPEECH, SILENCE])
    wake_word = FakeWakeWord()
    silence_detector = FakeSilenceDetector()
    server_client = FakeServerClient(
        events=[
            protocol.EmotionEvent(value="happy"),
            protocol.AudioChunkEvent(data=b"pcm1"),
            protocol.ResponseEndEvent(),
        ]
    )
    audio_output = FakeAudioOutput()
    face_display = FakeFaceDisplay()

    orchestrator = Orchestrator(
        audio_input, wake_word, silence_detector, server_client, audio_output, face_display,
    )

    await orchestrator.run()

    assert server_client.hello_calls == ["haro-session"]
    assert server_client.sent_frames == [SPEECH, SPEECH, SILENCE]
    assert server_client.end_of_speech_calls == 1
    assert audio_output.played == [b"pcm1"]
    assert audio_output.stop_calls == 1
    assert face_display.shown == [
        Expression.IDLE,
        Expression.LISTENING,
        Expression.THINKING,
        Expression.SPEAKING_HAPPY,
        Expression.IDLE,
    ]
    assert orchestrator.state == State.IDLE
    assert silence_detector.reset_calls == 1


async def test_error_event_shows_error_and_returns_to_idle():
    audio_input = FakeAudioInput([WAKE, SILENCE])
    wake_word = FakeWakeWord()
    silence_detector = FakeSilenceDetector()
    server_client = FakeServerClient(events=[protocol.ErrorEvent(message="oops")])
    audio_output = FakeAudioOutput()
    face_display = FakeFaceDisplay()

    orchestrator = Orchestrator(
        audio_input, wake_word, silence_detector, server_client, audio_output, face_display,
    )

    await orchestrator.run()

    assert face_display.shown == [
        Expression.IDLE,
        Expression.LISTENING,
        Expression.THINKING,
        Expression.ERROR,
        Expression.IDLE,
    ]
    assert orchestrator.state == State.IDLE
    assert audio_output.stop_calls == 1


async def test_response_timeout_shows_error_and_returns_to_idle():
    async def never_ends():
        await asyncio.sleep(10)
        yield protocol.ResponseEndEvent()  # pragma: no cover

    class HangingServerClient(FakeServerClient):
        async def receive_events(self):
            async for event in never_ends():
                yield event

    audio_input = FakeAudioInput([WAKE, SILENCE])
    wake_word = FakeWakeWord()
    silence_detector = FakeSilenceDetector()
    server_client = HangingServerClient(events=[])
    audio_output = FakeAudioOutput()
    face_display = FakeFaceDisplay()

    orchestrator = Orchestrator(
        audio_input, wake_word, silence_detector, server_client, audio_output, face_display,
        response_timeout_s=0.05,
    )

    await orchestrator.run()

    assert face_display.shown[-2:] == [Expression.ERROR, Expression.IDLE]
    assert orchestrator.state == State.IDLE
    assert audio_output.stop_calls == 1
