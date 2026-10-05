# PyInstaller spec - builds dist/ScribSalmon/ScribSalmon.exe (one-folder, windowed).
# Build the UI first:  cd web && npm ci && npm run build
from PyInstaller.utils.hooks import collect_all

datas = [("web/dist", "web/dist"), ("assets/icon.ico", "assets")]
binaries, hiddenimports = [], []
for pkg in ("faster_whisper", "ctranslate2", "webview", "soundcard", "sounddevice", "av", "tokenizers", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

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
)
coll = COLLECT(exe, a.binaries, a.datas, name="ScribSalmon")
