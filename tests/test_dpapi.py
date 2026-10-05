import sys

import pytest

from app import dpapi

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def test_round_trip():
    blob = dpapi.protect("sk-ant-secret ✓")
    assert blob.startswith("dpapi:v1:") and "secret" not in blob
    assert dpapi.unprotect(blob) == "sk-ant-secret ✓"


def test_garbage_raises():
    with pytest.raises(dpapi.DpapiError):
        dpapi.unprotect("dpapi:v1:AAAA")
    with pytest.raises(dpapi.DpapiError):
        dpapi.unprotect("plain")


def test_available():
    assert dpapi.available()
