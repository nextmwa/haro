import json

import pytest

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


def test_from_file_unknown_key_raises_value_error_naming_the_key(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"server_url": "ws://x", "wake_word_treshold": 0.7}))

    with pytest.raises(ValueError, match="wake_word_treshold"):
        Config.from_file(path)


def test_from_file_malformed_json_raises_json_decode_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")

    with pytest.raises(json.JSONDecodeError):
        Config.from_file(path)


def test_from_file_non_object_json_raises_value_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")

    with pytest.raises(ValueError, match="JSON object"):
        Config.from_file(path)
