"""Create / delete VSS snapshots through the built-in WMI class (needs admin)."""

from __future__ import annotations

import os
import re
import subprocess

VOLUME_RX = re.compile(r"^[A-Za-z]:\\$")
GUID_RX = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
DEVICE_RX = re.compile(r"^\\\\\?\\GLOBALROOT\\Device\\HarddiskVolumeShadowCopy\d+$")


def _ps(script: str, timeout: int = 300) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", script], capture_output=True, timeout=timeout, creationflags=flags)
    return (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")


class WmiShadowProvider:
    def create(self, volume: str) -> tuple[str, str]:
        if not VOLUME_RX.match(volume):
            raise ValueError("bad volume")
        script = (
            "$ErrorActionPreference='Stop';"
            f"$r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create "
            f"-Arguments @{{Volume='{volume}'; Context='ClientAccessible'}};"
            "if ($r.ReturnValue -ne 0) { Write-Output ('ERR ' + $r.ReturnValue); exit 2 };"
            "$s = Get-CimInstance -ClassName Win32_ShadowCopy -Filter (\"ID='\" + $r.ShadowID + \"'\");"
            "Write-Output ('OK ' + $s.ID + ' ' + $s.DeviceObject)"
        )
        out = _ps(script)
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) == 3 and parts[0] == "OK" and GUID_RX.match(parts[1]) and DEVICE_RX.match(parts[2]):
                return parts[1], parts[2]
        raise RuntimeError("could not create a shadow copy: " + out.strip()[:300])

    def delete(self, sid: str) -> None:
        if not GUID_RX.match(sid):
            return
        _ps(f"Get-CimInstance -ClassName Win32_ShadowCopy -Filter \"ID='{sid}'\" | Remove-CimInstance", 120)


class FakeProvider:
    """Test double: 'snapshot' = the live volume (protocol and path checks only)."""

    def create(self, volume: str) -> tuple[str, str]:
        if not VOLUME_RX.match(volume):
            raise ValueError("bad volume")
        return "{00000000-0000-0000-0000-000000000000}", "\\\\?\\" + volume.rstrip("\\")

    def delete(self, sid: str) -> None:
        pass
