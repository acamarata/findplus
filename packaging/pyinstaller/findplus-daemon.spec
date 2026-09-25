# PyInstaller spec — findplus-daemon onedir sidecar (arm64).
#
# Purpose    : Bundle the Python daemon so the Tauri desktop app can spawn it
#              without a system Python or venv. Onedir (not onefile): measured
#              on this machine, onefile re-extracts ~90 MB and answers
#              `--version` in 2.3-3.4 s against 0.38 s for onedir
#              (specs/desktop-app.md ADR-P1-03).
# Inputs     : `pyinstaller packaging/pyinstaller/findplus-daemon.spec` from any
#              directory. Every path below is derived from SPECPATH, because
#              PyInstaller resolves relative paths in a spec against the spec's
#              own directory, not the current one.
# Outputs    : <distpath>/findplus-daemon/ (onedir), copied to
#              desktop/src-tauri/resources/findplus-daemon/ (shipped as a Tauri
#              bundle resource; binaries/findplus-daemon-<triple> is a small
#              launcher that execs it).
# Constraints: codesign_identity=None — packaging/scripts/sign-sidecar.sh signs
#              every Mach-O afterwards. See specs/packaging-and-release.md §
#              PyInstaller spec (binding: datas, hiddenimports, excludes).
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# SPECPATH is injected by PyInstaller: <repo>/packaging/pyinstaller.
ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821

# Both specs import this, so the filter cannot be fixed in one and missed in
# the other again (E1 security round 3 F3).
import sys

sys.path.insert(0, SPECPATH)  # noqa: F821
from spec_datas import (  # noqa: E402
    apple_extra,
    daemon_datas,
    vendor_hiddenimports,
    vendor_metadata,
)

apple_hidden, apple_datas, apple_binaries = apple_extra()
datas = daemon_datas(ROOT) + apple_datas + vendor_metadata()

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
] + collect_submodules("findplus") + apple_hidden + vendor_hiddenimports()

excludes = ["tests", "playwright", "frida", "tkinter"]

a = Analysis(
    [str(ROOT / "packaging/pyinstaller/entry.py")],
    pathex=[str(ROOT / "cli/src")],
    binaries=apple_binaries,
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
    target_arch="arm64",
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

# Post-build: place the onedir where the Tauri bundler picks it up.
# externalBin entries must be a single FILE named <name>-<triple>, so the
# onedir ships under bundle.resources and binaries/findplus-daemon-<triple> is
# a launcher script that execs findplus-daemon inside it.
_dest = ROOT / "desktop/src-tauri/resources/findplus-daemon"
if _dest.exists():
    shutil.rmtree(_dest)
_dest.parent.mkdir(parents=True, exist_ok=True)
# symlinks=True keeps the .framework symlink layout intact (and stops the copy
# from doubling in size by dereferencing every Versions/Current link).
shutil.copytree(Path(DISTPATH) / "findplus-daemon", _dest, symlinks=True)  # noqa: F821
