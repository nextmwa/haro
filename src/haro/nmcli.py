import subprocess
from typing import Callable


class NmcliError(Exception):
    pass


CommandRunner = Callable[[list[str]], str]

DEFAULT_HOTSPOT_CON_NAME = "haro-setup"

WIFI_CONNECTION_TYPE = "802-11-wireless"


def _redact_password(args: list[str]) -> list[str]:
    """Replace any token following a literal "password" argument, so WiFi
    secrets never reach log output via an error message."""
    redacted = list(args)
    for i, token in enumerate(redacted):
        if token == "password" and i + 1 < len(redacted):
            redacted[i + 1] = "***"
    return redacted


def _default_runner(args: list[str]) -> str:
    result = subprocess.run(
        ["nmcli", *args], capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise NmcliError(
            result.stderr.strip() or f"nmcli {' '.join(_redact_password(args))} failed"
        )
    return result.stdout


class NetworkManagerClient:
    def __init__(self, interface: str, runner: CommandRunner = _default_runner) -> None:
        self._interface = interface
        self._runner = runner

    def is_connected(self) -> bool:
        """True only when a real WiFi client connection is active.

        NetworkManager's general status also reports "connected" while our own
        setup hotspot is up, which would mask a total lack of connectivity, so
        the hotspot profile is explicitly excluded here.
        """
        output = self._runner(["-t", "-f", "NAME,TYPE", "connection", "show", "--active"])
        for line in output.splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            name, conn_type = parts[0], parts[1]
            if conn_type == WIFI_CONNECTION_TYPE and name != DEFAULT_HOTSPOT_CON_NAME:
                return True
        return False

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

    def start_hotspot(
        self, ssid: str, password: str, con_name: str = DEFAULT_HOTSPOT_CON_NAME
    ) -> None:
        self._runner(
            [
                "device", "wifi", "hotspot",
                "ifname", self._interface,
                "con-name", con_name,
                "ssid", ssid,
                "password", password,
            ]
        )

    def stop_hotspot(self, con_name: str = DEFAULT_HOTSPOT_CON_NAME) -> None:
        # Delete rather than merely deactivate: a profile left defined stays
        # eligible for NetworkManager autoconnect and could silently come back.
        self._runner(["connection", "delete", con_name])
