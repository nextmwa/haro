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
