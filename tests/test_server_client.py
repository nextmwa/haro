import json

import pytest

from haro import protocol
from haro.server_client import ServerClient


class FakeConnection:
    def __init__(self, recv_queue: list) -> None:
        self.sent: list = []
        self._recv_queue = list(recv_queue)
        self.closed = False

    async def send(self, data) -> None:
        self.sent.append(data)

    async def recv(self):
        return self._recv_queue.pop(0)

    async def close(self) -> None:
        self.closed = True


def make_connector(connection: FakeConnection, fail_times: int = 0):
    attempts = {"count": 0}

    async def connector(url: str):
        attempts["count"] += 1
        if attempts["count"] <= fail_times:
            raise OSError("connection refused")
        return connection

    connector.attempts = attempts
    return connector


async def test_send_hello_sends_encoded_message():
    connection = FakeConnection(recv_queue=[])
    client = ServerClient("ws://example", connector=make_connector(connection))
    await client.connect()

    await client.send_hello("session-1")

    assert connection.sent == [protocol.encode_hello("session-1")]


async def test_send_audio_frame_sends_raw_bytes():
    connection = FakeConnection(recv_queue=[])
    client = ServerClient("ws://example", connector=make_connector(connection))
    await client.connect()

    await client.send_audio_frame(b"\x01\x02")

    assert connection.sent == [b"\x01\x02"]


async def test_send_end_of_speech_sends_encoded_message():
    connection = FakeConnection(recv_queue=[])
    client = ServerClient("ws://example", connector=make_connector(connection))
    await client.connect()

    await client.send_end_of_speech()

    assert connection.sent == [protocol.encode_end_of_speech()]


async def test_receive_events_parses_text_and_binary_frames():
    connection = FakeConnection(
        recv_queue=[
            json.dumps({"type": "emotion", "value": "happy"}),
            b"\x00\x01",
            json.dumps({"type": "response_end"}),
        ]
    )
    client = ServerClient("ws://example", connector=make_connector(connection))
    await client.connect()

    events = []
    async for event in client.receive_events():
        events.append(event)
        if isinstance(event, protocol.ResponseEndEvent):
            break

    assert events == [
        protocol.EmotionEvent(value="happy"),
        protocol.AudioChunkEvent(data=b"\x00\x01"),
        protocol.ResponseEndEvent(),
    ]


async def test_connect_with_retry_retries_with_backoff_then_succeeds():
    connection = FakeConnection(recv_queue=[])
    connector = make_connector(connection, fail_times=2)
    client = ServerClient("ws://example", connector=connector)

    sleep_calls = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    await client.connect_with_retry(initial_backoff=1.0, max_backoff=30.0, sleep=fake_sleep)

    assert connector.attempts["count"] == 3
    assert sleep_calls == [1.0, 2.0]


async def test_close_closes_the_connection():
    connection = FakeConnection(recv_queue=[])
    client = ServerClient("ws://example", connector=make_connector(connection))
    await client.connect()

    await client.close()

    assert connection.closed is True


async def test_send_hello_before_connect_raises_runtime_error():
    client = ServerClient("ws://example")

    with pytest.raises(RuntimeError, match="not connected"):
        await client.send_hello("session-1")
