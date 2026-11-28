"""Actual Tk widget/flow smoke tests, using a virtual display in CI.

All clients and credentials are synthetic. No network or local vault access.
"""
import os
import time
from types import SimpleNamespace

import pytest

from geostudio.web_app import firebase_auth as auth
from geostudio.web_app.firebase_login import LoginWindow
from geostudio.web_app.firebase_registration import RegistrationWindow


@pytest.fixture
def root():
    try:
        import tkinter as tk
        window = tk.Tk()
    except (ImportError, RuntimeError) as error:
        if os.environ.get("GEOSTUDIO_REQUIRE_AUTH_UI_TEST"):
            raise
        pytest.skip(str(error))
    except tk.TclError as error:
        if os.environ.get("GEOSTUDIO_REQUIRE_AUTH_UI_TEST"):
            raise
        pytest.skip(str(error))
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(exc)
    window.withdraw()
    try:
        yield window
        assert not errors, [str(e[1]) for e in errors]
    finally:
        try:
            window.destroy()
        except tk.TclError:
            pass


def pump(root, condition, timeout=4):
    until = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > until:
            pytest.fail("Tk flow did not reach expected state")
        root.update()
        time.sleep(.015)


class FakeClient:
    config = SimpleNamespace(admin_url="https://test.workers.dev")
    _registration_input = staticmethod(auth.FirebaseClient._registration_input)

    def __init__(self):
        self.calls = []
        self.verified = False
        self.session = None

    def login(self, email, password):
        self.calls.append(("login", email))
        raise auth.AuthDenied("Nieprawidłowe dane.")

    def reset_password(self, email):
        self.calls.append(("reset", email))

    def restore(self, state):
        self.calls.append(("restore", state["refreshToken"]))
        return auth.Grant(auth.Credentials("test", "id-token", "refresh-token", 3600,
                                           "test@example.invalid"),
                          None, offline=True, offline_unlimited=True)

    def begin_registration(self, email, password, code):
        self.calls.append(("begin", email))
        self.session = auth.RegistrationSession(email, code, "test", "refresh",
                                                email_sent=False)
        return self.session

    def resend_registration(self, session):
        assert session is self.session
        self.calls.append(("resend",))
        session.email_sent = True
        return session

    def finish_registration(self, session):
        assert session is self.session
        self.calls.append(("finish",))
        if not self.verified:
            raise auth.AuthDenied("Potwierdź adres e-mail.")
        return {"ok": True, "active": True, "pending": False}


def test_shared_native_styles_and_login_form(root):
    client = FakeClient()
    login = LoginWindow(root, client, None, force_prompt=True, version="2.0.test")
    root.update()
    assert login.email_field.entry.winfo_ismapped()
    assert login.password_field.entry.winfo_ismapped()
    assert login.register.winfo_ismapped()
    assert login.primary.cget("style") == "GS.Primary.TButton"
    assert login.keep.cget("style") == "GS.TCheckbutton"
    assert login.shell.theme.style.layout("GS.Primary.TButton")
    assert login.primary.winfo_width() >= login.primary.winfo_reqwidth()
    assert login.password_field.entry.winfo_width() > 0
    assert login.shell.heading_label.cget("text") == "Zaloguj się"
    login.password.set("synthetic-secret")
    login.password_field.eye.invoke()
    assert not login.password_field.entry.cget("show")
    login.password_field.eye.invoke()
    assert login.password_field.entry.cget("show")
    login.submit()
    assert not login.busy
    assert "Wpisz" in login.notice.text.cget("text")
    login.email.set("test@example.invalid")
    login.primary.invoke()
    assert login.busy
    assert login.primary.instate(["disabled"])
    assert login.progress.job is not None
    pump(root, lambda: not login.busy)
    assert login.password.get() == ""
    assert "Nieprawidłowe" in login.notice.text.cget("text")
    assert login.progress.job is None
    login.reset.invoke()
    pump(root, lambda: not login.busy)
    assert ("reset", "test@example.invalid") in client.calls
    assert "otrzymasz" in login.notice.text.cget("text")
    login.close()


def test_restore_offline_still_uses_access_gate(root):
    client = FakeClient()
    class Vault:
        def __init__(self):
            self.saved = False
        def load_state(self):
            return {"refreshToken":"synthetic-refresh","lastSeen":0}
        def save(self,*args,**kwargs):
            self.saved = True
        def clear(self):
            pass
    vault = Vault()
    login = LoginWindow(root, client, vault, version="2.0.test")
    pump(root, lambda: login.result is not None)
    assert login.result.status()["active"]
    assert login.result.status()["offlineUnlimited"]
    assert vault.saved
    assert client.calls == [("restore", "synthetic-refresh")]


def test_registration_switches_to_verification_and_reuses_session(root):
    root.deiconify()
    client = FakeClient()
    dialog = RegistrationWindow(root, client, "test@example.invalid", version="2.0.test")
    root.update()
    assert dialog.shell.step_label.cget("text") == "KROK 1 Z 2"
    assert dialog.form.winfo_ismapped()
    assert not dialog.resend.winfo_ismapped()
    assert dialog.primary.cget("style") == "GS.Primary.TButton"
    dialog.primary.invoke()
    assert not dialog.busy
    assert dialog.notice.winfo_ismapped() or dialog.notice.winfo_manager()
    dialog.password.set("synthetic-password")
    dialog.code.set("GS-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
    dialog.primary.invoke()
    assert dialog.busy
    pump(root, lambda: dialog.page == "verify" and not dialog.busy)
    root.update()
    assert not dialog.form.winfo_ismapped()
    assert dialog.verify.winfo_ismapped()
    assert dialog.shell.step_label.cget("text") == "KROK 2 Z 2"
    assert dialog.recipient.get() == "test@example.invalid"
    assert dialog.password.get() == "" and dialog.code.get() == ""
    assert dialog.resend.winfo_ismapped()
    assert not dialog.resend.instate(["disabled"])
    dialog.resend.invoke()
    pump(root, lambda: not dialog.busy)
    assert dialog.resend.instate(["disabled"])
    assert "ponownie" in dialog.notice.text.cget("text")
    dialog.primary.invoke()
    pump(root, lambda: not dialog.busy)
    assert "Potwierdź" in dialog.notice.text.cget("text")
    client.verified = True
    dialog.primary.invoke()
    pump(root, lambda: dialog.result is not None)
    assert dialog.result == ("test@example.invalid", "Konto gotowe! Zaloguj się.")
    assert client.session.refresh_token == "" and client.session.code == ""
    assert client.calls == [("begin","test@example.invalid"),("resend",),("finish",),("finish",)]


def test_registration_close_clears_session_and_returns_resume_hint(root):
    root.deiconify()
    client = FakeClient()
    dialog = RegistrationWindow(root, client, "test@example.invalid")
    dialog.password.set("synthetic-password")
    dialog.code.set("GS-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
    dialog.primary.invoke()
    pump(root, lambda: dialog.page == "verify" and not dialog.busy)
    dialog.close()
    assert "wznowić" in dialog.result[1]
    assert not client.session.refresh_token and not client.session.code


def test_large_dpi_can_scroll_and_reach_primary(root):
    # Simulate the high-DPI Windows case in a smaller virtual work area.
    root.tk.call("tk", "scaling", 2.2)
    root.deiconify()
    dialog = RegistrationWindow(root, FakeClient(), "test@example.invalid")
    root.update()
    assert dialog.win.winfo_height() <= root.winfo_screenheight()
    assert dialog.shell.canvas.bbox("all")
    if dialog.shell.scroll.winfo_ismapped():
        dialog.shell.canvas.yview_moveto(1)
        root.update()
        assert dialog.shell.canvas.yview()[1] >= .99
    dialog.close()
