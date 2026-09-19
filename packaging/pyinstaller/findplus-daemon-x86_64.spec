# x86_64 (Intel) build — see findplus-daemon.spec for arm64.
# PyInstaller spec — findplus-daemon onedir sidecar (arm64).
#
# Purpose    : Bundle the Python daemon so the Tauri desktop app can spawn it
#              without a system Python or venv. Onedir (not onefile): onefile
#              extracts ~150 MB per launch, triggers Gatekeeper every run, and
#              complicates library validation (specs/desktop-app.md ADR-P1-03).
# Inputs     : Run from the repo root: `pyinstaller
#              packaging/pyinstaller/findplus-daemon.spec`.
# Outputs    : dist/findplus-daemon/ (onedir), copied to
#              desktop/src-tauri/binaries/findplus-daemon-x86_64-apple-darwin/.
# Constraints: codesign_identity=None — packaging/scripts/sign-sidecar.sh signs
#              every Mach-O afterwards. See specs/packaging-and-release.md §
#              PyInstaller spec (binding: datas, hiddenimports, excludes).
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

datas = [
    ("web", "findplus/web/static"),
    ("cli/src/findplus/db/migrations", "findplus/db/migrations"),
    ("cli/vendor/GoogleFindMyTools", "findplus/_vendor/GoogleFindMyTools"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "alembic",
    "alembic.runtime.migration",
    "sqlalchemy.dialects.sqlite",
    "findplus.db.migrations.env",
    "google.protobuf",
    "gpsoauth",
    "undetected_chromedriver",
    "selenium",
    "pkg_resources.extern",
] + collect_submodules("findplus")

excludes = ["tests", "playwright", "frida", "tkinter"]

a = Analysis(
    ["packaging/pyinstaller/entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="findplus-daemon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="findplus-daemon",
)

# Post-build: copy the onedir output next to the Tauri sidecar externalBin path
# so `cargo tauri build` can pick it up without a manual copy step.
_dest = Path("desktop/src-tauri/binaries/findplus-daemon-x86_64-apple-darwin")
_dest.mkdir(parents=True, exist_ok=True)
shutil.copytree("dist/findplus-daemon", _dest, dirs_exist_ok=True)
