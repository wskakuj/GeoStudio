"""Modern native sign-in dialog, before starting the local editor server."""
from __future__ import annotations

import os
import queue
import threading

from .firebase_auth import AccessGate, AuthDenied, AuthError, FirebaseClient, load_config
from .firebase_vault import WindowsSessionVault


class LoginWindow:
    """UI only. A successful AccessGate is still required to open the editor."""
    def __init__(self, root, client, vault, *, force_prompt=False, version=""):
        import tkinter as tk
        from tkinter import ttk
        from .auth_ui import CARD, BORDER, MUTED, Field, Notice, Progress, Shell

        self.root, self.client, self.vault = root, client, vault
        self.version = version
        self.result = None
        self.restored_state = {}
        self.busy = False
        self.pending = queue.Queue()
        self.poll_id = None
        root.title("GeoStudio — Logowanie")
        self.shell = Shell(root, version, privacy=bool(client.config.admin_url))
        t = self.shell.theme
        self.shell.heading("Zaloguj się", "Zaloguj się, aby otworzyć edytor map.")
        form = self.shell.content
        self.email = tk.StringVar(master=root)
        self.password = tk.StringVar(master=root)
        self.remember = tk.BooleanVar(master=root, value=False)
        self.email_field = Field(form, t, "Adres e-mail", self.email,
                                 icon="mail", placeholder="nazwa@domena.pl")
        self.email_field.pack(fill="x", pady=(0, t.dp(14)))
        self.password_field = Field(form, t, "Hasło", self.password,
                                    icon="lock", placeholder="Wprowadź hasło", secret=True)
        self.password_field.pack(fill="x", pady=(0, t.dp(9)))
        options = tk.Frame(form, bg=CARD)
        options.pack(fill="x", pady=(0, t.dp(16)))
        self.keep = t.checkbox(options, "Zapamiętaj mnie", self.remember)
        self.keep.pack(side="left", anchor="w")
        self.reset = t.button(options, "Nie pamiętasz hasła?", self.reset_password, "Link")
        self.reset.pack(side="right")
        self.notice = Notice(form, t)
        self.progress = Progress(form, t)
        self.primary = t.button(form, "Zaloguj się", self.submit)
        self.primary.pack(fill="x")
        self.register = None
        if client.config.admin_url:
            tk.Frame(form, bg=BORDER, height=t.dp(1)).pack(fill="x", pady=(t.dp(18), t.dp(10)))
            footer = tk.Frame(form, bg=CARD)
            footer.pack(fill="x")
            line = tk.Frame(footer, bg=CARD)
            line.pack(anchor="center")
            t.label(line, "Masz kod zaproszenia?", fg=MUTED, size=9, wrap=0).pack(side="left")
            self.register = t.button(line, "Utwórz konto", self.show_registration, "Link")
            self.register.pack(side="left", padx=(t.dp(3), 0))
        self._set_busy(False)

        def enter(event):
            if isinstance(event.widget, ttk.Button) and event.widget is not self.primary:
                event.widget.invoke()
            else:
                self.submit()
            return "break"
        root.bind("<Return>", enter)
        root.bind("<Escape>", lambda _: self.close() or "break")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.shell.fit()
        root.deiconify()
        self.email_field.focus()
        if vault is not None and not force_prompt:
            try:
                self.restored_state = vault.load_state() or {}
                if self.restored_state:
                    self.remember.set(True)
                    self._launch("restore", lambda: client.restore(self.restored_state), True)
            except (OSError, ValueError):
                self._notice("Nie udało się odczytać zapamiętanej sesji. Zaloguj się ponownie.",
                             "warning")

    def _notice(self, text="", kind="info"):
        self.notice.show(text, kind, before=self.primary)
        self.shell.request_fit()

    def _set_busy(self, busy, action=""):
        self.busy = busy
        self.email_field.set_enabled(not busy)
        self.password_field.set_enabled(not busy)
        self.keep.configure(state="normal" if not busy and self.vault else "disabled")
        self.reset.configure(state="disabled" if busy else "normal")
        if self.register is not None:
            self.register.configure(state="disabled" if busy else "normal")
        labels = {"login": "Logowanie…", "restore": "Sprawdzanie sesji…",
                  "reset": "Wysyłanie wiadomości…"}
        self.primary.configure(state="disabled" if busy else "normal",
                               text=labels.get(action, "Łączenie…") if busy else "Zaloguj się")
        if busy:
            self.notice.show("")
            self.progress.start(before=self.primary)
        else:
            self.progress.stop()

    def _launch(self, action, task, keep_session=False):
        if self.busy:
            return
        self._set_busy(True, action)
        self.shell.request_fit()

        def worker():
            try:
                self.pending.put((action, task(), None, keep_session))
            except AuthError as error:
                self.pending.put((action, None, error, keep_session))
            except Exception:
                self.pending.put((action, None, AuthError("Nie udało się sprawdzić dostępu."), keep_session))
        threading.Thread(target=worker, daemon=True, name="GeoStudioSignIn").start()
        self.poll_id = self.root.after(40, self._poll)

    def _poll(self):
        from tkinter import messagebox
        self.poll_id = None
        try:
            action, grant, error, keep_session = self.pending.get_nowait()
        except queue.Empty:
            self.poll_id = self.root.after(40, self._poll)
            return
        self._set_busy(False)
        if action in ("login", "restore") and error is None:
            gate = AccessGate(self.client, grant, self.vault, keep_session,
                              last_seen=self.restored_state.get("lastSeen", 0) if action == "restore" else 0)
            status = gate.status()
            if not status["active"]:
                error = AuthDenied("Sesja wygasła. Zaloguj się ponownie.")
            else:
                if status["storageWarning"]:
                    messagebox.showwarning("GeoStudio", status["storageWarning"], parent=self.root)
                self.result = gate
                self.close()
                return
        if action == "restore" and isinstance(error, AuthDenied) and self.vault is not None:
            try:
                self.vault.clear()
            except OSError:
                pass
        self._notice(str(error) if error else
                     "Jeżeli konto istnieje, otrzymasz e-mail z instrukcją zmiany hasła.",
                     "error" if error else "info")
        if action == "login":
            self.password_field.focus()
        elif action == "restore":
            self.email_field.focus()

    def submit(self):
        if self.busy:
            return
        address, secret, keep_session = self.email.get(), self.password.get(), self.remember.get()
        if not address.strip() or not secret:
            self._notice("Wpisz adres e-mail i hasło.", "error")
            (self.email_field if not address.strip() else self.password_field).focus()
            return
        self.password.set("")
        self.password_field.mask()
        self._launch("login", lambda: self.client.login(address, secret), keep_session)

    def reset_password(self):
        if self.busy:
            return
        address = self.email.get()
        if not address.strip() or "@" not in address:
            self._notice("Wpisz adres e-mail, aby otrzymać link do zmiany hasła.", "info")
            self.email_field.focus()
            return
        self._launch("reset", lambda: self.client.reset_password(address))

    def show_registration(self):
        if self.busy:
            return
        from .firebase_registration import open_registration
        self.password.set("")
        self.password_field.mask()
        registration = open_registration(self.root, self.client, initial_email=self.email.get(),
                                         version=self.version)
        if registration:
            address, notice = registration
            self.email.set(address)
            kind = "success" if notice.startswith("Konto gotowe") else "info"
            self._notice(notice, kind)
            self.password_field.focus()

    def close(self):
        self.password.set("")
        self.progress.stop()
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.root.destroy()


def run_login(force_prompt=False):
    import tkinter as tk
    from tkinter import messagebox
    from .updater import current_version

    root = tk.Tk()
    root.withdraw()
    try:
        client = FirebaseClient(load_config())
    except AuthError as error:
        messagebox.showerror("GeoStudio — konfiguracja", str(error), parent=root)
        root.destroy()
        return None
    vault = WindowsSessionVault(client.config.project_id) if os.name == "nt" else None
    window = LoginWindow(root, client, vault, force_prompt=force_prompt, version=current_version())
    root.mainloop()
    return window.result
