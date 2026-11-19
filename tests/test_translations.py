"""Every UI string is translated to French, and the translator actually loads."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_every_string_has_a_french_translation():
    from make_ts import FR
    from i18n_extract import extract
    missing = [s for s in extract() if s not in FR]
    assert not missing, f"untranslated strings: {missing}"


def test_placeholders_preserved():
    from make_ts import FR
    import re
    for src, fr in FR.items():
        assert sorted(re.findall(r"%\d", src)) == sorted(re.findall(r"%\d", fr)), src


def test_ts_file_is_current_and_loads(qapp):
    pytest.importorskip("PySide6")
    from vaultmove.app.i18n import TsTranslator, tr
    p = os.path.join(ROOT, "vaultmove", "app", "i18n", "vaultmove_fr.ts")
    t = TsTranslator(p)
    from make_ts import FR
    assert not t.isEmpty()
    qapp.installTranslator(t)
    try:
        assert tr("Back Up Now") == "Sauvegarder maintenant"
    finally:
        qapp.removeTranslator(t)
    from i18n_extract import extract
    for s in extract():
        assert t.translate("VaultMove", s) == FR[s], f".ts is stale for {s!r}: run python tools/make_ts.py"
