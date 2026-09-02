from haro.wake_word import WakeWordDetector


class ScriptedModel:
    """Fake wake-word model returning a scripted sequence of score dicts."""

    def __init__(self, score_sequence: list[dict[str, float]]) -> None:
        self._scores = list(score_sequence)
        self.calls: list[bytes] = []

    def predict(self, frame: bytes) -> dict[str, float]:
        self.calls.append(frame)
        return self._scores.pop(0)


def test_process_frame_below_threshold_returns_false():
    model = ScriptedModel([{"hey_haro": 0.2}])
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(b"abcd") is False


def test_process_frame_at_or_above_threshold_returns_true():
    model = ScriptedModel([{"hey_haro": 0.5}])
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(b"abcd") is True


def test_process_frame_missing_key_returns_false():
    model = ScriptedModel([{"other_model": 0.9}])
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(b"abcd") is False


def test_process_frame_buffers_until_full_chunk():
    model = ScriptedModel([{"hey_haro": 0.9}])
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(b"ab") is False  # not enough bytes yet, no predict call
    assert model.calls == []
    assert detector.process_frame(b"cd") is True   # now a full 4-byte chunk triggers predict
    assert model.calls == [b"abcd"]


def test_process_frame_can_score_multiple_chunks_in_one_call():
    model = ScriptedModel([{"hey_haro": 0.1}, {"hey_haro": 0.9}])
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=2)

    assert detector.process_frame(b"abcd") is True
    assert model.calls == [b"ab", b"cd"]
