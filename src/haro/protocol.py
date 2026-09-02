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

    if not isinstance(data, dict):
        raise ProtocolError(f"expected a JSON object, got: {text!r}")

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
