r"""Render assets/logo.svg into PNGs, a multi-size Windows .ico and the web favicon.

    .venv\Scripts\python tools\make_icons.py
Needs only PySide6 (QtSvg): pip install -r requirements-dev.txt. The .ico is written by hand with PNG-compressed entries.
"""
import shutil
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(svg: Path, w: int, h: int) -> QImage:
    r = QSvgRenderer(str(svg))
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
    r.render(p, QRectF(0, 0, w, h))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path: Path, frames: dict) -> None:
    n = len(frames)
    out = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    blobs = []
    for size in sorted(frames):
        data = frames[size]
        out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs.append(data)
    path.write_bytes(out + b"".join(blobs))


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    logo = ASSETS / "logo.svg"
    frames = {s: png_bytes(render(logo, s, s)) for s in SIZES}
    write_ico(ASSETS / "icon.ico", frames)
    (ASSETS / "icon-256.png").write_bytes(frames[256])
    (ASSETS / "icon-512.png").write_bytes(png_bytes(render(logo, 512, 512)))
    wm = ASSETS / "logo-wordmark.svg"
    if wm.exists():
        (ASSETS / "logo-wordmark.png").write_bytes(png_bytes(render(wm, 1280, 320)))
    pub = ROOT / "web" / "public"
    pub.mkdir(exist_ok=True)
    shutil.copy(logo, pub / "logo.svg")
    shutil.copy(ASSETS / "icon.ico", pub / "favicon.ico")
    print("wrote", sorted(p.name for p in ASSETS.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
