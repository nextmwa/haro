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
        return output.strip().startswith("connected")

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
