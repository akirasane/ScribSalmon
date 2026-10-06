"""Pinned facts about the NVIDIA cuBLAS 12 runtime that the Whisper engine (CTranslate2) needs on Windows.

Shared by app.gpu (diagnostics) and app.gpulibs (downloader). Constants only, no logic beyond path helpers.
Values verified against the PyPI JSON API and the wheel's RECORD; update with tools/pin_gpu_libs.py.
"""
import os
from pathlib import Path

PACKAGE = "nvidia-cublas-cu12"
VERSION = "12.9.2.10"
WHEEL_NAME = "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl"
URL = ("https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/"
       "nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl")
SIZE = 553_162_896
SHA256 = "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661"
ALLOWED_HOSTS = frozenset({"files.pythonhosted.org"})
EULA_URL = "https://docs.nvidia.com/cuda/eula/index.html"

# wheel member -> (file name we write, size, sha256). Nothing else in the wheel is ever extracted.
MEMBERS = {
    "nvidia/cublas/bin/cublas64_12.dll": ("cublas64_12.dll", 102_518_272,
                                          "52ce5ba0ec5327d39be6021f0f9362d2ed4d64d7206f9b5afc06398d827b8e82"),
    "nvidia/cublas/bin/cublasLt64_12.dll": ("cublasLt64_12.dll", 668_673_536,
                                            "71705a7cf0923f4ab034d0d2620bbfc989ff669ac3d79f868b7a7c597ca559c5"),
    "nvidia_cublas_cu12-12.9.2.10.dist-info/licenses/License.txt": ("License.txt", 59_262,
                                                                  "ad6f5853fba0ca0d159d0f58d49ae49830c2f8c93f7a92648b9ce90adb4c6ccd"),
}
REQUIRED_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll")
MANIFEST_NAME = "manifest.json"
FOLDER_NAME = f"{PACKAGE}-{VERSION}"
INSTALLED_BYTES = sum(m[1] for m in MEMBERS.values())          # ~771 MB on disk
REQUIRED_FREE_BYTES = SIZE + INSTALLED_BYTES + 100 * 1024 * 1024  # wheel + extracted + margin (~1.43 GB)


def libs_root() -> Path:
    """%LOCALAPPDATA%/ScribSalmon/gpu-libs (Local, not Roaming: 771 MB must not sync)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ScribSalmon" / "gpu-libs"
