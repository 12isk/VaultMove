"""'Start with Windows': a per-user HKCU Run entry launching with --background."""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "VaultMove"


def launch_command(portable: bool = False) -> str:
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}" --background'
    else:
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(pyw):
            exe = pyw
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "run_vaultmove.py")
        cmd = f'"{exe}" "{script}" --background'
    if portable and "--portable" not in cmd:
        cmd += " --portable"
    return cmd


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False


def set_enabled(on: bool, portable: bool = False) -> None:
    if os.name != "nt":
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, launch_command(portable))
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except FileNotFoundError:
                pass
