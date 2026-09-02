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
