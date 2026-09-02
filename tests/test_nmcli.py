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


ACTIVE_CONNECTIONS_KEY = ("-t", "-f", "NAME,TYPE", "connection", "show", "--active")


def test_is_connected_true_when_a_real_wifi_connection_is_active():
    runner = ScriptedRunner(outputs={ACTIVE_CONNECTIONS_KEY: "MyHomeWifi:802-11-wireless\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is True


def test_is_connected_false_when_only_the_hotspot_is_active():
    runner = ScriptedRunner(outputs={ACTIVE_CONNECTIONS_KEY: "haro-setup:802-11-wireless\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is False


def test_is_connected_false_when_nothing_is_active():
    runner = ScriptedRunner(outputs={ACTIVE_CONNECTIONS_KEY: ""})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is False


def test_is_connected_false_when_only_a_non_wifi_connection_is_active():
    runner = ScriptedRunner(outputs={ACTIVE_CONNECTIONS_KEY: "Wired connection 1:802-3-ethernet\n"})
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is False


def test_is_connected_true_when_hotspot_and_a_real_wifi_are_both_active():
    runner = ScriptedRunner(
        outputs={ACTIVE_CONNECTIONS_KEY: "haro-setup:802-11-wireless\nMyHomeWifi:802-11-wireless\n"}
    )
    client = NetworkManagerClient("wlan0", runner=runner)

    assert client.is_connected() is True


def test_is_connected_ignores_malformed_lines():
    runner = ScriptedRunner(outputs={ACTIVE_CONNECTIONS_KEY: "garbage\n\nMyHomeWifi:802-11-wireless\n"})
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


def test_stop_hotspot_calls_nmcli_connection_delete():
    runner = ScriptedRunner()
    client = NetworkManagerClient("wlan0", runner=runner)

    client.stop_hotspot()

    assert runner.calls == [["connection", "delete", "haro-setup"]]


def test_default_runner_raises_nmcli_error_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="", stderr="Error: nmcli failed\n")
    with patch("haro.nmcli.subprocess.run", return_value=fake_result) as mock_run:
        with pytest.raises(NmcliError, match="Error: nmcli failed"):
            _default_runner(["device", "wifi", "list"])

    mock_run.assert_called_once_with(
        ["nmcli", "device", "wifi", "list"], capture_output=True, text=True, check=False,
    )


def test_default_runner_fallback_message_redacts_the_password():
    # Empty stderr forces the fallback message, which is built from the args.
    fake_result = MagicMock(returncode=1, stdout="", stderr="")
    args = ["device", "wifi", "connect", "HomeWifi", "password", "sup3rs3cret"]

    with patch("haro.nmcli.subprocess.run", return_value=fake_result):
        with pytest.raises(NmcliError) as excinfo:
            _default_runner(args)

    message = str(excinfo.value)
    assert "sup3rs3cret" not in message
    assert "password ***" in message
    assert "HomeWifi" in message
    # The caller's list must not be mutated by the redaction.
    assert args[-1] == "sup3rs3cret"
