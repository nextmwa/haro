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
    hotspot_ssid: str = "Haro-Setup"
    hotspot_password: str = "haro1234"
    setup_server_port: int = 8080
    wifi_interface: str = "wlan0"
    wifi_check_interval_s: float = 30.0
    wifi_unhealthy_threshold: int = 3

    @staticmethod
    def default() -> "Config":
        return Config()

    @staticmethod
    def from_file(path: str | Path) -> "Config":
        overrides = json.loads(Path(path).read_text())
        if not isinstance(overrides, dict):
            raise ValueError(f"config file must contain a JSON object, got {type(overrides).__name__}")
        valid_fields = {f.name for f in dataclasses.fields(Config)}
        unknown = set(overrides) - valid_fields
        if unknown:
            raise ValueError(
                f"unknown config key(s): {sorted(unknown)}; valid keys: {sorted(valid_fields)}"
            )
        return dataclasses.replace(Config(), **overrides)
