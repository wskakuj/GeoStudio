"""Small native sign-in dialog, before starting the local editor server."""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

from .firebase_auth import AccessGate, AuthDenied, AuthError, FirebaseClient, load_config
from .firebase_vault import WindowsSessionVault


def run_login(force_prompt=False):
    import tkinter as tk
    from tkinter import messagebox, ttk
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
    root.title("GeoStudio 2.0 — Logowanie")
    root.configure(background="#101720")
    root.resizable(False, False)
    # Size to the controls after layout, including Windows display scaling.
    root.minsize(440, 400)
    panel = tk.Frame(root, background="#101720", padx=30, pady=20)
    panel.pack(fill="both", expand=True)
    try:
        icon = tk.PhotoImage(file=str(Path(__file__).parent / "static" / "geostudio-icon.png"))
        icon = icon.subsample(max(1, icon.width() // 48))
        root.iconphoto(True, icon)
        tk.Label(panel, image=icon, background="#101720").pack()
    except tk.TclError:
        pass
    tk.Label(panel, text="GeoStudio 2.0", font=("Segoe UI", 20, "bold"),
             fg="#e9eff7", bg="#101720").pack(pady=(0, 3))
    tk.Label(panel, text="Zaloguj się, aby otworzyć edytor map", font=("Segoe UI", 10),
             fg="#a5b2c4", bg="#101720").pack(pady=(0, 18))
    form = tk.Frame(panel, bg="#172230", padx=17, pady=15,
                    highlightthickness=1, highlightbackground="#35485e")
    form.pack(fill="x")
    email = tk.StringVar()
    password = tk.StringVar()
    remember = tk.BooleanVar(value=False)

    def field(label, var, show=None):
        tk.Label(form, text=label, fg="#e9eff7", bg="#172230",
                 font=("Segoe UI", 10)).pack(anchor="w")
        line = tk.Frame(form, bg="#0e1824", highlightthickness=1,
                        highlightbackground="#35485e")
        line.pack(fill="x", pady=(3, 10))
        entry = tk.Entry(line, textvariable=var, show=show or "", width=27,
                         font=("Segoe UI", 11), bg="#0e1824", fg="#e9eff7",
                         insertbackground="#e9eff7", disabledbackground="#0e1824",
                         disabledforeground="#a5b2c4", bd=0, relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(10, 4))
        entry.bind("<FocusIn>", lambda _: line.configure(highlightbackground="#3978e5"))
        entry.bind("<FocusOut>", lambda _: line.configure(highlightbackground="#35485e"))
        return entry, line

    email_entry, _ = field("Adres e-mail", email)
    password_entry, password_line = field("Hasło", password, "•")
    revealed = False

    def toggle_password():
        nonlocal revealed
        revealed = not revealed
        password_entry.configure(show="" if revealed else "•")
        eye.configure(text="Ukryj" if revealed else "👁 Pokaż")
        password_entry.focus_set()

    eye = tk.Button(password_line, text="👁 Pokaż", command=toggle_password,
                    font=("Segoe UI", 9), fg="#9cbfff", bg="#0e1824",
                    activebackground="#35485e", activeforeground="white",
                    relief="flat", padx=6, bd=0)
    eye.pack(side="right", padx=(0, 4))
    keep = tk.Checkbutton(form, text="Zapamiętaj mnie na tym komputerze",
                          variable=remember, bg="#172230", fg="#e9eff7",
                          activebackground="#172230", activeforeground="#e9eff7",
                          selectcolor="#25364b", anchor="w")
    keep.pack(fill="x")
    if vault is None:
        keep.configure(state="disabled")
    message = tk.StringVar()
    tk.Label(form, textvariable=message, fg="#f0c482", bg="#172230",
             justify="left", anchor="nw", wraplength=345,
             height=2, font=("Segoe UI", 9)).pack(fill="x", pady=(5, 4))
    progress = ttk.Progressbar(form, mode="indeterminate", length=300)

    pending = queue.Queue()
    result = []
    busy = False

    def launch(action, task, keep_session=False):
        nonlocal busy
        if busy:
            return
        busy = True
        email_entry.configure(state="disabled")
        password_entry.configure(state="disabled")
        eye.configure(state="disabled")
        submit.configure(state="disabled")
        reset.configure(state="disabled")
        keep.configure(state="disabled")
        message.set("Łączenie z Firebase…")
        progress.start(12)

        def worker():
            try:
                pending.put((action, task(), None, keep_session))
            except AuthError as error:
                pending.put((action, None, error, keep_session))
            except Exception:
                pending.put((action, None, AuthError("Nie udało się sprawdzić dostępu."), keep_session))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        nonlocal busy
        try:
            action, grant, error, keep_session = pending.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        busy = False
        progress.stop()
        if action in ("login", "restore") and error is None:
            gate = AccessGate(client, grant, vault, keep_session)
            if not gate.status()["active"]:
                error = AuthDenied("Sesja wygasła. Zaloguj się ponownie.")
            else:
                if gate.status()["storageWarning"]:
                    messagebox.showwarning("GeoStudio", gate.status()["storageWarning"], parent=root)
                result.append(gate)
                root.destroy()
                return
        if action == "restore" and isinstance(error, AuthDenied) and vault is not None:
            try:
                vault.clear()
            except OSError:
                pass
        email_entry.configure(state="normal")
        password_entry.configure(state="normal")
        eye.configure(state="normal")
        submit.configure(state="normal")
        reset.configure(state="normal")
        keep.configure(state="normal" if vault else "disabled")
        message.set(str(error) if error else
                    "Jeżeli konto istnieje, otrzymasz e-mail z instrukcją zmiany hasła.")
        root.after(100, poll)

    def submit_login():
        address, secret, keep_session = email.get(), password.get(), remember.get()
        password.set("")
        if revealed:
            toggle_password()
        launch("login", lambda: client.login(address, secret), keep_session)

    def reset_password():
        address = email.get()
        launch("reset", lambda: client.reset_password(address))

    submit = tk.Button(form, text="Zaloguj się", command=submit_login,
                       bg="#3978e5", fg="white", activebackground="#2864cf",
                       activeforeground="white", relief="flat", padx=16, pady=8,
                       font=("Segoe UI", 11, "bold"))
    submit.pack(fill="x")
    reset = tk.Button(form, text="Nie pamiętasz hasła?", command=reset_password,
                      fg="#8bb5ff", bg="#172230", activebackground="#172230",
                      activeforeground="white", relief="flat")
    reset.pack(pady=(5, 0))
    progress.pack(fill="x", pady=(6, 0))
    tk.Label(panel, text="GeoStudio " + current_version() + "  ·  Dostęp dla uprawnionych",
             fg="#a5b2c4", bg="#101720", font=("Segoe UI", 9)).pack(pady=(10, 0))
    root.update_idletasks()
    width = max(440, root.winfo_reqwidth())
    height = max(460, root.winfo_reqheight())
    root.geometry("%dx%d+%d+%d" % (width, height,
                  max(0, (root.winfo_screenwidth()-width)//2),
                  max(0, (root.winfo_screenheight()-height)//2)))
    root.deiconify()
    root.bind("<Return>", lambda _event: submit_login() if not busy else None)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    email_entry.focus_set()
    if vault is not None and not force_prompt:
        try:
            token = vault.load()
            if token:
                remember.set(True)
                launch("restore", lambda: client.refresh(token), True)
        except (OSError, ValueError):
            message.set("Nie udało się odczytać zapamiętanej sesji. Zaloguj się ponownie.")
    root.after(100, poll)
    root.mainloop()
    return result[0] if result else None
