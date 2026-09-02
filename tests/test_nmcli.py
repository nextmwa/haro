import pytest
from unittest.mock import patch, MagicMock

from haro.nmcli import NetworkManagerClient, NmcliError, _default_runner


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


def test_is_connected_true_when_state_is_connected_with_variant():
    runner = ScriptedRunner(outputs={("-t", "-g", "STATE", "general", "status"): "connected (site)\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is True


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


def test_default_runner_raises_nmcli_error_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="", stderr="Error: nmcli failed\n")
    with patch("haro.nmcli.subprocess.run", return_value=fake_result) as mock_run:
        with pytest.raises(NmcliError, match="Error: nmcli failed"):
            _default_runner(["device", "wifi", "list"])

    mock_run.assert_called_once_with(
        ["nmcli", "device", "wifi", "list"], capture_output=True, text=True, check=False,
    )
