"""Background work on QThreadPool. The UI thread never blocks on I/O.

run_async(fn, on_done, on_error) runs fn() on the pool; results come back to
the UI thread through queued signals. Tasks are kept referenced until they
report, so their signal objects are not garbage-collected early.
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_live: set = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(dict)


class Task(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.setAutoDelete(True)

    def run(self):
        try:
            r = self.fn(*self.args, **self.kwargs)
        except Exception as e:  # reported to the UI, never swallowed
            self.signals.failed.emit(f"{e.__class__.__name__}: {e}\n{traceback.format_exc(limit=6)}")
        else:
            self.signals.done.emit(r)


def pool() -> QThreadPool:
    p = QThreadPool.globalInstance()
    if p.maxThreadCount() < 3:
        p.setMaxThreadCount(3)
    return p


def run_async(fn, on_done=None, on_error=None, on_progress=None, *args, **kwargs) -> Task:
    t = Task(fn, *args, **kwargs)
    _live.add(t.signals)

    def _finish(*_):
        _live.discard(t.signals)

    if on_done:
        t.signals.done.connect(on_done)
    if on_error:
        t.signals.failed.connect(on_error)
    if on_progress:
        t.signals.progress.connect(on_progress)
    t.signals.done.connect(_finish)
    t.signals.failed.connect(_finish)
    pool().start(t)
    return t
