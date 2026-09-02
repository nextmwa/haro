import numpy as np
import pytest

from haro.wake_word import WakeWordDetector


class ScriptedModel:
    """Fake wake-word model returning a scripted sequence of score dicts.

    Mirrors the real ``openwakeword.Model.predict`` contract: it accepts only a
    1-D ``numpy.ndarray`` of ``int16`` samples and rejects anything else the way
    the real model does (it raises ``ValueError`` on non-ndarray input). This
    keeps the fake from silently accepting ``bytes`` that would crash on real
    hardware.
    """

    def __init__(self, score_sequence: list[dict[str, float]], expected_samples: int | None = None) -> None:
        self._scores = list(score_sequence)
        self._expected_samples = expected_samples
        self.calls: list[np.ndarray] = []

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        if not isinstance(frame, np.ndarray):
            raise ValueError(f"predict() requires a numpy.ndarray, got {type(frame).__name__}")
        if frame.dtype != np.int16:
            raise ValueError(f"predict() requires int16 samples, got {frame.dtype}")
        if frame.ndim != 1:
            raise ValueError(f"predict() requires 1-D audio, got {frame.ndim} dimensions")
        if self._expected_samples is not None and frame.shape[0] != self._expected_samples:
            raise ValueError(
                f"predict() expected {self._expected_samples} samples, got {frame.shape[0]}"
            )
        self.calls.append(frame)
        return self._scores.pop(0)


def _pcm(*samples: int) -> bytes:
    """Build little-endian int16 PCM bytes from sample values."""
    return np.array(samples, dtype=np.int16).tobytes()


def test_process_frame_below_threshold_returns_false():
    model = ScriptedModel([{"hey_haro": 0.2}], expected_samples=2)
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(_pcm(1, 2)) is False


def test_process_frame_at_or_above_threshold_returns_true():
    model = ScriptedModel([{"hey_haro": 0.5}], expected_samples=2)
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(_pcm(1, 2)) is True


def test_process_frame_missing_key_returns_false():
    model = ScriptedModel([{"other_model": 0.9}], expected_samples=2)
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    assert detector.process_frame(_pcm(1, 2)) is False


def test_process_frame_buffers_until_full_chunk():
    model = ScriptedModel([{"hey_haro": 0.9}], expected_samples=2)
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=4)

    # Not enough bytes yet: no predict call.
    assert detector.process_frame(_pcm(1)) is False
    assert model.calls == []
    # Now a full 4-byte (2-sample) chunk triggers predict.
    assert detector.process_frame(_pcm(2)) is True
    assert len(model.calls) == 1
    np.testing.assert_array_equal(model.calls[0], np.array([1, 2], dtype=np.int16))


def test_process_frame_can_score_multiple_chunks_in_one_call():
    model = ScriptedModel([{"hey_haro": 0.1}, {"hey_haro": 0.9}], expected_samples=1)
    detector = WakeWordDetector(model, "hey_haro", threshold=0.5, frame_size_bytes=2)

    assert detector.process_frame(_pcm(7, 8)) is True
    assert len(model.calls) == 2
    np.testing.assert_array_equal(model.calls[0], np.array([7], dtype=np.int16))
    np.testing.assert_array_equal(model.calls[1], np.array([8], dtype=np.int16))


def test_model_receives_int16_ndarray_of_expected_length():
    """Regression lock: the detector must hand the model numpy int16 samples,
    never raw bytes (the real openwakeword.Model.predict rejects bytes)."""
    frame_size_bytes = 2560
    model = ScriptedModel([{"hey_haro": 0.0}])
    detector = WakeWordDetector(
        model, "hey_haro", threshold=0.5, frame_size_bytes=frame_size_bytes
    )

    detector.process_frame(b"\x00" * frame_size_bytes)

    assert len(model.calls) == 1
    call = model.calls[0]
    assert isinstance(call, np.ndarray)
    assert call.dtype == np.int16
    assert call.shape == (frame_size_bytes // 2,)


def test_scripted_model_rejects_bytes_so_the_fake_cannot_hide_the_bug():
    """Guard on the fake itself: passing bytes must fail loudly, as the real model does."""
    model = ScriptedModel([{"hey_haro": 0.9}])

    with pytest.raises(ValueError, match="numpy.ndarray"):
        model.predict(b"abcd")
