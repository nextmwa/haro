# Haro Core Voice Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core voice interaction pipeline for the Haro desk robot: wake-word triggered speech capture, streaming to an AI server over WebSocket, streamed audio playback of the response, and face expressions on an OLED display — running as an auto-starting service on a Raspberry Pi 3B+.

**Architecture:** A single Python 3 `asyncio` application composed of small, independently testable modules (config, protocol, framing, VAD, wake word, face display, server client, audio input/output) wired together by an `Orchestrator` state machine. Hardware-touching modules (audio I/O, OLED device) are thin wrappers with the reusable logic factored out into pure, unit-testable pieces; the wrappers themselves are verified manually on the physical Raspberry Pi, not via pytest.

**Tech Stack:** Python 3.11+, `asyncio`, `sounddevice` (audio I/O via ALSA/PortAudio), `websockets` (WebSocket client), `openwakeword` (local wake-word detection), `webrtcvad` (voice activity detection), `luma.oled` + `Pillow` (SSD1306 OLED rendering), `pytest` + `pytest-asyncio` (testing).

**Spec:** `docs/superpowers/specs/2026-09-02-haro-robot-design.md`

## Global Constraints

- Python 3.11+ (needed for `asyncio.timeout`).
- WebSocket protocol messages must exactly match the contract in the spec's "WebSocket protocol" section: JSON control messages `hello`, `end_of_speech` (client→server), `emotion`, `response_end`, `error` (server→client); binary WebSocket frames carry raw 16-bit PCM mono audio.
- Mic sample rate fixed at 16kHz (spec requirement for STT upload).
- Hardware-dependent code (real `sounddevice` streams, real I2C OLED device, real `openwakeword` model) is wrapped so the reusable logic is unit-tested with fakes/injected dependencies; the thin hardware wrapper itself is verified manually on the Raspberry Pi, per the spec's Testing section.
- The sound sensor and the two spare OLED displays are out of scope (spec explicitly excludes them).
- WiFi provisioning is out of scope for this plan (covered by a separate plan); this pipeline assumes the Pi already has network connectivity.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/haro/__init__.py`
- Create: `tests/test_scaffolding.py`

**Interfaces:**
- Produces: an installable `haro` package under `src/haro/`, a `tests/` directory collected by `pytest`, and `pytest-asyncio` configured in auto mode so later `async def test_...` functions need no decorator.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "haro"
version = "0.1.0"
description = "Personal AI desk robot"
requires-python = ">=3.11"
dependencies = [
    "sounddevice>=0.4.6",
    "websockets>=12.0",
    "openwakeword>=0.6.0",
    "webrtcvad>=2.0.10",
    "luma.oled>=3.13.0",
    "Pillow>=10.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create the package init**

Create `src/haro/__init__.py` (empty file).

- [ ] **Step 3: Write a trivial scaffolding test**

```python
# tests/test_scaffolding.py
import haro


def test_package_imports():
    assert haro is not None
```

- [ ] **Step 4: Install the package in editable mode with dev dependencies**

Run: `pip install -e ".[dev]"`
Expected: install succeeds (this pulls in `sounddevice`, `websockets`, `openwakeword`, `webrtcvad`, `luma.oled`, `Pillow`, `pytest`, `pytest-asyncio`).

- [ ] **Step 5: Run the test suite to verify the harness works**

Run: `pytest -v`
Expected: 1 test passes (`test_package_imports`).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/haro/__init__.py tests/test_scaffolding.py
git commit -m "chore: scaffold haro Python package and test harness"
```

---

### Task 2: Frame buffering (`framing.py`)

**Files:**
- Create: `src/haro/framing.py`
- Test: `tests/test_framing.py`

**Interfaces:**
- Produces: `FrameBuffer(frame_size_bytes: int)` with `.push(data: bytes) -> list[bytes]` (returns zero or more complete frames, carrying over any leftover bytes to the next call) and `.clear() -> None`. Used by `wake_word.py`, `vad.py`, and `audio_input.py` in later tasks.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_framing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.framing'`

- [ ] **Step 3: Implement `FrameBuffer`**

```python
# src/haro/framing.py


class FrameBuffer:
    def __init__(self, frame_size_bytes: int) -> None:
        if frame_size_bytes <= 0:
            raise ValueError("frame_size_bytes must be positive")
        self._frame_size = frame_size_bytes
        self._buffer = bytearray()

    def push(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while len(self._buffer) >= self._frame_size:
            frames.append(bytes(self._buffer[: self._frame_size]))
            del self._buffer[: self._frame_size]
        return frames

    def clear(self) -> None:
        self._buffer.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_framing.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/framing.py tests/test_framing.py
git commit -m "feat: add FrameBuffer for fixed-size audio frame chunking"
```

---

### Task 3: Config module

**Files:**
- Create: `src/haro/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass with fields `server_url: str`, `wake_word_model: str`, `wake_word_threshold: float`, `wake_word_frame_size_bytes: int`, `mic_device: str | None`, `speaker_device: str | None`, `mic_sample_rate: int`, `speaker_sample_rate: int`, `i2c_display_address: int`, `end_of_speech_silence_ms: int`, `response_timeout_s: float`; `Config.default() -> Config`; `Config.from_file(path: str | Path) -> Config` (JSON file, missing keys fall back to defaults).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import json

from haro.config import Config


def test_default_config_has_expected_values():
    config = Config.default()
    assert config.server_url == "ws://localhost:8765"
    assert config.wake_word_model == "hey_jarvis"
    assert config.wake_word_threshold == 0.5
    assert config.wake_word_frame_size_bytes == 2560
    assert config.mic_sample_rate == 16000
    assert config.speaker_sample_rate == 24000
    assert config.i2c_display_address == 0x3C
    assert config.end_of_speech_silence_ms == 800
    assert config.response_timeout_s == 15.0


def test_from_file_overrides_only_given_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"server_url": "wss://example.com/ws", "wake_word_threshold": 0.7}))

    config = Config.from_file(path)

    assert config.server_url == "wss://example.com/ws"
    assert config.wake_word_threshold == 0.7
    assert config.wake_word_model == "hey_jarvis"  # untouched default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.config'`

- [ ] **Step 3: Implement `Config`**

```python
# src/haro/config.py
import dataclasses
import json
from pathlib import Path


@dataclasses.dataclass
class Config:
    server_url: str = "ws://localhost:8765"
    wake_word_model: str = "hey_jarvis"
    wake_word_threshold: float = 0.5
    wake_word_frame_size_bytes: int = 2560
    mic_device: str | None = None
    speaker_device: str | None = None
    mic_sample_rate: int = 16000
    speaker_sample_rate: int = 24000
    i2c_display_address: int = 0x3C
    end_of_speech_silence_ms: int = 800
    response_timeout_s: float = 15.0

    @staticmethod
    def default() -> "Config":
        return Config()

    @staticmethod
    def from_file(path: str | Path) -> "Config":
        overrides = json.loads(Path(path).read_text())
        return dataclasses.replace(Config(), **overrides)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/config.py tests/test_config.py
git commit -m "feat: add Config with defaults and JSON file overrides"
```

---

### Task 4: Protocol module

**Files:**
- Create: `src/haro/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Produces: `ProtocolError`; event dataclasses `EmotionEvent(value: str)`, `ResponseEndEvent()`, `ErrorEvent(message: str)`, `AudioChunkEvent(data: bytes)`; `ServerEvent` type alias (union of the four); `encode_hello(session_id: str) -> str`; `encode_end_of_speech() -> str`; `parse_server_message(text: str) -> ServerEvent` (raises `ProtocolError` on invalid JSON or unknown `type`). Used by `server_client.py` and `orchestrator.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_protocol.py
import json

import pytest

from haro import protocol


def test_encode_hello():
    text = protocol.encode_hello("session-123")
    assert json.loads(text) == {"type": "hello", "session_id": "session-123"}


def test_encode_end_of_speech():
    text = protocol.encode_end_of_speech()
    assert json.loads(text) == {"type": "end_of_speech"}


def test_parse_emotion_message():
    event = protocol.parse_server_message('{"type": "emotion", "value": "happy"}')
    assert event == protocol.EmotionEvent(value="happy")


def test_parse_response_end_message():
    event = protocol.parse_server_message('{"type": "response_end"}')
    assert event == protocol.ResponseEndEvent()


def test_parse_error_message():
    event = protocol.parse_server_message('{"type": "error", "message": "boom"}')
    assert event == protocol.ErrorEvent(message="boom")


def test_parse_invalid_json_raises_protocol_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_server_message("not json")


def test_parse_unknown_type_raises_protocol_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_server_message('{"type": "mystery"}')


def test_parse_emotion_missing_value_raises_protocol_error():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_server_message('{"type": "emotion"}')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.protocol'`

- [ ] **Step 3: Implement the protocol module**

```python
# src/haro/protocol.py
import dataclasses
import json
from typing import Union


class ProtocolError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class EmotionEvent:
    value: str


@dataclasses.dataclass(frozen=True)
class ResponseEndEvent:
    pass


@dataclasses.dataclass(frozen=True)
class ErrorEvent:
    message: str


@dataclasses.dataclass(frozen=True)
class AudioChunkEvent:
    data: bytes


ServerEvent = Union[EmotionEvent, ResponseEndEvent, ErrorEvent, AudioChunkEvent]


def encode_hello(session_id: str) -> str:
    return json.dumps({"type": "hello", "session_id": session_id})


def encode_end_of_speech() -> str:
    return json.dumps({"type": "end_of_speech"})


def parse_server_message(text: str) -> ServerEvent:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {text!r}") from exc

    msg_type = data.get("type")
    if msg_type == "emotion":
        value = data.get("value")
        if not isinstance(value, str):
            raise ProtocolError(f"emotion message missing value: {data!r}")
        return EmotionEvent(value=value)
    if msg_type == "response_end":
        return ResponseEndEvent()
    if msg_type == "error":
        return ErrorEvent(message=data.get("message", ""))
    raise ProtocolError(f"unknown message type: {msg_type!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_protocol.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/protocol.py tests/test_protocol.py
git commit -m "feat: add WebSocket protocol encode/decode for robot<->server contract"
```

---

### Task 5: Voice activity detection (`vad.py`)

**Files:**
- Create: `src/haro/vad.py`
- Test: `tests/test_vad.py`

**Interfaces:**
- Consumes: `haro.framing.FrameBuffer`.
- Produces: `VadLike` protocol (`is_speech(frame: bytes, sample_rate: int) -> bool`); `SilenceDetector(sample_rate=16000, vad_frame_duration_ms=30, silence_duration_ms=800, aggressiveness=2, vad=None)` with `.process_frame(frame: bytes) -> bool` (returns `True` once enough consecutive silence has been seen since the last `reset()`/trigger) and `.reset() -> None`. Used by `orchestrator.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vad.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vad.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.vad'`

- [ ] **Step 3: Implement `SilenceDetector`**

```python
# src/haro/vad.py
from typing import Protocol

import webrtcvad

from .framing import FrameBuffer


class VadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class SilenceDetector:
    def __init__(
        self,
        sample_rate: int = 16000,
        vad_frame_duration_ms: int = 30,
        silence_duration_ms: int = 800,
        aggressiveness: int = 2,
        vad: VadLike | None = None,
    ) -> None:
        self._vad = vad if vad is not None else webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        frame_size_bytes = int(sample_rate * vad_frame_duration_ms / 1000) * 2  # 16-bit mono
        self._buffer = FrameBuffer(frame_size_bytes)
        self._silence_frames_needed = max(1, silence_duration_ms // vad_frame_duration_ms)
        self._consecutive_silence = 0

    def reset(self) -> None:
        self._consecutive_silence = 0
        self._buffer.clear()

    def process_frame(self, frame: bytes) -> bool:
        triggered = False
        for chunk in self._buffer.push(frame):
            if self._vad.is_speech(chunk, self._sample_rate):
                self._consecutive_silence = 0
            else:
                self._consecutive_silence += 1
            if self._consecutive_silence >= self._silence_frames_needed:
                triggered = True
        return triggered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vad.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/vad.py tests/test_vad.py
git commit -m "feat: add SilenceDetector for end-of-speech detection"
```

---

### Task 6: Wake word detection (`wake_word.py`)

**Files:**
- Create: `src/haro/wake_word.py`
- Test: `tests/test_wake_word.py`

**Interfaces:**
- Consumes: `haro.framing.FrameBuffer`.
- Produces: `WakeWordModel` protocol (`predict(frame) -> dict[str, float]`); `WakeWordDetector(model, model_name: str, threshold: float = 0.5, frame_size_bytes: int = 2560)` with `.process_frame(frame: bytes) -> bool`. Used by `orchestrator.py`; real `openwakeword.Model` instance is injected as `model` in `main.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wake_word.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wake_word.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.wake_word'`

- [ ] **Step 3: Implement `WakeWordDetector`**

```python
# src/haro/wake_word.py
from typing import Protocol

from .framing import FrameBuffer


class WakeWordModel(Protocol):
    def predict(self, frame) -> dict[str, float]: ...


class WakeWordDetector:
    def __init__(
        self,
        model: WakeWordModel,
        model_name: str,
        threshold: float = 0.5,
        frame_size_bytes: int = 2560,
    ) -> None:
        self._model = model
        self._model_name = model_name
        self._threshold = threshold
        self._buffer = FrameBuffer(frame_size_bytes)

    def process_frame(self, frame: bytes) -> bool:
        triggered = False
        for chunk in self._buffer.push(frame):
            scores = self._model.predict(chunk)
            if scores.get(self._model_name, 0.0) >= self._threshold:
                triggered = True
        return triggered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wake_word.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/wake_word.py tests/test_wake_word.py
git commit -m "feat: add WakeWordDetector with internal frame buffering"
```

---

### Task 7: Face display (`face_display.py`)

**Files:**
- Create: `src/haro/face_display.py`
- Test: `tests/test_face_display.py`

**Interfaces:**
- Produces: `Expression` enum (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING_HAPPY`, `SPEAKING_SAD`, `SPEAKING_CONFUSED`, `SPEAKING_NEUTRAL`, `ERROR`, `SETUP`); `expression_for_emotion(value: str) -> Expression`; `render_expression(expression: Expression, size: tuple[int, int] = (128, 64)) -> PIL.Image.Image`; `DisplayDevice` protocol (`width`, `height`, `display(image) -> None`); `FaceDisplay(device: DisplayDevice)` with `.show(expression: Expression) -> None`. `expression_for_emotion` and `Expression` are used by `orchestrator.py`; `FaceDisplay` is used by `orchestrator.py` and wired to a real `luma.oled` device in `main.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_face_display.py
from haro.face_display import (
    Expression,
    FaceDisplay,
    expression_for_emotion,
    render_expression,
)


def test_expression_for_emotion_known_values():
    assert expression_for_emotion("happy") == Expression.SPEAKING_HAPPY
    assert expression_for_emotion("sad") == Expression.SPEAKING_SAD
    assert expression_for_emotion("confused") == Expression.SPEAKING_CONFUSED
    assert expression_for_emotion("neutral") == Expression.SPEAKING_NEUTRAL


def test_expression_for_emotion_unknown_defaults_to_neutral():
    assert expression_for_emotion("bewildered") == Expression.SPEAKING_NEUTRAL


def test_render_expression_returns_correct_size():
    image = render_expression(Expression.IDLE, size=(128, 64))
    assert image.size == (128, 64)


def test_render_expression_differs_between_expressions():
    idle = render_expression(Expression.IDLE, size=(128, 64))
    happy = render_expression(Expression.SPEAKING_HAPPY, size=(128, 64))
    sad = render_expression(Expression.SPEAKING_SAD, size=(128, 64))
    assert idle.tobytes() != happy.tobytes()
    assert happy.tobytes() != sad.tobytes()


class FakeDevice:
    def __init__(self, width: int = 128, height: int = 64) -> None:
        self.width = width
        self.height = height
        self.displayed = []

    def display(self, image) -> None:
        self.displayed.append(image)


def test_face_display_show_renders_to_device():
    device = FakeDevice()
    face = FaceDisplay(device)

    face.show(Expression.LISTENING)

    assert len(device.displayed) == 1
    assert device.displayed[0].size == (128, 64)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_face_display.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.face_display'`

- [ ] **Step 3: Implement `face_display.py`**

```python
# src/haro/face_display.py
import enum
from typing import Protocol

from PIL import Image, ImageDraw


class Expression(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING_HAPPY = "speaking_happy"
    SPEAKING_SAD = "speaking_sad"
    SPEAKING_CONFUSED = "speaking_confused"
    SPEAKING_NEUTRAL = "speaking_neutral"
    ERROR = "error"
    SETUP = "setup"


class DisplayDevice(Protocol):
    width: int
    height: int

    def display(self, image: Image.Image) -> None: ...


_EMOTION_TO_EXPRESSION = {
    "happy": Expression.SPEAKING_HAPPY,
    "sad": Expression.SPEAKING_SAD,
    "confused": Expression.SPEAKING_CONFUSED,
    "neutral": Expression.SPEAKING_NEUTRAL,
}


def expression_for_emotion(value: str) -> Expression:
    return _EMOTION_TO_EXPRESSION.get(value, Expression.SPEAKING_NEUTRAL)


def render_expression(expression: Expression, size: tuple[int, int] = (128, 64)) -> Image.Image:
    width, height = size
    image = Image.new("1", size, 0)
    draw = ImageDraw.Draw(image)

    eye_y = height // 3
    eye_radius = max(2, height // 8)
    left_eye_x = width // 3
    right_eye_x = 2 * width // 3
    mouth_y = int(height * 0.7)
    mouth_half_width = width // 4
    mouth_cx = width // 2

    def open_eye(cx: int, cy: int, r: int) -> None:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=1, fill=1)

    def closed_eye(cx: int, cy: int, r: int) -> None:
        draw.line((cx - r, cy, cx + r, cy), fill=1, width=2)

    if expression in (Expression.THINKING, Expression.ERROR):
        closed_eye(left_eye_x, eye_y, eye_radius)
        closed_eye(right_eye_x, eye_y, eye_radius)
    else:
        open_eye(left_eye_x, eye_y, eye_radius)
        open_eye(right_eye_x, eye_y, eye_radius)

    if expression == Expression.SPEAKING_HAPPY:
        draw.arc(
            (mouth_cx - mouth_half_width, mouth_y - 10, mouth_cx + mouth_half_width, mouth_y + 15),
            start=20, end=160, fill=1, width=2,
        )
    elif expression == Expression.SPEAKING_SAD:
        draw.arc(
            (mouth_cx - mouth_half_width, mouth_y, mouth_cx + mouth_half_width, mouth_y + 25),
            start=200, end=340, fill=1, width=2,
        )
    elif expression == Expression.SPEAKING_CONFUSED:
        draw.line(
            (mouth_cx - mouth_half_width, mouth_y, mouth_cx, mouth_y + 8, mouth_cx + mouth_half_width, mouth_y),
            fill=1, width=2,
        )
    elif expression == Expression.ERROR:
        draw.line((mouth_cx - mouth_half_width, mouth_y + 10, mouth_cx + mouth_half_width, mouth_y - 5), fill=1, width=2)
        draw.line((mouth_cx - mouth_half_width, mouth_y - 5, mouth_cx + mouth_half_width, mouth_y + 10), fill=1, width=2)
    elif expression == Expression.SETUP:
        draw.text((mouth_cx - 20, mouth_y - 5), "setup", fill=1)
    else:
        draw.line((mouth_cx - mouth_half_width, mouth_y, mouth_cx + mouth_half_width, mouth_y), fill=1, width=2)

    return image


class FaceDisplay:
    def __init__(self, device: DisplayDevice) -> None:
        self._device = device

    def show(self, expression: Expression) -> None:
        image = render_expression(expression, (self._device.width, self._device.height))
        self._device.display(image)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_face_display.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/face_display.py tests/test_face_display.py
git commit -m "feat: add FaceDisplay with expression rendering"
```

---

### Task 8: Server client (`server_client.py`)

**Files:**
- Create: `src/haro/server_client.py`
- Test: `tests/test_server_client.py`

**Interfaces:**
- Consumes: `haro.protocol` (`encode_hello`, `encode_end_of_speech`, `parse_server_message`, `AudioChunkEvent`).
- Produces: `ServerClient(url: str, connector=None)` with `async def connect() -> None`, `async def connect_with_retry(initial_backoff=1.0, max_backoff=30.0, sleep=asyncio.sleep) -> None`, `async def close() -> None`, `async def send_hello(session_id: str) -> None`, `async def send_audio_frame(frame: bytes) -> None`, `async def send_end_of_speech() -> None`, `def receive_events(self) -> AsyncIterator[protocol.ServerEvent]` (async generator). Used by `orchestrator.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server_client.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_server_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.server_client'`

- [ ] **Step 3: Implement `ServerClient`**

```python
# src/haro/server_client.py
import asyncio
from typing import AsyncIterator, Protocol

from . import protocol


class WebSocketLike(Protocol):
    async def send(self, data) -> None: ...
    async def recv(self): ...
    async def close(self) -> None: ...


async def _default_connector(url: str) -> WebSocketLike:
    import websockets

    return await websockets.connect(url)


class ServerClient:
    def __init__(self, url: str, connector=None) -> None:
        self._url = url
        self._connector = connector if connector is not None else _default_connector
        self._connection: WebSocketLike | None = None

    async def connect(self) -> None:
        self._connection = await self._connector(self._url)

    async def connect_with_retry(
        self,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        sleep=asyncio.sleep,
    ) -> None:
        backoff = initial_backoff
        while True:
            try:
                await self.connect()
                return
            except OSError:
                await sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def send_hello(self, session_id: str) -> None:
        await self._connection.send(protocol.encode_hello(session_id))

    async def send_audio_frame(self, frame: bytes) -> None:
        await self._connection.send(frame)

    async def send_end_of_speech(self) -> None:
        await self._connection.send(protocol.encode_end_of_speech())

    async def receive_events(self) -> AsyncIterator[protocol.ServerEvent]:
        while True:
            message = await self._connection.recv()
            if isinstance(message, bytes):
                yield protocol.AudioChunkEvent(data=message)
            else:
                yield protocol.parse_server_message(message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_server_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/server_client.py tests/test_server_client.py
git commit -m "feat: add ServerClient with reconnect-with-backoff and protocol I/O"
```

---

### Task 9: Audio input (`audio_input.py`)

**Files:**
- Create: `src/haro/audio_input.py`

**Interfaces:**
- Consumes: `haro.framing.FrameBuffer`.
- Produces: `AudioInput(frame_size_bytes: int, device: str | None = None, sample_rate: int = 16000)` with `.start() -> None`, `.stop() -> None`, `async def frames(self) -> AsyncIterator[bytes]`. Used by `orchestrator.py` (via the `frames()` iterator) and wired to real hardware in `main.py`.
- This module wraps `sounddevice`, a real audio hardware library. Its frame-chunking logic is already covered by `tests/test_framing.py` (Task 2); this task has no additional pytest suite — it is verified manually on the Raspberry Pi per the spec's Testing section, since it requires a physical INMP441 microphone.

- [ ] **Step 1: Implement `AudioInput`**

```python
# src/haro/audio_input.py
import asyncio
from typing import AsyncIterator

from .framing import FrameBuffer


class AudioInput:
    def __init__(self, frame_size_bytes: int, device: str | None = None, sample_rate: int = 16000) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._buffer = FrameBuffer(frame_size_bytes)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        for frame in self._buffer.push(bytes(indata)):
            self._queue.put_nowait(frame)

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            yield frame
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python -c "from haro.audio_input import AudioInput; print('ok')"`
Expected: prints `ok` (this only checks the module and its `sounddevice` import load correctly; `start()`/`stop()` require real audio hardware and are verified manually on the Raspberry Pi later, per Task 13).

- [ ] **Step 3: Commit**

```bash
git add src/haro/audio_input.py
git commit -m "feat: add AudioInput wrapper around sounddevice capture"
```

---

### Task 10: Audio output (`audio_output.py`)

**Files:**
- Create: `src/haro/audio_output.py`
- Test: `tests/test_audio_output.py`

**Interfaces:**
- Produces: `OutputStreamLike` protocol (`write(data: bytes) -> None`, `start() -> None`, `stop() -> None`, `close() -> None`); `AudioOutput(stream: OutputStreamLike | None = None, device: str | None = None, sample_rate: int = 24000)` with `.play_chunk(chunk: bytes) -> None`, `.stop() -> None`. Used by `orchestrator.py`; when `stream=None`, wired to a real `sounddevice.RawOutputStream` lazily on first use (production path, exercised manually on the Pi).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audio_output.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audio_output.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.audio_output'`

- [ ] **Step 3: Implement `AudioOutput`**

```python
# src/haro/audio_output.py
from typing import Protocol


class OutputStreamLike(Protocol):
    def write(self, data: bytes) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class AudioOutput:
    def __init__(
        self,
        stream: OutputStreamLike | None = None,
        device: str | None = None,
        sample_rate: int = 24000,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._injected_stream = stream
        self._stream: OutputStreamLike | None = None
        self._started = False

    def _get_stream(self) -> OutputStreamLike:
        if self._injected_stream is not None:
            return self._injected_stream
        if self._stream is None:
            import sounddevice as sd

            self._stream = sd.RawOutputStream(
                samplerate=self._sample_rate, channels=1, dtype="int16", device=self._device,
            )
        return self._stream

    def play_chunk(self, chunk: bytes) -> None:
        stream = self._get_stream()
        if not self._started:
            stream.start()
            self._started = True
        stream.write(chunk)

    def stop(self) -> None:
        if self._started:
            stream = self._get_stream()
            stream.stop()
            stream.close()
            self._started = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_audio_output.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/audio_output.py tests/test_audio_output.py
git commit -m "feat: add AudioOutput with lazy start and injectable stream"
```

---

### Task 11: Orchestrator state machine (`orchestrator.py`)

**Files:**
- Create: `src/haro/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `haro.protocol` (`EmotionEvent`, `AudioChunkEvent`, `ErrorEvent`, `ResponseEndEvent`), `haro.face_display` (`Expression`, `expression_for_emotion`).
- Produces: `State` enum (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`); `Orchestrator(audio_input, wake_word, silence_detector, server_client, audio_output, face_display, response_timeout_s=15.0, session_id="haro-session")` with `async def run(self) -> None` and a public `.state: State` attribute. This is the top-level piece wired up with real components in `main.py` (Task 13).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orchestrator.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.orchestrator'`

- [ ] **Step 3: Implement `Orchestrator`**

```python
# src/haro/orchestrator.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add Orchestrator state machine wiring the full pipeline"
```

---

### Task 12: Fake development server (`tools/fake_server.py`)

**Files:**
- Create: `tools/fake_server.py`

**Interfaces:**
- Standalone script implementing the server side of the protocol from `docs/superpowers/specs/2026-09-02-haro-robot-design.md` with canned responses, for manual end-to-end testing of the pipeline before the real AI server exists. Not imported by any `haro` module.

- [ ] **Step 1: Implement the fake server**

```python
# tools/fake_server.py
"""Minimal mock AI server for local development and manual testing.

Implements the robot<->server WebSocket protocol described in
docs/superpowers/specs/2026-09-02-haro-robot-design.md with a canned
response, so the Haro pipeline can be exercised end-to-end before the
real AI server exists.
"""
import asyncio
import json
import math
import struct

import websockets

SAMPLE_RATE = 24000


def _make_tone(duration_s: float, frequency_hz: float) -> bytes:
    num_samples = int(SAMPLE_RATE * duration_s)
    samples = [
        int(32767 * 0.3 * math.sin(2 * math.pi * frequency_hz * i / SAMPLE_RATE))
        for i in range(num_samples)
    ]
    return struct.pack(f"<{num_samples}h", *samples)


async def handle_connection(websocket):
    async for message in websocket:
        if isinstance(message, str):
            data = json.loads(message)
            if data.get("type") == "end_of_speech":
                await websocket.send(json.dumps({"type": "emotion", "value": "happy"}))
                tone = _make_tone(duration_s=1.0, frequency_hz=440.0)
                chunk_size = 4096
                for i in range(0, len(tone), chunk_size):
                    await websocket.send(tone[i : i + chunk_size])
                await websocket.send(json.dumps({"type": "response_end"}))
        # Binary audio frames sent by the robot while listening are ignored by this mock.


async def main() -> None:
    async with websockets.serve(handle_connection, "0.0.0.0", 8765):
        print("Fake Haro server listening on ws://0.0.0.0:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Manually verify the fake server responds correctly**

Run the server in one terminal: `python tools/fake_server.py`
Expected: prints `Fake Haro server listening on ws://0.0.0.0:8765`

In a second terminal, run this verification snippet:

```bash
python - <<'EOF'
import asyncio
import json

import websockets


async def main():
    async with websockets.connect("ws://localhost:8765") as ws:
        await ws.send(json.dumps({"type": "hello", "session_id": "test"}))
        await ws.send(json.dumps({"type": "end_of_speech"}))
        first = await ws.recv()
        print("first message:", first)
        assert json.loads(first) == {"type": "emotion", "value": "happy"}
        chunk = await ws.recv()
        print("received audio chunk of", len(chunk), "bytes")
        assert isinstance(chunk, bytes)


asyncio.run(main())
EOF
```

Expected: prints the emotion message and an audio chunk size, no assertion errors.

- [ ] **Step 3: Commit**

```bash
git add tools/fake_server.py
git commit -m "chore: add fake WebSocket server for manual pipeline testing"
```

---

### Task 13: Entry point (`main.py`)

**Files:**
- Create: `src/haro/main.py`

**Interfaces:**
- Consumes: `Config` (Task 3), `AudioInput` (Task 9), `WakeWordDetector` (Task 6), `SilenceDetector` (Task 5), `ServerClient` (Task 8), `AudioOutput` (Task 10), `FaceDisplay` (Task 7), `Orchestrator` (Task 11).
- Produces: `build_orchestrator(config: Config) -> tuple[Orchestrator, AudioInput, AudioOutput, FaceDisplay]`; `async def run(config_path: str | None) -> None`; `main() -> None` (console entry point). Wires real hardware (sounddevice via `AudioInput`/`AudioOutput`, `openwakeword.Model`, `luma.oled` SSD1306 over I2C) — verified manually on the Raspberry Pi, not via pytest.

- [ ] **Step 1: Implement `main.py`**

```python
# src/haro/main.py
import asyncio
import sys

import openwakeword
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306

from .audio_input import AudioInput
from .audio_output import AudioOutput
from .config import Config
from .face_display import Expression, FaceDisplay
from .orchestrator import Orchestrator
from .server_client import ServerClient
from .vad import SilenceDetector
from .wake_word import WakeWordDetector


def build_orchestrator(config: Config) -> tuple[Orchestrator, AudioInput, AudioOutput, FaceDisplay]:
    audio_input = AudioInput(
        frame_size_bytes=config.wake_word_frame_size_bytes,
        device=config.mic_device,
        sample_rate=config.mic_sample_rate,
    )
    model = openwakeword.Model(wakeword_models=[config.wake_word_model])
    wake_word = WakeWordDetector(
        model=model,
        model_name=config.wake_word_model,
        threshold=config.wake_word_threshold,
        frame_size_bytes=config.wake_word_frame_size_bytes,
    )
    silence_detector = SilenceDetector(
        sample_rate=config.mic_sample_rate,
        silence_duration_ms=config.end_of_speech_silence_ms,
    )
    server_client = ServerClient(url=config.server_url)
    audio_output = AudioOutput(device=config.speaker_device, sample_rate=config.speaker_sample_rate)

    serial = i2c(port=1, address=config.i2c_display_address)
    device = ssd1306(serial)
    face_display = FaceDisplay(device)

    orchestrator = Orchestrator(
        audio_input=audio_input,
        wake_word=wake_word,
        silence_detector=silence_detector,
        server_client=server_client,
        audio_output=audio_output,
        face_display=face_display,
        response_timeout_s=config.response_timeout_s,
    )
    return orchestrator, audio_input, audio_output, face_display


async def run(config_path: str | None) -> None:
    config = Config.from_file(config_path) if config_path else Config.default()
    orchestrator, audio_input, audio_output, face_display = build_orchestrator(config)
    try:
        audio_input.start()
    except Exception:
        face_display.show(Expression.ERROR)
        raise
    try:
        await orchestrator.run()
    finally:
        audio_input.stop()
        audio_output.stop()


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manually verify end-to-end on the Raspberry Pi**

With the fake server from Task 12 running (`python tools/fake_server.py`) and a `config.json` on the Pi pointing `server_url` at it (`ws://<fake-server-host>:8765`), run:

`python -m haro.main config.json`

Expected: the OLED shows the idle face; saying the configured wake word (default `hey_jarvis`) switches it to listening, then thinking, then the happy expression while a 440Hz tone plays through the speaker, then it returns to idle. This step requires the physical INMP441, MAX98357A/speaker, and OLED wired up per the spec's hardware table — it is a hardware verification step, not an automated test.

- [ ] **Step 3: Commit**

```bash
git add src/haro/main.py
git commit -m "feat: add main entry point wiring real hardware to the orchestrator"
```

---

### Task 14: systemd service packaging

**Files:**
- Create: `systemd/haro.service`

**Interfaces:**
- Standalone systemd unit file; not consumed by any Python module. Depends on `haro.main:main` (Task 13) being installed and runnable via a Python interpreter path on the Pi.

- [ ] **Step 1: Create the systemd unit file**

```ini
# systemd/haro.service
[Unit]
Description=Haro personal AI desk robot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/haro
ExecStart=/home/pi/haro/.venv/bin/python -m haro.main /home/pi/haro/config.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Manually verify the service starts on boot**

On the Raspberry Pi, with the project checked out at `/home/pi/haro` and a virtualenv at `/home/pi/haro/.venv` with the package installed (`pip install -e ".[dev]"` or a plain install), and a real `config.json` in place:

```bash
sudo cp systemd/haro.service /etc/systemd/system/haro.service
sudo systemctl daemon-reload
sudo systemctl enable --now haro.service
sudo systemctl status haro.service
```

Expected: `systemctl status` shows `active (running)`. Confirm logs with `journalctl -u haro.service -f`, and confirm a reboot (`sudo reboot`) brings the robot back up automatically without any login or keyboard interaction.

- [ ] **Step 3: Commit**

```bash
git add systemd/haro.service
git commit -m "chore: add systemd service for automatic startup on boot"
```
