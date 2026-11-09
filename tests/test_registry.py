from qwencoder_cua.core.registry import detect_linux_session


def test_detect_wayland(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    assert detect_linux_session() == "wayland"


def test_detect_x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert detect_linux_session() == "x11"


def test_detect_unknown(monkeypatch):
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert detect_linux_session() == "unknown"
