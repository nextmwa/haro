import asyncio

from aiohttp.test_utils import TestClient, TestServer

from haro.face_display import Expression
from haro.wifi_provisioning import WifiProvisioning


class FakeNmClient:
    def __init__(self, connected_sequence: list[bool]) -> None:
        self._connected_sequence = list(connected_sequence)
        self.scan_calls = 0
        self.start_hotspot_calls: list[tuple[str, str]] = []
        self.stop_hotspot_calls = 0
        self.connect_calls: list[tuple[str, str]] = []

    def is_connected(self) -> bool:
        if len(self._connected_sequence) > 1:
            return self._connected_sequence.pop(0)
        return self._connected_sequence[0]

    def scan_networks(self) -> list[str]:
        self.scan_calls += 1
        return ["HomeWifi"]

    def connect(self, ssid: str, password: str) -> None:
        self.connect_calls.append((ssid, password))

    def start_hotspot(self, ssid: str, password: str) -> None:
        self.start_hotspot_calls.append((ssid, password))

    def stop_hotspot(self) -> None:
        self.stop_hotspot_calls += 1


class FakeFaceDisplay:
    def __init__(self) -> None:
        self.shown: list[Expression] = []

    def show(self, expression: Expression) -> None:
        self.shown.append(expression)


class FakeServerRunner:
    """Simulates a client submitting a working network choice as soon as the server starts,
    by driving the real setup_server app through aiohttp's own test client — no real
    TCP port is bound."""

    def __init__(self, ssid: str = "HomeWifi", password: str = "secret") -> None:
        self._ssid = ssid
        self._password = password

    async def serve_until(self, app, port, stop_event):
        async with TestClient(TestServer(app)) as client:
            await client.post("/connect", data={"ssid": self._ssid, "password": self._password})
        await stop_event.wait()


async def test_ensure_connected_skips_setup_when_already_connected():
    nm_client = FakeNmClient(connected_sequence=[True])
    face_display = FakeFaceDisplay()
    provisioning = WifiProvisioning(
        nm_client, face_display, "Haro-Setup", "haro1234", server_runner=FakeServerRunner(),
    )

    await provisioning.ensure_connected()

    assert face_display.shown == []
    assert nm_client.start_hotspot_calls == []


async def test_ensure_connected_runs_setup_flow_when_not_connected():
    nm_client = FakeNmClient(connected_sequence=[False, True])
    face_display = FakeFaceDisplay()
    provisioning = WifiProvisioning(
        nm_client, face_display, "Haro-Setup", "haro1234",
        server_runner=FakeServerRunner(ssid="HomeWifi", password="secret"),
    )

    await provisioning.ensure_connected()

    assert face_display.shown == [Expression.SETUP]
    assert nm_client.scan_calls == 1
    assert nm_client.start_hotspot_calls == [("Haro-Setup", "haro1234")]
    assert nm_client.connect_calls == [("HomeWifi", "secret")]
    assert nm_client.stop_hotspot_calls == 1


async def test_monitor_calls_ensure_connected_after_threshold_failures():
    nm_client = FakeNmClient(connected_sequence=[False])
    face_display = FakeFaceDisplay()
    provisioning = WifiProvisioning(
        nm_client, face_display, "Haro-Setup", "haro1234",
        server_runner=FakeServerRunner(),
        check_interval_s=0.01, unhealthy_threshold=3,
    )
    triggered = asyncio.Event()
    ensure_connected_calls = 0

    async def fake_ensure_connected() -> None:
        nonlocal ensure_connected_calls
        ensure_connected_calls += 1
        triggered.set()

    provisioning.ensure_connected = fake_ensure_connected

    monitor_task = asyncio.create_task(provisioning.monitor())
    await asyncio.wait_for(triggered.wait(), timeout=1.0)
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    assert ensure_connected_calls == 1


async def test_monitor_does_not_trigger_when_connected():
    nm_client = FakeNmClient(connected_sequence=[True])
    face_display = FakeFaceDisplay()
    provisioning = WifiProvisioning(
        nm_client, face_display, "Haro-Setup", "haro1234",
        server_runner=FakeServerRunner(),
        check_interval_s=0.01, unhealthy_threshold=3,
    )
    ensure_connected_calls = 0

    async def fake_ensure_connected() -> None:
        nonlocal ensure_connected_calls
        ensure_connected_calls += 1

    provisioning.ensure_connected = fake_ensure_connected

    monitor_task = asyncio.create_task(provisioning.monitor())
    await asyncio.sleep(0.1)
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

    assert ensure_connected_calls == 0
