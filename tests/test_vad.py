from haro.vad import SilenceDetector


class ScriptedVad:
    """Fake VAD returning a scripted sequence of is_speech results."""

    def __init__(self, results: list[bool]) -> None:
        self._results = list(results)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return self._results.pop(0)


def _frame(n: int = 960) -> bytes:
    return b"\x00" * n


def test_process_frame_triggers_after_enough_consecutive_silence():
    # 30ms frames, need 60ms of silence => 2 consecutive silent frames.
    vad = ScriptedVad([False, False])
    detector = SilenceDetector(silence_duration_ms=60, vad=vad)

    assert detector.process_frame(_frame()) is False
    assert detector.process_frame(_frame()) is True


def test_speech_resets_the_silence_counter():
    vad = ScriptedVad([False, True, False, False])
    detector = SilenceDetector(silence_duration_ms=60, vad=vad)

    assert detector.process_frame(_frame()) is False  # silence 1
    assert detector.process_frame(_frame()) is False  # speech resets
    assert detector.process_frame(_frame()) is False  # silence 1 again
    assert detector.process_frame(_frame()) is True   # silence 2 => trigger


def test_reset_clears_counter_and_buffer():
    vad = ScriptedVad([False, False, False, False])
    detector = SilenceDetector(silence_duration_ms=60, vad=vad)

    assert detector.process_frame(_frame()) is False
    detector.reset()
    assert detector.process_frame(_frame()) is False
    assert detector.process_frame(_frame()) is True


def test_process_frame_rechunks_arbitrary_input_sizes():
    # Push one big chunk covering 3 internal 960-byte frames at once.
    vad = ScriptedVad([False, False, False])
    detector = SilenceDetector(silence_duration_ms=60, vad=vad)

    assert detector.process_frame(_frame(960 * 3)) is True
