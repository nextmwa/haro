import asyncio
import logging
import sys

import openwakeword
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from openwakeword import utils as openwakeword_utils

from .audio_input import AudioInput
from .audio_output import AudioOutput
from .config import Config
from .face_display import Expression, FaceDisplay
from .nmcli import NetworkManagerClient
from .orchestrator import Orchestrator
from .server_client import ServerClient
from .vad import SilenceDetector
from .wake_word import WakeWordDetector
from .wifi_provisioning import WifiProvisioning

logger = logging.getLogger(__name__)


def build_face_display(config: Config) -> FaceDisplay:
    serial = i2c(port=1, address=config.i2c_display_address)
    device = ssd1306(serial)
    return FaceDisplay(device)


def build_orchestrator(
    config: Config, face_display: FaceDisplay,
) -> tuple[Orchestrator, AudioInput, AudioOutput, ServerClient]:
    audio_input = AudioInput(
        frame_size_bytes=config.wake_word_frame_size_bytes,
        device=config.mic_device,
        sample_rate=config.mic_sample_rate,
    )
    logger.info("verifying/downloading wake word model %r", config.wake_word_model)
    openwakeword_utils.download_models([config.wake_word_model])
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

    orchestrator = Orchestrator(
        audio_input=audio_input,
        wake_word=wake_word,
        silence_detector=silence_detector,
        server_client=server_client,
        audio_output=audio_output,
        face_display=face_display,
        response_timeout_s=config.response_timeout_s,
    )
    return orchestrator, audio_input, audio_output, server_client


def build_wifi_provisioning(config: Config, face_display: FaceDisplay) -> WifiProvisioning:
    nm_client = NetworkManagerClient(interface=config.wifi_interface)
    return WifiProvisioning(
        nm_client=nm_client,
        face_display=face_display,
        hotspot_ssid=config.hotspot_ssid,
        hotspot_password=config.hotspot_password,
        setup_server_port=config.setup_server_port,
        check_interval_s=config.wifi_check_interval_s,
        unhealthy_threshold=config.wifi_unhealthy_threshold,
    )


async def run(config_path: str | None) -> None:
    config = Config.from_file(config_path) if config_path else Config.default()
    logger.info("loaded config from %s", config_path or "defaults")
    face_display = build_face_display(config)

    # WiFi must be up before build_orchestrator(), which downloads the wake word
    # model over the network on first run.
    wifi_provisioning = build_wifi_provisioning(config, face_display)
    await wifi_provisioning.ensure_connected()

    orchestrator, audio_input, audio_output, server_client = build_orchestrator(config, face_display)

    try:
        audio_input.start()
    except Exception:
        logger.exception("failed to start audio input")
        face_display.show(Expression.ERROR)
        raise
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(orchestrator.run())
            tg.create_task(wifi_provisioning.monitor())
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.exception("run() failed", exc_info=exc)
        face_display.show(Expression.ERROR)
        raise
    finally:
        logger.info("shutting down")
        # Each teardown step is guarded so one failure cannot skip the others or
        # mask the exception that caused the shutdown.
        for label, shutdown in (("audio input", audio_input.stop), ("audio output", audio_output.stop)):
            try:
                shutdown()
            except Exception:
                logger.exception("error stopping %s", label)
        try:
            await server_client.close()
        except Exception:
            logger.exception("error closing server connection")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
