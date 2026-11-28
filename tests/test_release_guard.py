"""The publish guard refuses old source code with a newer release tag."""
from pathlib import Path

import pytest

from geostudio import __version__
from tools.windows.check_release import check_source

ROOT = Path(__file__).resolve().parents[1]


def test_source_matches_its_tag():
    assert check_source(ROOT, "v" + __version__) == __version__


@pytest.mark.parametrize("tag", ["v99.99.99", "preview", "2.0.99", "v2.0.99-rc1"])
def test_wrong_tag_is_refused(tag):
    with pytest.raises(ValueError):
        check_source(ROOT, tag)


def _valid_config():
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return ["test-geostudio", "test_key_not_a_real_firebase_key",
            "https://offline.example.workers.dev",
            base64.urlsafe_b64encode(key).decode().rstrip("="),
            "https://admin.example.workers.dev"]


def test_release_requires_all_five_client_settings():
    from geostudio.web_app.firebase_auth import AuthError
    from tools.windows.configure_firebase import render_config
    values = _valid_config()
    namespace = {}
    exec(render_config(*values, require_full=True), namespace)
    assert namespace["ADMIN_URL"] == values[4]
    for i in range(len(values)):
        incomplete = values.copy()
        incomplete[i] = ""
        with pytest.raises(AuthError):
            render_config(*incomplete, require_full=True)


def test_release_requires_a_real_public_key():
    import base64
    from geostudio.web_app.firebase_auth import AuthError
    from tools.windows.configure_firebase import render_config
    values = _valid_config()
    values[3] = base64.urlsafe_b64encode(b"\x04" + bytes(64)).decode().rstrip("=")
    with pytest.raises(AuthError):
        render_config(*values, require_full=True)


def test_frozen_release_selftest_fails_closed(monkeypatch):
    from geostudio.web_app import firebase_auth as auth, updater
    from geostudio.web_app.__main__ import _selftest_release
    monkeypatch.setattr(updater, "current_version", lambda: __version__)
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    monkeypatch.setattr(auth, "load_config", lambda: auth.FirebaseConfig(*_valid_config()))
    assert _selftest_release(__version__) == 1
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    assert _selftest_release(__version__) == 0
    assert _selftest_release("0.0.0") == 1
    monkeypatch.setattr(auth, "load_config",
                        lambda: auth.FirebaseConfig(*_valid_config()[:2]))
    assert _selftest_release(__version__) == 1


def test_108_can_discover_new_release_installer(monkeypatch):
    from geostudio.web_app import updater
    asset = "GeoStudio2-Setup-" + __version__ + "-x64.exe"
    url = "https://github.com/wskakuj/GeoStudio/releases/download/v" + __version__ + "/" + asset
    monkeypatch.setattr(updater, "fetch_latest_release", lambda timeout=6.0: {
        "tag_name": "v" + __version__,
        "assets": [{"name": asset, "browser_download_url": url}],
    })
    result = updater.check_for_update(current="2.0.108")
    assert result and result["assetUrl"] == url
    assert updater.check_for_update(current=__version__) is None
