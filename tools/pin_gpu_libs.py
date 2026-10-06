"""Dev tool: (re)generate the pinned values in app/gpuconst.py for a new nvidia-cublas-cu12 release.

PyPI JSON is parsed ONLY here, never by the app at runtime.

  python tools/pin_gpu_libs.py 12.9.2.10                 # query PyPI, range-read the wheel's RECORD, print a block
  python tools/pin_gpu_libs.py 12.9.2.10 --wheel X.whl   # same but read a local wheel (hashes computed locally)

Review the printed block against the PyPI page before pasting it into app/gpuconst.py.
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

PACKAGE = "nvidia-cublas-cu12"
ALLOWED_HOSTS = frozenset({"files.pythonhosted.org"})
WANTED = ("cublas64_12.dll", "cublasLt64_12.dll", "License.txt")


def parse_pypi_json(data: dict, version: str) -> dict:
    """Return {url, size, sha256, filename} for the win_amd64 wheel of `version`; raise ValueError otherwise."""
    files = (data.get("releases") or {}).get(version)
    if files is None and data.get("info", {}).get("version") == version:
        files = data.get("urls")
    if not files:
        raise ValueError(f"version {version} not found")
    cands = [f for f in files if str(f.get("filename", "")).endswith("win_amd64.whl")]
    if len(cands) != 1:
        raise ValueError(f"expected exactly one win_amd64 wheel, found {len(cands)}")
    f = cands[0]
    if f.get("yanked"):
        raise ValueError("wheel is yanked")
    url = f.get("url", "")
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS or u.port not in (None, 443):
        raise ValueError(f"download host not allowed: {url}")
    sha = (f.get("digests") or {}).get("sha256", "")
    size = f.get("size")
    if len(sha) != 64 or not isinstance(size, int) or size <= 0:
        raise ValueError("missing sha256/size")
    return {"url": url, "size": size, "sha256": sha.lower(), "filename": f["filename"]}


class _HttpRange(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (enough for zipfile)."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n < 0 or self.pos + n > self.size:
            n = self.size - self.pos
        if n <= 0:
            return b""
        req = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos + n - 1}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        self.pos += len(data)
        return data


def record_entries(zf: zipfile.ZipFile) -> dict:
    """{member: (size, sha256 hex)} for the wanted members, from the wheel's *.dist-info/RECORD."""
    name = next(n for n in zf.namelist() if n.endswith(".dist-info/RECORD"))
    out = {}
    for row in csv.reader(io.StringIO(zf.read(name).decode("utf-8"))):
        if len(row) >= 3 and row[0].rsplit("/", 1)[-1] in WANTED and row[1].startswith("sha256="):
            b64 = row[1][7:]
            out[row[0]] = (int(row[2]), base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).hex())
    return out


def render(version: str, info: dict, members: dict) -> str:
    lines = ['PACKAGE = "%s"' % PACKAGE, 'VERSION = "%s"' % version,
             'WHEEL_NAME = "%s"' % info["filename"], 'URL = "%s"' % info["url"],
             "SIZE = %s" % format(info["size"], ","), 'SHA256 = "%s"' % info["sha256"], "MEMBERS = {"]
    for m, (size, sha) in sorted(members.items()):
        lines.append('    "%s": ("%s", %s,\n        "%s"),' % (m, m.rsplit("/", 1)[-1], format(size, "_"), sha))
    lines.append("}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version")
    ap.add_argument("--wheel", help="local wheel file instead of HTTP range reads")
    a = ap.parse_args(argv)
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE}/{a.version}/json", timeout=30) as r:
        data = json.load(r)
    info = parse_pypi_json({"info": data["info"], "urls": data["urls"]}, a.version)
    if a.wheel:
        zf = zipfile.ZipFile(a.wheel)
        if Path(a.wheel).stat().st_size != info["size"]:
            print("WARNING: local wheel size differs from PyPI", file=sys.stderr)
    else:
        zf = zipfile.ZipFile(_HttpRange(info["url"], info["size"]))
    members = record_entries(zf)
    if len(members) != len(WANTED):
        print(f"WARNING: found {len(members)} of {len(WANTED)} wanted members in RECORD", file=sys.stderr)
    print(render(a.version, info, members))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
