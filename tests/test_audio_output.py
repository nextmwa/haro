from haro.audio_output import AudioOutput


class FakeStream:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self) -> None:
        self.calls.append(("start",))

    def write(self, data: bytes) -> None:
        self.calls.append(("write", data))

    def stop(self) -> None:
        self.calls.append(("stop",))

    def close(self) -> None:
        self.calls.append(("close",))


def test_play_chunk_starts_stream_once_then_writes():
    stream = FakeStream()
    output = AudioOutput(stream=stream)

    output.play_chunk(b"chunk1")
    output.play_chunk(b"chunk2")

    assert stream.calls == [
        ("start",),
        ("write", b"chunk1"),
        ("write", b"chunk2"),
    ]


def test_stop_stops_and_closes_started_stream():
    stream = FakeStream()
    output = AudioOutput(stream=stream)
    output.play_chunk(b"chunk1")

    output.stop()

    assert stream.calls[-2:] == [("stop",), ("close",)]


def test_stop_is_a_no_op_if_never_started():
    stream = FakeStream()
    output = AudioOutput(stream=stream)

    output.stop()

    assert stream.calls == []


def test_play_chunk_after_stop_restarts_stream():
    stream = FakeStream()
    output = AudioOutput(stream=stream)
    output.play_chunk(b"chunk1")
    output.stop()

    output.play_chunk(b"chunk2")

    assert stream.calls[-2:] == [("start",), ("write", b"chunk2")]


def test_stop_resets_cached_stream_for_real_playback_path():
    output = AudioOutput(stream=None, device=None, sample_rate=24000)
    output._stream = FakeStream()  # simulate a previously-created real stream
    output._started = True

    output.stop()

    assert output._stream is None
