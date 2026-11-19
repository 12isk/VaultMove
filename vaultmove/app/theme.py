"""Design tokens, one QSS template, light/dark switching that follows Windows.

Values follow the macOS design skill (~/.claude/skills/macos-design): hierarchy
through background levels (not borders), hairline low-opacity edges, the Apple
type scale (13 px body), 8 px grid, radii 8 (cards) / 6 (controls) / 12 (panels),
28 px controls, 34 px large buttons. Light and dark are designed separately:
dark spreads its background levels further apart instead of inverting light.
Widgets never hard-code colours: they use objectNames styled here, or tokens().
"""

from __future__ import annotations

from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    # background levels: window, sections/top bar, cards, inputs
    "bg": "#f5f5f7", "bar": "#fbfbfd", "card": "#ffffff", "tertiary": "#e8e8ed", "field": "#ffffff",
    "text": "#1d1d1f", "subtext": "#6e6e73", "tertext": "#aeaeb2",
    "edge": "rgba(0,0,0,0.08)", "edge_strong": "rgba(0,0,0,0.15)",
    "hover": "rgba(0,0,0,0.04)", "pressed": "rgba(0,0,0,0.08)",
    "button": "#ffffff", "accent": "#007aff", "accent_hover": "#0066d6", "accent_pressed": "#0058b8",
    "accent_disabled": "#a9cdfa", "accent_soft": "rgba(0,122,255,0.10)",
    "selection": "rgba(0,122,255,0.14)", "segment_bg": "rgba(0,0,0,0.06)", "track": "#e5e5ea",
    "scroll": "rgba(0,0,0,0.22)", "disabled": "#aeaeb2",
    "danger": "#ff3b30", "success": "#34c759", "warning": "#c76f00",
    "badge_local_bg": "rgba(52,199,89,0.14)", "badge_local_fg": "#1d7a37",
    "badge_vault_bg": "rgba(0,122,255,0.12)", "badge_vault_fg": "#0058b8",
    "badge_old_bg": "rgba(0,0,0,0.06)", "badge_old_fg": "#6e6e73",
    "toast_bg": "rgba(40,40,42,0.94)", "toast_fg": "#ffffff", "kbd_bg": "rgba(128,128,128,0.12)",
}

DARK = {
    "bg": "#1c1c1e", "bar": "#232325", "card": "#2c2c2e", "tertiary": "#3a3a3c", "field": "#1c1c1e",
    "text": "#f5f5f7", "subtext": "#98989d", "tertext": "#636366",
    "edge": "rgba(255,255,255,0.08)", "edge_strong": "rgba(255,255,255,0.15)",
    "hover": "rgba(255,255,255,0.06)", "pressed": "rgba(255,255,255,0.10)",
    "button": "#3a3a3c", "accent": "#0a84ff", "accent_hover": "#409cff", "accent_pressed": "#0a6fd6",
    "accent_disabled": "#1d4f86", "accent_soft": "rgba(10,132,255,0.18)",
    "selection": "rgba(10,132,255,0.32)", "segment_bg": "rgba(255,255,255,0.07)", "track": "#3a3a3c",
    "scroll": "rgba(255,255,255,0.25)", "disabled": "#636366",
    "danger": "#ff453a", "success": "#30d158", "warning": "#ff9f0a",
    "badge_local_bg": "rgba(48,209,88,0.18)", "badge_local_fg": "#5fe07c",
    "badge_vault_bg": "rgba(10,132,255,0.24)", "badge_vault_fg": "#6cb4ff",
    "badge_old_bg": "rgba(255,255,255,0.08)", "badge_old_fg": "#a1a1a6",
    "toast_bg": "rgba(58,58,60,0.96)", "toast_fg": "#f5f5f7", "kbd_bg": "rgba(128,128,128,0.22)",
}

# Apple type scale (px): Large Title 26 bold, Title 3 15 semibold, Body 13, Callout 12, Caption 11.
QSS = Template("""
QWidget { color: $text; font-family: "$font"; font-size: 13px; }
QMainWindow, QDialog, QWidget#Page, QScrollArea, QScrollArea > QWidget > QWidget#Page { background: $bg; }
QWidget#Transparent { background: transparent; }
QWidget#TopBar { background: $bar; border-bottom: 1px solid $edge; }
QFrame#Card { background: $card; border: 1px solid $edge; border-radius: 8px; }
QFrame#Panel { background: $card; border: 1px solid $edge_strong; border-radius: 12px; }
QFrame#ActionBar { background: $card; border: 1px solid $edge_strong; border-radius: 10px; }
QFrame#DropTarget { background: $accent_soft; border: 2px dashed $accent; border-radius: 8px; }
QLabel { background: transparent; }
QLabel#Title { font-size: 26px; font-weight: 700; }
QLabel#Title1 { font-size: 22px; font-weight: 400; }
QLabel#H2 { font-size: 15px; font-weight: 600; }
QLabel#AppName { font-size: 15px; font-weight: 600; }
QLabel#Subtle { color: $subtext; font-size: 12px; }
QLabel#Caption { color: $subtext; font-size: 11px; }
QLabel#Danger { color: $danger; font-size: 12px; }
QLabel#Warning { color: $warning; font-size: 12px; }
QLabel#Stat { font-size: 17px; font-weight: 600; }
QLabel#EmptyTitle { font-size: 17px; font-weight: 600; }
QLabel#Kbd { color: $subtext; background: $kbd_bg; border: 1px solid $edge; border-radius: 4px;
             padding: 1px 6px; font-size: 11px; }
QLabel#Toast { color: $toast_fg; background: $toast_bg; border-radius: 10px; padding: 10px 16px;
               font-size: 13px; font-weight: 500; }

QPushButton { background: $button; border: 1px solid $edge_strong; border-radius: 6px; padding: 4px 12px;
              min-height: 18px; }
QPushButton:hover { background: $hover; }
QPushButton:pressed { background: $pressed; }
QPushButton:focus { border: 1px solid $accent; }
QPushButton:disabled { color: $disabled; border-color: $edge; }
QPushButton#Primary { background: $accent; color: #ffffff; border: 1px solid $accent; font-weight: 600;
                      padding: 7px 18px; border-radius: 6px; }
QPushButton#Primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#Primary:pressed { background: $accent_pressed; }
QPushButton#Primary:focus { border: 2px solid $text; }
QPushButton#Primary:disabled { background: $accent_disabled; border-color: $accent_disabled; color: #ffffff; }
QPushButton#Link { background: transparent; border: none; color: $accent; padding: 2px 4px; }
QPushButton#Link:hover { text-decoration: underline; }
QWidget#SegmentBar { background: $segment_bg; border-radius: 7px; }
QPushButton#Segment { background: transparent; border: 1px solid transparent; border-radius: 6px;
                      padding: 3px 16px; color: $subtext; min-height: 18px; }
QPushButton#Segment:hover { color: $text; }
QPushButton#Segment:checked { background: $card; color: $text; font-weight: 600; border: 1px solid $edge; }
QPushButton#Segment:focus { border: 1px dashed $accent; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px; }
QToolButton:hover { background: $hover; }
QToolButton:pressed { background: $pressed; }
QToolButton:focus { border: 1px solid $accent; }
QToolButton:disabled { color: $disabled; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QDateTimeEdit {
    background: $field; border: 1px solid $edge_strong; border-radius: 6px; padding: 4px 8px;
    selection-background-color: $accent; selection-color: #ffffff; min-height: 18px; }
QLineEdit#Search { background: $segment_bg; border: 1px solid transparent; border-radius: 7px; padding: 4px 8px; }
QLineEdit#Search:focus { background: $field; border: 1px solid $accent; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid $accent; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $edge_strong; selection-background-color: $accent;
                              selection-color: #ffffff; outline: 0; }
QPlainTextEdit#Log { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; color: $subtext;
                     border: 1px solid $edge; }

QListWidget, QTreeView, QTableView { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 6px 4px; border: none; min-height: 22px; }
QTreeView::item { padding: 0 4px; border: none; height: 34px; }
QListWidget::item:selected, QTreeView::item:selected { background: $selection; color: $text; }
QListWidget::item:hover, QTreeView::item:hover { background: $hover; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; color: $subtext; border: none; border-bottom: 1px solid $edge;
                       padding: 6px 4px; font-weight: 600; font-size: 11px; }

QProgressBar { background: $track; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QProgressBar#Thin { max-height: 4px; min-height: 4px; border-radius: 2px; }
QProgressBar#Thin::chunk { border-radius: 2px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { width: 0; height: 0;
    background: transparent; }

QMenu { background: $card; border: 1px solid $edge_strong; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 5px 20px; border-radius: 4px; }
QMenu::item:selected { background: $accent; color: #ffffff; }
QMenu::item:disabled { color: $disabled; }
QMenu::separator { height: 1px; background: $edge; margin: 4px 8px; }
QToolTip { background: $card; color: $text; border: 1px solid $edge_strong; padding: 3px 6px; border-radius: 4px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListView::indicator, QTreeView::indicator {
    width: 16px; height: 16px; border: 1px solid $edge_strong; border-radius: 4px; background: $field; }
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

# Animation timings from the skill (ease-out ~ OutQuad; fast 150 ms, normal 250 ms, slow 400 ms).
FAST, NORMAL, SLOW = 150, 250, 400

_current = dict(LIGHT)
_dark = False
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


def tokens() -> dict:
    return _current


def is_dark() -> bool:
    return _dark


def color(name: str) -> QColor:
    """QColor for a token; accepts both #rrggbb and rgba(r,g,b,a) values."""
    v = _current[name]
    if v.startswith("rgba("):
        r, g, b, a = (x.strip() for x in v[5:-1].split(","))
        return QColor(int(r), int(g), int(b), int(float(a) * 255))
    return QColor(v)


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
    f.setPixelSize(13)
    app.setFont(f)
    pal = QPalette()
    for role, tok in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "field"),
                      (QPalette.AlternateBase, "tertiary"), (QPalette.Text, "text"), (QPalette.Button, "button"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.ToolTipBase, "card"), (QPalette.ToolTipText, "text"),
                      (QPalette.PlaceholderText, "subtext"), (QPalette.Link, "accent")):
        pal.setColor(role, color(tok))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, color("disabled"))
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(font=fam, **_current, **_assets(dark)))


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
