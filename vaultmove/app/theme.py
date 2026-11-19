"""Design tokens, one QSS template, and light/dark switching that follows Windows.

Widgets never hard-code colours: they use objectNames that the template
styles (Card, Primary, Segment, Title, Subtle...) or read theme.tokens().
"""

from __future__ import annotations

from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f5f5f7", "card": "#ffffff", "card_border": "#e8e8ed", "text": "#1d1d1f", "subtext": "#6e6e73",
    "border": "#d2d2d7", "field": "#ffffff", "button": "#ffffff", "hover": "#f0f0f5", "pressed": "#e5e5ea",
    "accent": "#0a84ff", "accent_hover": "#3395ff", "accent_pressed": "#0060df", "accent_disabled": "#a8cfff",
    "selection": "#d6e8ff", "segment_bg": "#e3e3e8", "track": "#e5e5ea", "scroll": "#c7c7cc",
    "disabled": "#aeaeb2", "danger": "#ff3b30", "success": "#30b158", "warning": "#ff9500",
    "badge_local_bg": "#e3f5e8", "badge_local_fg": "#1e7b3a", "badge_vault_bg": "#e5f0ff",
    "badge_vault_fg": "#0060df", "badge_old_bg": "#efeff4", "badge_old_fg": "#6e6e73",
}

DARK = {
    "bg": "#1c1c1e", "card": "#2c2c2e", "card_border": "#3a3a3c", "text": "#f5f5f7", "subtext": "#98989d",
    "border": "#48484a", "field": "#1c1c1e", "button": "#3a3a3c", "hover": "#3f3f42", "pressed": "#4a4a4d",
    "accent": "#0a84ff", "accent_hover": "#409cff", "accent_pressed": "#0068d6", "accent_disabled": "#1d4f86",
    "selection": "#0b3e74", "segment_bg": "#1c1c1e", "track": "#3a3a3c", "scroll": "#545458",
    "disabled": "#636366", "danger": "#ff453a", "success": "#32d74b", "warning": "#ff9f0a",
    "badge_local_bg": "#16361f", "badge_local_fg": "#5fe07c", "badge_vault_bg": "#0c2f57",
    "badge_vault_fg": "#6cb4ff", "badge_old_bg": "#3a3a3c", "badge_old_fg": "#a1a1a6",
}

QSS = Template("""
QWidget { color: $text; font-family: "$font"; }
QMainWindow, QDialog, QWidget#Page, QScrollArea, QScrollArea > QWidget > QWidget#Page { background: $bg; }
QWidget#Transparent { background: transparent; }
QFrame#Card { background: $card; border: 1px solid $card_border; border-radius: 14px; }
QLabel { background: transparent; }
QLabel#Title { font-size: 19pt; font-weight: 600; }
QLabel#H2 { font-size: 12pt; font-weight: 600; }
QLabel#AppName { font-size: 12pt; font-weight: 600; }
QLabel#Subtle { color: $subtext; }
QLabel#Danger { color: $danger; }
QLabel#Warning { color: $warning; }
QLabel#Stat { font-size: 15pt; font-weight: 600; }

QPushButton { background: $button; border: 1px solid $border; border-radius: 8px; padding: 6px 14px;
              min-height: 18px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:focus { border: 1px solid $accent; }
QPushButton:disabled { color: $disabled; }
QPushButton#Primary { background: $accent; color: #ffffff; border: 1px solid $accent; font-weight: 600;
                      padding: 8px 22px; border-radius: 10px; }
QPushButton#Primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#Primary:pressed { background: $accent_pressed; }
QPushButton#Primary:focus { border: 2px solid $text; }
QPushButton#Primary:disabled { background: $accent_disabled; border-color: $accent_disabled; color: #ffffff; }
QPushButton#Link { background: transparent; border: none; color: $accent; padding: 2px 4px; }
QPushButton#Link:hover { text-decoration: underline; }
QPushButton#Link:focus { border: 1px solid $accent; }
QWidget#SegmentBar { background: $segment_bg; border-radius: 10px; }
QPushButton#Segment { background: transparent; border: 1px solid transparent; border-radius: 8px;
                      padding: 5px 18px; color: $subtext; }
QPushButton#Segment:hover { color: $text; }
QPushButton#Segment:checked { background: $card; color: $text; font-weight: 600; border: 1px solid $card_border; }
QPushButton#Segment:focus { border: 1px dashed $accent; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 4px 8px; }
QToolButton:hover { background: $hover; }
QToolButton:focus { border: 1px solid $accent; }
QToolButton:disabled { color: $disabled; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QDateTimeEdit {
    background: $field; border: 1px solid $border; border-radius: 8px; padding: 5px 8px;
    selection-background-color: $accent; selection-color: #ffffff; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid $accent; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $border; selection-background-color: $accent;
                              selection-color: #ffffff; outline: 0; }
QPlainTextEdit#Log { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; color: $subtext; }

QListWidget, QTreeView, QTableView { background: transparent; border: none; outline: 0; }
QListWidget::item, QTreeView::item { padding: 6px 4px; border: none; }
QListWidget::item:selected, QTreeView::item:selected { background: $selection; color: $text; border-radius: 6px; }
QListWidget::item:hover, QTreeView::item:hover { background: $hover; border-radius: 6px; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; color: $subtext; border: none; border-bottom: 1px solid $card_border;
                       padding: 6px 4px; font-weight: 600; }

QProgressBar { background: $track; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QProgressBar#Thin { max-height: 6px; min-height: 6px; border-radius: 3px; }
QProgressBar#Thin::chunk { border-radius: 3px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0;
    background: transparent; }

QMenu { background: $card; border: 1px solid $border; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: $accent; color: #ffffff; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $card_border; margin: 4px 8px; }
QToolTip { background: $card; color: $text; border: 1px solid $border; padding: 4px 6px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListView::indicator, QTreeView::indicator {
    width: 16px; height: 16px; border: 1px solid $border; border-radius: 5px; background: $field; }
QCheckBox::indicator:hover, QListView::indicator:hover { border-color: $accent; }
QCheckBox::indicator:focus { border: 1px solid $accent; }
QCheckBox::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked {
    background: $accent; border-color: $accent; image: url($img_check); }
QCheckBox::indicator:disabled { background: $track; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url($img_down); width: 12px; height: 12px; }
QSpinBox { padding-right: 22px; min-width: 64px; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none;
                      background: transparent; margin-top: 2px; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none;
                        background: transparent; margin-bottom: 2px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: $hover; border-radius: 4px; }
QSpinBox::up-arrow { image: url($img_up); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url($img_down); width: 10px; height: 10px; }
""")

_asset_dir = None


def _assets(dark: bool) -> dict:
    """Tiny painted images (check mark, chevrons) referenced by the QSS."""
    global _asset_dir
    import os
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
    if _asset_dir is None:
        _asset_dir = tempfile.mkdtemp(prefix="vaultmove-ui-")
    tag = "d" if dark else "l"
    sub = DARK["subtext"] if dark else LIGHT["subtext"]
    out = {}

    def draw(name, pts, colour, width):
        path = os.path.join(_asset_dir, f"{name}_{tag}.png")
        if not os.path.exists(path):
            img = QImage(48, 48, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(colour), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pp = QPainterPath(QPointF(*pts[0]))
            for pt in pts[1:]:
                pp.lineTo(QPointF(*pt))
            p.drawPath(pp)
            p.end()
            img.save(path)
        out["img_" + name] = path.replace("\\", "/")

    draw("check", [(12, 25), (20, 33), (36, 15)], "#ffffff", 5.5)
    draw("down", [(12, 18), (24, 30), (36, 18)], sub, 5)
    draw("up", [(12, 30), (24, 18), (36, 30)], sub, 5)
    return out

_current = dict(LIGHT)
_dark = False


def tokens() -> dict:
    return _current


def is_dark() -> bool:
    return _dark


def color(name: str) -> QColor:
    return QColor(_current[name])


def system_is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return app.palette().color(QPalette.Window).lightness() < 128


def ui_font_family() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI"):
        if f in fams:
            return f
    return QApplication.font().family()


def apply(app: QApplication, dark: bool | None = None):
    global _current, _dark
    if dark is None:
        dark = system_is_dark(app)
    _dark = dark
    _current = dict(DARK if dark else LIGHT)
    app.setStyle("Fusion")
    fam = ui_font_family()
    f = QFont(fam)
    f.setPointSizeF(10)
    app.setFont(f)
    pal = QPalette()
    t = _current
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["field"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["hover"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["button"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(t["card"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["subtext"]))
    pal.setColor(QPalette.Link, QColor(t["accent"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["disabled"]))
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(font=fam, **t, **_assets(dark)))


class ThemeManager(QObject):
    """Re-applies the theme when Windows switches light/dark."""

    changed = Signal(bool)

    def __init__(self, app: QApplication, forced: bool | None = None):
        super().__init__(app)
        self.app = app
        self.forced = forced
        apply(app, forced)
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_change)
        except AttributeError:
            pass

    def _on_change(self, *_):
        if self.forced is not None:
            return
        apply(self.app, None)
        self.changed.emit(_dark)

    def set_forced(self, dark: bool | None):
        self.forced = dark
        apply(self.app, dark)
        self.changed.emit(_dark)
