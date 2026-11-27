from types import SimpleNamespace
import sys

from geostudio.web_app import __main__ as desktop


def test_native_runtime_check_is_windows_only(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "clr", SimpleNamespace(AddReference=calls.append))
    monkeypatch.setattr(desktop, "os", SimpleNamespace(name="posix"))
    desktop._check_windows_runtime()
    assert calls == []
    monkeypatch.setattr(desktop, "os", SimpleNamespace(name="nt"))
    desktop._check_windows_runtime()
    assert calls == ["System.Windows.Forms"]


def test_loader_error_detection_is_specific():
    assert desktop._is_pythonnet_loader_error(RuntimeError(
        "Failed to resolve Python.Runtime.Loader.Initialize from Python.Runtime.dll"))
    assert not desktop._is_pythonnet_loader_error(RuntimeError("Other runtime failure"))
