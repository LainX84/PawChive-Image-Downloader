# PyInstaller specification for PawChive Image Downloader.
#
#   python -m PyInstaller packaging/pawchive.spec --noconfirm
#
# or simply:  python tools/build.py
# Produces dist/PawChive Image Downloader/ (Windows, Linux) or
# dist/PawChive Image Downloader.app (macOS).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, str(ROOT / "src"))
from pawchive_downloader.version import APP_NAME, __version__  # noqa: E402

ICONS = ROOT / "packaging" / "icons"
if sys.platform == "win32":
    ICON = str(ICONS / "app.ico")
elif sys.platform == "darwin":
    ICON = str(ICONS / "app.icns")
else:
    ICON = str(ICONS / "app.png")

# Qt modules the application does not use: leaving them out saves ~150 MB.
QT_EXCLUDES = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialBus",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtHttpServer",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSvgWidgets", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtConcurrent",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "PawChiveDownloader.pyw")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src" / "pawchive_downloader" / "storage" / "migrations" / "*.sql"),
         "pawchive_downloader/storage/migrations"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "DISCLAIMER.md"), "."),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    ],
    hiddenimports=collect_submodules("keyring.backends") + collect_submodules("pawchive_downloader"),
    excludes=["tkinter", "pytest", "respx", *QT_EXCLUDES],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PawChiveDownloader",
    console=False,
    icon=ICON,
    target_arch=None,  # the architecture of the Python running PyInstaller
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON,
        bundle_identifier="io.github.lainx84.pawchive-image-downloader",
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # follow the system light/dark appearance
            "LSMinimumSystemVersion": "12.0",
            "NSHumanReadableCopyright": "Copyright (c) 2026 LainX84 — MIT License",
        },
    )
