# PyInstaller spec for VaultMove.
#   pyinstaller packaging/vaultmove.spec                       -> dist/VaultMove/ (onedir, installer payload)
#   set VAULTMOVE_ONEFILE=1 && pyinstaller packaging/vaultmove.spec -> dist/VaultMove-Portable-x.y.z.exe
# UPX is deliberately NOT used: UPX-packed Qt DLLs are a classic antivirus false-positive trigger.
import os
import re

ONEFILE = os.environ.get("VAULTMOVE_ONEFILE") == "1"
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
with open(os.path.join(ROOT, "vaultmove", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)

# Only QtCore, QtGui and QtWidgets are used. Everything else is excluded explicitly.
QT_EXCLUDES = [
    "PySide6." + m for m in (
        "QtNetwork", "QtNetworkAuth", "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtQuick3D",
        "QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel", "QtWebSockets", "QtWebView",
        "QtHttpServer", "QtMultimedia", "QtMultimediaWidgets", "QtSpatialAudio", "QtTextToSpeech",
        "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic", "Qt3DAnimation", "Qt3DExtras",
        "QtCharts", "QtDataVisualization", "QtGraphs", "QtGraphsWidgets", "QtPdf", "QtPdfWidgets", "QtSql",
        "QtTest", "QtXml", "QtOpenGL", "QtOpenGLWidgets", "QtDesigner", "QtHelp", "QtUiTools", "QtBluetooth",
        "QtNfc", "QtPositioning", "QtLocation", "QtSensors", "QtSerialPort", "QtSerialBus", "QtConcurrent",
        "QtDBus", "QtPrintSupport", "QtSvg", "QtSvgWidgets", "QtStateMachine", "QtRemoteObjects", "QtScxml",
        "QtAxContainer", "scripts")
]
PY_EXCLUDES = ["tkinter", "_tkinter", "unittest", "pydoc", "doctest", "lib2to3", "pytest", "_pytest", "pytestqt",
               "pip", "setuptools", "distutils", "xmlrpc", "ftplib", "curses", "IPython", "numpy", "test"]

# Qt files we never need (names are matched case-insensitively against the file name).
DROP_FILES = {
    "opengl32sw.dll",            # 20 MB software OpenGL; Qt Widgets do not use OpenGL
    "d3dcompiler_47.dll",
    "qt6network.dll", "qt6pdf.dll", "qt6qml.dll", "qt6qmlmodels.dll", "qt6qmlmeta.dll", "qt6qmlworkerscript.dll",
    "qt6quick.dll", "qt6opengl.dll", "qt6svg.dll", "qt6virtualkeyboard.dll", "qt6dbus.dll",
    "qminimal.dll", "qoffscreen.dll", "qdirect2d.dll",
    "qjpeg.dll", "qgif.dll", "qtiff.dll", "qwebp.dll", "qtga.dll", "qwbmp.dll", "qicns.dll", "qpdf.dll", "qsvg.dll",
    "qsvgicon.dll", "qschannelbackend.dll", "qopensslbackend.dll", "qcertonlybackend.dll",
    "qnetworklistmanager.dll", "qtuiotouchplugin.dll", "qmodernwindowsstyle.dll", "qwindowsvistastyle.dll",
}
KEEP_TRANSLATIONS = {"qtbase_fr.qm"}


def keep(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1].lower()
    if name in DROP_FILES:
        return False
    if "/translations/" in dest.lower() and name.endswith(".qm"):
        return name in KEEP_TRANSLATIONS
    if "/qml/" in dest.lower():
        return False
    return True


a = Analysis(
    [os.path.join(ROOT, "run_vaultmove.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(ROOT, "vaultmove", "app", "i18n", "vaultmove_fr.qm"), "vaultmove/app/i18n")],
    hiddenimports=["vaultmove.helper.server", "vaultmove.helper.shadow"],
    excludes=QT_EXCLUDES + PY_EXCLUDES,
    noarchive=False,
    optimize=1,
)
a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)
ICON = os.path.join(ROOT, "packaging", "vaultmove.ico")

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name=f"VaultMove-Portable-{VERSION}", icon=ICON, console=False, upx=False,
              runtime_tmpdir=None, disable_windowed_traceback=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VaultMove", icon=ICON, console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="VaultMove", upx=False)
