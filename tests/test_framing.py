# tests/test_framing.py
import pytest

from haro.framing import FrameBuffer


def test_push_returns_no_frames_until_enough_bytes():
    buf = FrameBuffer(frame_size_bytes=4)
    assert buf.push(b"ab") == []


def test_push_returns_exact_frame_when_enough_bytes():
    buf = FrameBuffer(frame_size_bytes=4)
    buf.push(b"ab")
    assert buf.push(b"cd") == [b"abcd"]


def test_push_returns_multiple_frames_from_one_call():
    buf = FrameBuffer(frame_size_bytes=2)
    assert buf.push(b"abcdef") == [b"ab", b"cd", b"ef"]


def test_push_carries_over_leftover_bytes():
    buf = FrameBuffer(frame_size_bytes=3)
    assert buf.push(b"abcde") == [b"abc"]
    assert buf.push(b"fg") == [b"def"]


def test_clear_discards_buffered_bytes():
    buf = FrameBuffer(frame_size_bytes=4)
    buf.push(b"ab")
    buf.clear()
    assert buf.push(b"cd") == []


def test_rejects_non_positive_frame_size():
    with pytest.raises(ValueError):
        FrameBuffer(frame_size_bytes=0)
