# PyInstaller recipe for EduKit — the same file builds Windows (EduKit.exe) and macOS (EduKit.app).
#   cd desktop
#   pyinstaller --noconfirm packaging/edukit.spec
# Output: dist/EduKit/EduKit.exe (Windows) or dist/EduKit.app (macOS)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

HERE = Path(SPECPATH)            # desktop/packaging
DESKTOP = HERE.parent            # desktop
ROOT = DESKTOP.parent            # repository root
APP_VERSION = "0.1.0"

datas = [
    (str(ROOT / "sample_data"), "sample_data"),
    (str(DESKTOP / "edukit" / "data" / "schema.sql"), "edukit/data"),
    (str(HERE / "icon.png"), "."),
    (str(DESKTOP / "edukit" / "ui" / "assets"), "edukit/ui/assets"),
]

# Qt modules EduKit never uses (keeps the download ~3x smaller)
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets", "PySide6.QtQml", "PySide6.QtQuickControls2",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.QtSpatialAudio", "PySide6.QtSerialBus", "PySide6.QtVirtualKeyboard",
    "tkinter", "pytest", "pytestqt", "platformio", "PIL", "numpy", "pyflakes",
]

# Bluetooth LE (bleak) + its platform backends
hidden = ["serial.tools.list_ports", "PySide6.QtMultimedia", "PySide6.QtTextToSpeech"] + collect_submodules("bleak")
if sys.platform == "darwin":
    hidden += ["objc", "Foundation", "CoreBluetooth", "libdispatch"]
elif sys.platform == "win32":
    hidden += collect_submodules("winrt")

a = Analysis(
    [str(DESKTOP / "run.py")],
    pathex=[str(DESKTOP)],
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(HERE / ("icon.ico" if sys.platform == "win32" else "icon.icns"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EduKit",
    console=False,            # no black terminal window
    icon=icon,
    version=str(HERE / "version_info.txt") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="EduKit")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="EduKit.app",
        icon=icon,
        bundle_identifier="org.edukit.classroom",
        version=APP_VERSION,
        info_plist={
            "CFBundleDisplayName": "EduBond — رحلة إلى مكة",
            "CFBundleShortVersionString": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
            # required by macOS before any Bluetooth use (otherwise the app is terminated)
            "NSMicrophoneUsageDescription": "EduKit records your voice for game sounds (correct, wrong, win…). / يسجّل EduKit صوتك لأصوات اللعبة.",
            "NSBluetoothAlwaysUsageDescription": "EduKit connects to the classroom ESP32 boards (buttons and LED map) over Bluetooth. / يتصل EduKit بلوحات الصف عبر البلوتوث.",
        },
    )
