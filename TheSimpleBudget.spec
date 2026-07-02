# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller build spec for The Simple Budget.

Build with:  pyinstaller --noconfirm --clean TheSimpleBudget.spec

pyttsx3 loads its speech driver dynamically, so PyInstaller can't see it by
static analysis -- we add the platform's driver as a hidden import explicitly.
"""
import sys
from PyInstaller.utils.hooks import collect_data_files

if sys.platform == "darwin":
    driver = "pyttsx3.drivers.nsss"
elif sys.platform == "win32":
    driver = "pyttsx3.drivers.sapi5"
else:
    driver = "pyttsx3.drivers.espeak"

# python-docx ships a default .docx template and fpdf2 ships font metrics;
# both are loaded at runtime and must be bundled or exports would fail.
datas = []
for pkg in ("docx", "fpdf"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

a = Analysis(
    ["budget_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["pyttsx3.drivers", driver],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TheSimpleBudget",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TheSimpleBudget",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TheSimpleBudget.app",
        icon=None,
        bundle_identifier="com.mediaswing.thesimplebudget",
    )
