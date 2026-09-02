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
