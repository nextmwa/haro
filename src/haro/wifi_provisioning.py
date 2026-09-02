import asyncio
import logging
from typing import Protocol

from aiohttp import web

from .face_display import Expression
from .setup_server import create_setup_app

logger = logging.getLogger(__name__)


class FaceDisplayLike(Protocol):
    def show(self, expression: Expression) -> None: ...


class NetworkManagerClientLike(Protocol):
    def is_connected(self) -> bool: ...
    def scan_networks(self) -> list[str]: ...
    def connect(self, ssid: str, password: str) -> None: ...
    def start_hotspot(self, ssid: str, password: str) -> None: ...
    def stop_hotspot(self) -> None: ...


class ServerRunnerLike(Protocol):
    async def serve_until(
        self, app: web.Application, port: int, stop_event: asyncio.Event
    ) -> None: ...


class AiohttpServerRunner:
    async def serve_until(
        self, app: web.Application, port: int, stop_event: asyncio.Event
    ) -> None:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        try:
            await stop_event.wait()
        finally:
            await runner.cleanup()


class WifiProvisioning:
    def __init__(
        self,
        nm_client: NetworkManagerClientLike,
        face_display: FaceDisplayLike,
        hotspot_ssid: str,
        hotspot_password: str,
        setup_server_port: int = 8080,
        server_runner: ServerRunnerLike | None = None,
        check_interval_s: float = 30.0,
        unhealthy_threshold: int = 3,
    ) -> None:
        self._nm_client = nm_client
        self._face_display = face_display
        self._hotspot_ssid = hotspot_ssid
        self._hotspot_password = hotspot_password
        self._setup_server_port = setup_server_port
        self._server_runner = server_runner if server_runner is not None else AiohttpServerRunner()
        self._check_interval_s = check_interval_s
        self._unhealthy_threshold = unhealthy_threshold

    async def ensure_connected(self) -> None:
        if await asyncio.to_thread(self._nm_client.is_connected):
            return

        logger.info("no known WiFi connection, entering setup mode")
        self._face_display.show(Expression.SETUP)
        networks = await asyncio.to_thread(self._nm_client.scan_networks)
        await asyncio.to_thread(
            self._nm_client.start_hotspot, self._hotspot_ssid, self._hotspot_password
        )

        stop_event = asyncio.Event()

        async def on_submit(ssid: str, password: str) -> bool:
            try:
                await asyncio.to_thread(self._nm_client.connect, ssid, password)
            except Exception as exc:
                logger.warning("failed to connect to %s: %s", ssid, exc)
                return False
            if await asyncio.to_thread(self._nm_client.is_connected):
                stop_event.set()
                return True
            return False

        app = create_setup_app(networks, on_submit)
        try:
            await self._server_runner.serve_until(app, self._setup_server_port, stop_event)
        finally:
            await asyncio.to_thread(self._nm_client.stop_hotspot)

        logger.info("WiFi setup complete, resuming normal operation")
        self._face_display.show(Expression.IDLE)

    async def monitor(self) -> None:
        consecutive_failures = 0
        while True:
            await asyncio.sleep(self._check_interval_s)
            if await asyncio.to_thread(self._nm_client.is_connected):
                consecutive_failures = 0
                continue
            consecutive_failures += 1
            logger.warning(
                "WiFi check failed (%d/%d)", consecutive_failures, self._unhealthy_threshold
            )
            if consecutive_failures >= self._unhealthy_threshold:
                consecutive_failures = 0
                try:
                    await self.ensure_connected()
                except Exception as exc:
                    logger.warning("ensure_connected failed during monitor re-entry: %s", exc)
