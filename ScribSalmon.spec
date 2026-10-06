# PyInstaller spec - builds dist/ScribSalmon/ScribSalmon.exe (one-folder, windowed).
# Build the UI first:  cd web && npm ci && npm run build
import re
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)  # noqa: F821 - provided by PyInstaller
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

# Packages the app cannot run without: a failed collect_all must fail the build, not ship a broken exe.
REQUIRED = ("faster_whisper", "ctranslate2", "webview", "soundcard", "sounddevice", "av", "onnxruntime",
            "tokenizers")

datas = [("web/dist", "web/dist"), ("assets/icon.ico", "assets"), ("LICENSE", "."), ("VERSION", ".")]
binaries, hiddenimports = [], []
for pkg in REQUIRED:
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:
        raise SystemExit(f"collect_all({pkg!r}) failed: {e!r} - refusing to build an incomplete app")
    datas += d
    binaries += b
    hiddenimports += h

# app modules that are only reached dynamically (selftest imports them by name) must still be bundled
hiddenimports += ["app.updater", "app.gpu", "app.gpulibs", "app.logsetup", "app.gpuconst"]


def _write_version_info() -> str:
    """PyInstaller version resource (file/product version shown in Explorer) generated from VERSION."""
    nums = [int(x) for x in re.findall(r"\d+", VERSION)[:4]]
    nums += [0] * (4 - len(nums))
    tup = tuple(nums)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'OmeletteSalmon'),
      StringStruct('FileDescription', 'ScribSalmon'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'ScribSalmon'),
      StringStruct('OriginalFilename', 'ScribSalmon.exe'),
      StringStruct('ProductName', 'ScribSalmon'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    out = ROOT / "build" / "version_info.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return str(out)


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PySide6", "shiboken6", "tkinter", "matplotlib"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ScribSalmon",
    console=False,
    icon="assets/icon.ico",
    version=_write_version_info(),
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScribSalmon")

# pythonnet/WinForms needs ScribSalmon.exe.config next to the exe (without it 1.0.0 crashed on start);
# copy it here so local builds work the same as release builds.
shutil.copy2(ROOT / "packaging" / "ScribSalmon.exe.config",
             Path(DISTPATH) / "ScribSalmon" / "ScribSalmon.exe.config")  # noqa: F821
