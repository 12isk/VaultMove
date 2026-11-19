"""Drive arrival / power events.

A hidden native top-level QWidget receives the WM_DEVICECHANGE and
WM_POWERBROADCAST broadcasts (message-only windows do not get broadcasts).
A slow poll of GetLogicalDrives() is the fallback, so a missed message only
delays detection by a few seconds. Signals are debounced.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QWidget

from ..core import winapi

WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMPOWERSTATUSCHANGE = 0x000A


class DeviceWatcher(QWidget):
    volumesChanged = Signal()
    resumed = Signal()
    powerChanged = Signal()

    def __init__(self, poll_ms: int = 5000):
        super().__init__(None)
        self.setWindowTitle("VaultMove device watcher")
        self._mask = winapi.logical_drives_mask()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(2500)  # let Windows finish mounting the volume
        self._debounce.timeout.connect(self.volumesChanged.emit)
        self._poll = QTimer(self)
        self._poll.setInterval(poll_ms)
        self._poll.timeout.connect(self._check_mask)
        self._poll.start()
        if winapi.IS_WIN:
            self.winId()  # create the native (hidden) window so it receives broadcasts

    def _check_mask(self):
        m = winapi.logical_drives_mask()
        if m != self._mask:
            self._mask = m
            self._debounce.start()

    def nativeEvent(self, event_type, message):  # noqa: N802
        try:
            if winapi.IS_WIN and event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_DEVICECHANGE and msg.wParam in (DBT_DEVICEARRIVAL, DBT_DEVICEREMOVECOMPLETE):
                    self._mask = winapi.logical_drives_mask()
                    self._debounce.start()
                elif msg.message == WM_POWERBROADCAST:
                    if msg.wParam in (PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC):
                        self.resumed.emit()
                    elif msg.wParam == PBT_APMPOWERSTATUSCHANGE:
                        self.powerChanged.emit()
        except Exception:
            pass
        return False, 0
