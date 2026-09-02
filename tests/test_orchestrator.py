import asyncio
import threading

from haro import protocol
from haro.face_display import Expression
from haro.orchestrator import Orchestrator, State

NOISE = b"noise"
WAKE = b"wake"
SPEECH = b"speech"
SILENCE = b"silence"
BOOM = b"boom"


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
        self.connect_calls = 0
        self.hello_calls: list[str] = []
        self.sent_frames: list[bytes] = []
        self.end_of_speech_calls = 0
        self.close_calls = 0

    async def connect_with_retry(self) -> None:
        self.connect_calls += 1

    async def send_hello(self, session_id: str) -> None:
        self.hello_calls.append(session_id)

    async def send_audio_frame(self, frame: bytes) -> None:
        self.sent_frames.append(frame)

    async def send_end_of_speech(self) -> None:
        self.end_of_speech_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

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


def build(server_client, frames, **kwargs):
    """Wire an Orchestrator with the standard fakes; returns it plus the fakes."""
    audio_input = FakeAudioInput(frames)
    wake_word = FakeWakeWord()
    silence_detector = FakeSilenceDetector()
    audio_output = FakeAudioOutput()
    face_display = FakeFaceDisplay()
    orchestrator = Orchestrator(
        audio_input,
        wake_word,
        silence_detector,
        server_client,
        audio_output,
        face_display,
        **kwargs,
    )
    return orchestrator, silence_detector, audio_output, face_display


async def test_full_conversation_turn_happy_path():
    server_client = FakeServerClient(
        events=[
            protocol.EmotionEvent(value="happy"),
            protocol.AudioChunkEvent(data=b"pcm1"),
            protocol.ResponseEndEvent(),
        ]
    )
    orchestrator, silence_detector, audio_output, face_display = build(
        server_client, [NOISE, WAKE, SPEECH, SPEECH, SILENCE]
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


async def test_response_end_does_not_reconnect():
    """A normal turn keeps the persistent connection: no close, no second hello."""
    server_client = FakeServerClient(
        events=[
            protocol.AudioChunkEvent(data=b"pcm1"),
            protocol.ResponseEndEvent(),
        ]
    )
    orchestrator, _, _, _ = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()

    assert server_client.close_calls == 0
    assert server_client.connect_calls == 1  # startup only
    assert server_client.hello_calls == ["haro-session"]  # startup only


async def test_error_event_shows_error_and_returns_to_idle():
    server_client = FakeServerClient(events=[protocol.ErrorEvent(message="oops")])
    orchestrator, _, audio_output, face_display = build(server_client, [WAKE, SILENCE])

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


async def test_error_event_triggers_reconnect():
    server_client = FakeServerClient(events=[protocol.ErrorEvent(message="oops")])
    orchestrator, _, _, _ = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()

    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2  # startup + reconnect
    assert server_client.hello_calls == ["haro-session", "haro-session"]


async def test_response_timeout_shows_error_and_reconnects():
    async def never_ends():
        await asyncio.sleep(10)
        yield protocol.ResponseEndEvent()  # pragma: no cover

    class HangingServerClient(FakeServerClient):
        async def receive_events(self):
            async for event in never_ends():
                yield event  # pragma: no cover

    server_client = HangingServerClient(events=[])
    orchestrator, _, audio_output, face_display = build(
        server_client, [WAKE, SILENCE], response_timeout_s=0.05
    )

    await orchestrator.run()

    assert face_display.shown[-2:] == [Expression.ERROR, Expression.IDLE]
    assert orchestrator.state == State.IDLE
    assert audio_output.stop_calls == 1
    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2  # timeout now also forces a reconnect
    assert server_client.hello_calls == ["haro-session", "haro-session"]


async def test_protocol_error_mid_response_is_caught_and_reconnects():
    """A malformed server message must not kill the process."""

    class BadMessageServerClient(FakeServerClient):
        async def receive_events(self):
            yield protocol.AudioChunkEvent(data=b"pcm1")
            raise protocol.ProtocolError("unknown message type: 'mystery'")

    server_client = BadMessageServerClient(events=[])
    orchestrator, _, audio_output, face_display = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()  # must not raise

    assert audio_output.played == [b"pcm1"]
    assert face_display.shown == [
        Expression.IDLE,
        Expression.LISTENING,
        Expression.THINKING,
        Expression.ERROR,
        Expression.IDLE,
    ]
    assert orchestrator.state == State.IDLE
    assert audio_output.stop_calls == 1
    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2
    assert server_client.hello_calls == ["haro-session", "haro-session"]


async def test_network_error_mid_response_is_caught_and_reconnects():
    class DroppedServerClient(FakeServerClient):
        async def receive_events(self):
            raise OSError("connection reset by peer")
            yield  # pragma: no cover

    server_client = DroppedServerClient(events=[])
    orchestrator, _, _, face_display = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()  # must not raise

    assert face_display.shown[-2:] == [Expression.ERROR, Expression.IDLE]
    assert orchestrator.state == State.IDLE
    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2


async def test_send_audio_frame_failure_reconnects_and_keeps_running():
    """A dropped connection while listening reconnects, then the loop continues."""

    class FlakySendServerClient(FakeServerClient):
        async def send_audio_frame(self, frame: bytes) -> None:
            if frame == BOOM:
                raise OSError("broken pipe")
            await super().send_audio_frame(frame)

    server_client = FlakySendServerClient(
        events=[protocol.AudioChunkEvent(data=b"pcm1"), protocol.ResponseEndEvent()]
    )
    # First turn: wake, then the send fails -> reconnect, back to IDLE.
    # Then a second, complete turn proves the orchestrator kept running.
    orchestrator, silence_detector, audio_output, face_display = build(
        server_client, [WAKE, BOOM, WAKE, SPEECH, SILENCE]
    )

    await orchestrator.run()  # must not raise

    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2
    assert server_client.hello_calls == ["haro-session", "haro-session"]
    # BOOM never made it; the second turn's frames did.
    assert server_client.sent_frames == [SPEECH, SILENCE]
    # reset on the first LISTENING, on the abort, and on the second LISTENING
    assert silence_detector.reset_calls == 3
    assert face_display.shown == [
        Expression.IDLE,
        Expression.LISTENING,
        Expression.ERROR,
        Expression.IDLE,
        Expression.LISTENING,
        Expression.THINKING,
        Expression.IDLE,
    ]
    assert audio_output.played == [b"pcm1"]
    assert server_client.end_of_speech_calls == 1
    assert orchestrator.state == State.IDLE


async def test_end_of_speech_failure_reconnects_and_returns_to_idle():
    class FailingEndOfSpeechClient(FakeServerClient):
        async def send_end_of_speech(self) -> None:
            await super().send_end_of_speech()
            raise OSError("broken pipe")

    server_client = FailingEndOfSpeechClient(events=[])
    orchestrator, _, _, face_display = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()  # must not raise

    assert face_display.shown == [
        Expression.IDLE,
        Expression.LISTENING,
        Expression.THINKING,
        Expression.ERROR,
        Expression.IDLE,
    ]
    assert orchestrator.state == State.IDLE
    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2


async def test_reconnect_survives_a_close_that_raises():
    class UncloseableServerClient(FakeServerClient):
        async def close(self) -> None:
            await super().close()
            raise OSError("socket already gone")

    server_client = UncloseableServerClient(events=[protocol.ErrorEvent(message="oops")])
    orchestrator, _, _, _ = build(server_client, [WAKE, SILENCE])

    await orchestrator.run()  # must not raise

    assert server_client.close_calls == 1
    assert server_client.connect_calls == 2  # reconnect still happened


async def test_audio_playback_is_offloaded_off_the_event_loop():
    """play_chunk/stop are blocking I/O and must run in a worker thread."""
    call_threads: list[int] = []

    class ThreadRecordingOutput(FakeAudioOutput):
        def play_chunk(self, chunk: bytes) -> None:
            call_threads.append(threading.get_ident())
            super().play_chunk(chunk)

        def stop(self) -> None:
            call_threads.append(threading.get_ident())
            super().stop()

    server_client = FakeServerClient(
        events=[protocol.AudioChunkEvent(data=b"pcm1"), protocol.ResponseEndEvent()]
    )
    audio_output = ThreadRecordingOutput()
    face_display = FakeFaceDisplay()
    orchestrator = Orchestrator(
        FakeAudioInput([WAKE, SILENCE]),
        FakeWakeWord(),
        FakeSilenceDetector(),
        server_client,
        audio_output,
        face_display,
    )
    loop_thread = threading.get_ident()

    await orchestrator.run()

    assert call_threads, "expected play_chunk/stop to be called"
    assert all(tid != loop_thread for tid in call_threads)
