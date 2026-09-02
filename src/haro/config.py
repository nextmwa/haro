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
