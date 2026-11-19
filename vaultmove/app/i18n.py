"""Translations: every user-visible string goes through tr() with one context.

At runtime we load app/i18n/vaultmove_<lang>.qm (compiled in CI with
pyside6-lrelease). When running from source without the .qm, the .ts XML is
parsed directly so translations still work without any build step.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator

CONTEXT = "VaultMove"
I18N_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")
LANGUAGES = {"en": "English", "fr": "Français"}


def tr(text: str) -> str:
    return QCoreApplication.translate(CONTEXT, text)


def N_(text: str) -> str:
    """Marks a string for extraction; translated later with tr(variable)."""
    return text


class TsTranslator(QTranslator):
    """Fallback translator that reads a Qt Linguist .ts file directly."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._map: dict[str, str] = {}
        root = ET.parse(path).getroot()
        for ctx in root.iter("context"):
            for msg in ctx.iter("message"):
                src = msg.findtext("source") or ""
                t = msg.find("translation")
                if t is not None and t.text and t.get("type") not in ("unfinished", "obsolete"):
                    self._map[src] = t.text

    def translate(self, context, source_text, disambiguation=None, n=-1):  # noqa: N802
        if context == CONTEXT:
            return self._map.get(source_text, "")
        return ""

    def isEmpty(self) -> bool:  # noqa: N802
        return not self._map


def pick_language(setting: str) -> str:
    if setting in LANGUAGES:
        return setting
    name = QLocale.system().name().split("_")[0].lower()
    return name if name in LANGUAGES else "en"


def _install_qt_base(app, lang: str):
    """Qt's own strings (standard buttons like Cancel/Yes/No) in the same language."""
    from PySide6.QtCore import QLibraryInfo
    dirs = []
    try:
        dirs.append(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    except Exception:
        pass
    try:
        import PySide6
        dirs.append(os.path.join(os.path.dirname(PySide6.__file__), "translations"))
    except Exception:
        pass
    for d in dirs:
        t = QTranslator(app)
        if d and t.load(f"qtbase_{lang}", d):
            app.installTranslator(t)
            return t
    return None


def install(app, setting: str = "auto"):
    lang = pick_language(setting)
    if lang == "en":
        return None
    _install_qt_base(app, lang)
    qm = os.path.join(I18N_DIR, f"vaultmove_{lang}.qm")
    ts = os.path.join(I18N_DIR, f"vaultmove_{lang}.ts")
    tr_obj = QTranslator(app)
    if os.path.exists(qm) and tr_obj.load(qm):
        app.installTranslator(tr_obj)
        return tr_obj
    if os.path.exists(ts):
        t = TsTranslator(ts, app)
        app.installTranslator(t)
        return t
    return None
