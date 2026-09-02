# Haro WiFi Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Haro connect itself to WiFi without a keyboard or monitor: if no known network is available at boot (or the connection is lost for a sustained period at runtime), the robot starts its own WiFi hotspot and serves a small setup web page where the owner picks a network and enters its password.

**Architecture:** A `WifiProvisioning` state machine wraps NetworkManager (via `nmcli`, the mechanism already named in the spec) behind an injectable command-runner boundary, and an `aiohttp`-based setup web app behind an injectable server-runner boundary — so the whole flow is unit-testable with fakes, no real network hardware or root privileges required. `main.py` calls `WifiProvisioning.ensure_connected()` once at startup before the existing Orchestrator starts, and runs a background `WifiProvisioning.monitor()` loop alongside `Orchestrator.run()` to catch a WiFi drop during normal operation and re-enter setup mode automatically. This plan builds on top of the already-merged core voice pipeline; it does not modify `orchestrator.py`.

**Tech Stack:** Python 3.11+, `asyncio`, `aiohttp` (new dependency — the setup web server), `nmcli`/NetworkManager (already the spec's chosen WiFi backend, invoked as a subprocess), `pytest` + `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-09-02-haro-robot-design.md` (see the "WifiProvisioning" component and the boot-sequence/error-handling sections)

## Global Constraints

- Python 3.11+ (matches the existing project floor).
- WiFi management goes through NetworkManager (`nmcli`), per the spec's explicit mention that provisioning "hands the connection to NetworkManager" — no `hostapd`/`dnsmasq` dependency; `nmcli device wifi hotspot` provides both the AP and DHCP.
- Every `nmcli` interaction is wrapped by an injectable command-runner so no test in this plan needs root privileges, a real WiFi radio, or a real NetworkManager installation.
- The setup web server binds to `0.0.0.0:8080` (configurable via `Config.setup_server_port`), a non-privileged port, so the existing systemd unit's `User=pi` does not need to become root.
- No captive-portal DNS auto-redirect in this plan (out of scope/YAGNI) — the owner browses to a documented address (the hotspot's IP, `192.168.4.1`, on port `8080`) to reach the setup page; this matches the spec's own fallback wording ("altrimenti vai su haro.local/192.168.4.1").
- Runtime re-provisioning after a WiFi drop (the spec's "disconnessione futura" requirement) is implemented as a periodic background task (`WifiProvisioning.monitor()`) run in `main.py` alongside `Orchestrator.run()` via `asyncio.gather` — `orchestrator.py` itself is not modified by this plan.
- Hardware-dependent wiring (`main.py`'s real NetworkManager/aiohttp-server usage, the systemd unit) has no pytest suite by design, verified manually on the Raspberry Pi, matching the pattern already established for `audio_input.py` in the core pipeline plan.
- `Config`, `Expression`/`FaceDisplay`, and `main.py` already exist from the core pipeline plan — this plan modifies them, it does not recreate them. Current relevant contents are reproduced in each task below so no task requires re-reading a file to know its starting state.

---

### Task 1: Config additions for WiFi provisioning

**Files:**
- Modify: `src/haro/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: six new `Config` fields — `hotspot_ssid: str`, `hotspot_password: str`, `setup_server_port: int`, `wifi_interface: str`, `wifi_check_interval_s: float`, `wifi_unhealthy_threshold: int` — consumed by `main.py` (Task 5) when constructing `NetworkManagerClient` and `WifiProvisioning`.

The current `src/haro/config.py` in full:

```python
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
        if not isinstance(overrides, dict):
            raise ValueError(f"config file must contain a JSON object, got {type(overrides).__name__}")
        valid_fields = {f.name for f in dataclasses.fields(Config)}
        unknown = set(overrides) - valid_fields
        if unknown:
            raise ValueError(
                f"unknown config key(s): {sorted(unknown)}; valid keys: {sorted(valid_fields)}"
            )
        return dataclasses.replace(Config(), **overrides)
```

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (the file already has `test_default_config_has_expected_values` and other tests — add this as a new test function, don't remove anything existing):

```python
def test_default_config_has_wifi_provisioning_defaults():
    config = Config.default()
    assert config.hotspot_ssid == "Haro-Setup"
    assert config.hotspot_password == "haro1234"
    assert config.setup_server_port == 8080
    assert config.wifi_interface == "wlan0"
    assert config.wifi_check_interval_s == 30.0
    assert config.wifi_unhealthy_threshold == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_config.py::test_default_config_has_wifi_provisioning_defaults -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'hotspot_ssid'`

- [ ] **Step 3: Add the new fields to `Config`**

In `src/haro/config.py`, add these six fields to the `Config` dataclass, after the existing `response_timeout_s: float = 15.0` line (order doesn't matter for a dataclass with all-defaulted fields, but keep them grouped together for readability):

```python
    hotspot_ssid: str = "Haro-Setup"
    hotspot_password: str = "haro1234"
    setup_server_port: int = 8080
    wifi_interface: str = "wlan0"
    wifi_check_interval_s: float = 30.0
    wifi_unhealthy_threshold: int = 3
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all `test_config.py` tests, including the new one)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -v`
Expected: PASS (all existing tests plus the new one)

- [ ] **Step 6: Commit**

```bash
git add src/haro/config.py tests/test_config.py
git commit -m "feat: add WiFi provisioning settings to Config"
```

---

### Task 2: NetworkManager client (`nmcli.py`)

**Files:**
- Create: `src/haro/nmcli.py`
- Test: `tests/test_nmcli.py`

**Interfaces:**
- Produces: `NmcliError` exception; `CommandRunner` type alias (`Callable[[list[str]], str]`); `NetworkManagerClient(interface: str, runner: CommandRunner = ...)` with `.is_connected() -> bool`, `.scan_networks() -> list[str]`, `.connect(ssid: str, password: str) -> None`, `.start_hotspot(ssid: str, password: str) -> None`, `.stop_hotspot() -> None`. Used by `wifi_provisioning.py` (Task 4) and wired to the real `nmcli` binary in `main.py` (Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nmcli.py
import pytest

from haro.nmcli import NetworkManagerClient, NmcliError


class ScriptedRunner:
    def __init__(self, outputs: dict[tuple, str] | None = None, raise_on: set[tuple] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._outputs = outputs or {}
        self._raise_on = raise_on or set()

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        key = tuple(args)
        if key in self._raise_on:
            raise NmcliError("boom")
        return self._outputs.get(key, "")


def test_is_connected_true_when_state_is_connected():
    runner = ScriptedRunner(outputs={("-t", "-g", "STATE", "general", "status"): "connected\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is True


def test_is_connected_false_when_state_is_not_connected():
    runner = ScriptedRunner(outputs={("-t", "-g", "STATE", "general", "status"): "disconnected\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is False


def test_scan_networks_dedupes_and_strips_blank_lines():
    key = ("-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes")
    runner = ScriptedRunner(outputs={key: "HomeWifi\nHomeWifi\n\nOffice\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.scan_networks() == ["HomeWifi", "Office"]


def test_connect_calls_nmcli_with_ssid_and_password():
    runner = ScriptedRunner()
    client = NetworkManagerClient("wlan0", runner=runner)

    client.connect("HomeWifi", "secret123")

    assert runner.calls == [["device", "wifi", "connect", "HomeWifi", "password", "secret123"]]


def test_connect_raises_nmcli_error_on_failure():
    args = ["device", "wifi", "connect", "HomeWifi", "password", "wrong"]
    runner = ScriptedRunner(raise_on={tuple(args)})
    client = NetworkManagerClient("wlan0", runner=runner)

    with pytest.raises(NmcliError):
        client.connect("HomeWifi", "wrong")


def test_start_hotspot_calls_nmcli_with_expected_args():
    runner = ScriptedRunner()
    client = NetworkManagerClient("wlan0", runner=runner)

    client.start_hotspot("Haro-Setup", "haro1234")

    assert runner.calls == [
        [
            "device", "wifi", "hotspot",
            "ifname", "wlan0",
            "con-name", "haro-setup",
            "ssid", "Haro-Setup",
            "password", "haro1234",
        ]
    ]


def test_stop_hotspot_calls_nmcli_connection_down():
    runner = ScriptedRunner()
    client = NetworkManagerClient("wlan0", runner=runner)

    client.stop_hotspot()

    assert runner.calls == [["connection", "down", "haro-setup"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_nmcli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.nmcli'`

- [ ] **Step 3: Implement `nmcli.py`**

```python
# src/haro/nmcli.py
import subprocess
from typing import Callable


class NmcliError(Exception):
    pass


CommandRunner = Callable[[list[str]], str]


def _default_runner(args: list[str]) -> str:
    result = subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise NmcliError(result.stderr.strip() or f"nmcli {' '.join(args)} failed")
    return result.stdout


class NetworkManagerClient:
    def __init__(self, interface: str, runner: CommandRunner = _default_runner) -> None:
        self._interface = interface
        self._runner = runner

    def is_connected(self) -> bool:
        output = self._runner(["-t", "-g", "STATE", "general", "status"])
        return output.strip() == "connected"

    def scan_networks(self) -> list[str]:
        output = self._runner(
            ["-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"]
        )
        seen: set[str] = set()
        unique: list[str] = []
        for line in output.splitlines():
            ssid = line.strip()
            if ssid and ssid not in seen:
                seen.add(ssid)
                unique.append(ssid)
        return unique

    def connect(self, ssid: str, password: str) -> None:
        self._runner(["device", "wifi", "connect", ssid, "password", password])

    def start_hotspot(self, ssid: str, password: str, con_name: str = "haro-setup") -> None:
        self._runner(
            [
                "device", "wifi", "hotspot",
                "ifname", self._interface,
                "con-name", con_name,
                "ssid", ssid,
                "password", password,
            ]
        )

    def stop_hotspot(self, con_name: str = "haro-setup") -> None:
        self._runner(["connection", "down", con_name])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_nmcli.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/haro/nmcli.py tests/test_nmcli.py
git commit -m "feat: add NetworkManagerClient wrapping nmcli"
```

---

### Task 3: Setup web app (`setup_server.py`)

**Files:**
- Create: `src/haro/setup_server.py`
- Test: `tests/test_setup_server.py`
- Modify: `pyproject.toml` (add `aiohttp` dependency)

**Interfaces:**
- Consumes: `aiohttp.web`.
- Produces: `ConnectCallback` type alias (`Callable[[str, str], Awaitable[bool]]`); `create_setup_app(networks: list[str], on_submit: ConnectCallback) -> aiohttp.web.Application` — `GET /` renders a form listing `networks`, `POST /connect` reads `ssid`/`password` form fields, calls `on_submit(ssid, password)`, and returns a 200 response on success or a 400 response on failure (missing SSID, or `on_submit` returning `False`). Used by `wifi_provisioning.py` (Task 4).

- [ ] **Step 1: Add the `aiohttp` dependency**

In `pyproject.toml`, add `"aiohttp>=3.9.0",` to the `dependencies` list (alongside the existing `numpy`, `sounddevice`, etc. entries).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_setup_server.py
from aiohttp.test_utils import TestClient, TestServer

from haro.setup_server import create_setup_app


async def test_index_lists_networks():
    app = create_setup_app(["HomeWifi", "Office"], on_submit=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        text = await resp.text()

    assert resp.status == 200
    assert "HomeWifi" in text
    assert "Office" in text


async def test_connect_calls_on_submit_and_reports_success():
    calls: list[tuple[str, str]] = []

    async def on_submit(ssid: str, password: str) -> bool:
        calls.append((ssid, password))
        return True

    app = create_setup_app(["HomeWifi"], on_submit=on_submit)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"ssid": "HomeWifi", "password": "secret"})

    assert resp.status == 200
    assert calls == [("HomeWifi", "secret")]


async def test_connect_reports_failure_from_on_submit():
    async def on_submit(ssid: str, password: str) -> bool:
        return False

    app = create_setup_app(["HomeWifi"], on_submit=on_submit)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"ssid": "HomeWifi", "password": "wrong"})

    assert resp.status == 400


async def test_connect_without_ssid_returns_400():
    app = create_setup_app([], on_submit=None)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/connect", data={"password": "secret"})

    assert resp.status == 400
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_setup_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.setup_server'`

- [ ] **Step 4: Install the new dependency and implement `setup_server.py`**

Run: `pip install -e ".[dev]"` (picks up the new `aiohttp` dependency added in Step 1)

```python
# src/haro/setup_server.py
from typing import Awaitable, Callable

from aiohttp import web

ConnectCallback = Callable[[str, str], Awaitable[bool]]


def create_setup_app(networks: list[str], on_submit: ConnectCallback) -> web.Application:
    app = web.Application()

    async def index(request: web.Request) -> web.Response:
        options = "".join(
            f'<label><input type="radio" name="ssid" value="{ssid}" required> {ssid}</label><br>'
            for ssid in networks
        )
        html = f"""
        <html><body>
        <h1>Haro setup</h1>
        <form method="post" action="/connect">
        {options}
        <label>Password: <input type="password" name="password"></label><br>
        <button type="submit">Connect</button>
        </form>
        </body></html>
        """
        return web.Response(text=html, content_type="text/html")

    async def connect(request: web.Request) -> web.Response:
        data = await request.post()
        ssid = str(data.get("ssid", ""))
        password = str(data.get("password", ""))
        if not ssid:
            return web.Response(text="Missing network selection", status=400)
        success = await on_submit(ssid, password)
        if success:
            return web.Response(text="Connected! Haro is resuming normal operation.")
        return web.Response(text="Could not connect. Go back and try again.", status=400)

    app.router.add_get("/", index)
    app.router.add_post("/connect", connect)
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_setup_server.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/haro/setup_server.py tests/test_setup_server.py
git commit -m "feat: add aiohttp setup web app for WiFi provisioning"
```

---

### Task 4: WifiProvisioning orchestrator

**Files:**
- Create: `src/haro/wifi_provisioning.py`
- Test: `tests/test_wifi_provisioning.py`

**Interfaces:**
- Consumes: `haro.face_display.Expression` (Task-independent, already exists); `haro.nmcli.NetworkManagerClient`'s public interface (Task 2, via a duck-typed Protocol, not a direct import of the concrete class); `haro.setup_server.create_setup_app` (Task 3).
- Produces: `WifiProvisioning(nm_client, face_display, hotspot_ssid: str, hotspot_password: str, setup_server_port: int = 8080, server_runner=None, check_interval_s: float = 30.0, unhealthy_threshold: int = 3)` with `async def ensure_connected(self) -> None` and `async def monitor(self) -> None`. Used by `main.py` (Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wifi_provisioning.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wifi_provisioning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'haro.wifi_provisioning'`

- [ ] **Step 3: Implement `wifi_provisioning.py`**

```python
# src/haro/wifi_provisioning.py
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
        if self._nm_client.is_connected():
            return

        logger.info("no known WiFi connection, entering setup mode")
        self._face_display.show(Expression.SETUP)
        networks = self._nm_client.scan_networks()
        self._nm_client.start_hotspot(self._hotspot_ssid, self._hotspot_password)

        stop_event = asyncio.Event()

        async def on_submit(ssid: str, password: str) -> bool:
            try:
                self._nm_client.connect(ssid, password)
            except Exception as exc:
                logger.warning("failed to connect to %s: %s", ssid, exc)
                return False
            if self._nm_client.is_connected():
                stop_event.set()
                return True
            return False

        app = create_setup_app(networks, on_submit)
        await self._server_runner.serve_until(app, self._setup_server_port, stop_event)

        self._nm_client.stop_hotspot()
        logger.info("WiFi setup complete, resuming normal operation")

    async def monitor(self) -> None:
        consecutive_failures = 0
        while True:
            await asyncio.sleep(self._check_interval_s)
            if self._nm_client.is_connected():
                consecutive_failures = 0
                continue
            consecutive_failures += 1
            logger.warning(
                "WiFi check failed (%d/%d)", consecutive_failures, self._unhealthy_threshold
            )
            if consecutive_failures >= self._unhealthy_threshold:
                consecutive_failures = 0
                await self.ensure_connected()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wifi_provisioning.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add src/haro/wifi_provisioning.py tests/test_wifi_provisioning.py
git commit -m "feat: add WifiProvisioning state machine for hotspot setup and monitoring"
```

---

### Task 5: Wire WiFi provisioning into `main.py`

**Files:**
- Modify: `src/haro/main.py`

**Interfaces:**
- Consumes: `Config` (Task 1's new fields), `haro.nmcli.NetworkManagerClient` (Task 2), `haro.wifi_provisioning.WifiProvisioning` (Task 4).
- Produces: `build_wifi_provisioning(config: Config, face_display: FaceDisplay) -> WifiProvisioning`. Wires real hardware (the real `nmcli` binary via `NetworkManagerClient`'s default runner, the real `aiohttp` server via `AiohttpServerRunner`) — verified manually on the Raspberry Pi, not via pytest, matching the rest of `main.py`.

The current `src/haro/main.py` in full (this task modifies it):

```python
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
from .orchestrator import Orchestrator
from .server_client import ServerClient
from .vad import SilenceDetector
from .wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


def build_orchestrator(
    config: Config,
) -> tuple[Orchestrator, AudioInput, AudioOutput, FaceDisplay, ServerClient]:
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
    return orchestrator, audio_input, audio_output, face_display, server_client


async def run(config_path: str | None) -> None:
    config = Config.from_file(config_path) if config_path else Config.default()
    logger.info("loaded config from %s", config_path or "defaults")
    orchestrator, audio_input, audio_output, face_display, server_client = build_orchestrator(config)
    try:
        audio_input.start()
    except Exception:
        logger.exception("failed to start audio input")
        face_display.show(Expression.ERROR)
        raise
    try:
        await orchestrator.run()
    except Exception:
        logger.exception("orchestrator crashed")
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
```

- [ ] **Step 1: Add the new imports**

At the top of `src/haro/main.py`, add these two imports alongside the existing ones (keep the existing imports exactly as they are, just add these two — one new stdlib-adjacent import isn't needed since `asyncio` is already imported):

```python
from .nmcli import NetworkManagerClient
from .wifi_provisioning import WifiProvisioning
```

- [ ] **Step 2: Add `build_wifi_provisioning`**

Add this function after `build_orchestrator` and before `run`:

```python
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
```

- [ ] **Step 3: Gate startup on WiFi connectivity and run the monitor loop alongside the orchestrator**

Replace the body of `run` with:

```python
async def run(config_path: str | None) -> None:
    config = Config.from_file(config_path) if config_path else Config.default()
    logger.info("loaded config from %s", config_path or "defaults")
    orchestrator, audio_input, audio_output, face_display, server_client = build_orchestrator(config)

    wifi_provisioning = build_wifi_provisioning(config, face_display)
    await wifi_provisioning.ensure_connected()

    try:
        audio_input.start()
    except Exception:
        logger.exception("failed to start audio input")
        face_display.show(Expression.ERROR)
        raise
    try:
        await asyncio.gather(orchestrator.run(), wifi_provisioning.monitor())
    except Exception:
        logger.exception("orchestrator crashed")
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
```

`build_orchestrator` and `main()` are unchanged — only `run`'s body changes and `build_wifi_provisioning` is added.

- [ ] **Step 4: Verify the module imports cleanly**

Run: `python -c "from haro.main import build_wifi_provisioning, run; print('ok')"`
Expected: prints `ok`. This only checks the module and its imports load correctly; the real `ensure_connected()`/`monitor()` flow against a real WiFi radio and NetworkManager installation is verified manually on the Raspberry Pi (Step 5).

- [ ] **Step 5: Manually verify on the Raspberry Pi**

On the Pi, with no known WiFi network configured (or with WiFi disabled to simulate that state): run `python -m haro.main config.json` and confirm the OLED shows the `setup` expression, a `Haro-Setup` WiFi network becomes visible from another device, and connecting to it and browsing to `http://192.168.4.1:8080` shows the setup page listing nearby networks. Submitting a valid network + password should connect the Pi and the process should proceed into normal operation (as verified in the core pipeline plan's own Task 13 manual check). This is a hardware verification step, not an automated test — no physical WiFi radio exists in this dev environment.

- [ ] **Step 6: Commit**

```bash
git add src/haro/main.py
git commit -m "feat: gate startup on WiFi connectivity and monitor for drops"
```

---

### Task 6: systemd unit — don't wait on a network that may never come up

**Files:**
- Modify: `systemd/haro.service`

**Interfaces:**
- Standalone systemd unit file change; not consumed by any Python module.

**Why this task exists:** The current unit has `After=network-online.target` / `Wants=network-online.target`, which was correct when the robot assumed WiFi was already configured. Now that the whole point of this plan is to handle "no WiFi configured yet," waiting on `network-online.target` before the service even starts could block the very AP-mode fallback that's supposed to handle that case on a factory-fresh Pi. The service only needs NetworkManager itself to be running (so `nmcli` commands work) — it does not need an actual internet connection first, since establishing one is exactly what this service now does.

The current `systemd/haro.service` in full:

```ini
[Unit]
Description=Haro personal AI desk robot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
User=pi
WorkingDirectory=/home/pi/haro
ExecStart=/home/pi/haro/.venv/bin/python -m haro.main /home/pi/haro/config.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 1: Change the `[Unit]` dependency**

Replace:

```ini
[Unit]
Description=Haro personal AI desk robot
After=network-online.target
Wants=network-online.target
```

with:

```ini
[Unit]
Description=Haro personal AI desk robot
After=NetworkManager.service
Wants=NetworkManager.service
```

Leave the `[Service]` and `[Install]` sections exactly as they are.

- [ ] **Step 2: Manually verify on the Raspberry Pi**

`sudo systemctl daemon-reload && sudo systemctl restart haro.service`, then on a factory-fresh Pi with no WiFi configured, confirm the service starts (does not wait indefinitely) and reaches the setup-mode flow from Task 5's manual check. This is a hardware verification step, not an automated test.

- [ ] **Step 3: Commit**

```bash
git add systemd/haro.service
git commit -m "chore: depend on NetworkManager.service instead of network-online.target"
```
