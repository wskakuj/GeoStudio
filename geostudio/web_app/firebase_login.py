"""Small native sign-in dialog, before starting the local editor server."""
from __future__ import annotations

import os
import queue
import threading
from pathlib import Path

from .firebase_auth import AccessGate, AuthDenied, AuthError, FirebaseClient, load_config
from .firebase_vault import WindowsSessionVault


def run_login():
    import tkinter as tk
    from tkinter import messagebox, ttk

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
    root.geometry("440x460")
    root.update_idletasks()
    root.geometry("+%d+%d" % (max(0, (root.winfo_screenwidth()-440)//2),
                              max(0, (root.winfo_screenheight()-460)//2)))
    root.deiconify()
    panel = tk.Frame(root, background="#101720", padx=36, pady=25)
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
    email = tk.StringVar()
    password = tk.StringVar()
    remember = tk.BooleanVar(value=False)

    def field(label, var, show=None):
        tk.Label(panel, text=label, fg="#e9eff7", bg="#101720").pack(anchor="w")
        entry = ttk.Entry(panel, textvariable=var, show=show or "")
        entry.pack(fill="x", ipady=5, pady=(3, 10))
        return entry

    email_entry = field("Adres e-mail", email)
    password_entry = field("Hasło", password, "•")
    keep = tk.Checkbutton(panel, text="Zapamiętaj mnie na tym komputerze",
                          variable=remember, bg="#101720", fg="#e9eff7",
                          activebackground="#101720", activeforeground="#e9eff7",
                          selectcolor="#25364b", anchor="w")
    keep.pack(fill="x")
    if vault is None:
        keep.configure(state="disabled")
    message = tk.StringVar()
    tk.Label(panel, textvariable=message, fg="#f0c482", bg="#101720",
             justify="left", wraplength=355).pack(fill="x", pady=(8, 6))

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
        submit.configure(state="disabled")
        reset.configure(state="disabled")
        keep.configure(state="disabled")
        message.set("Łączenie z Firebase…")

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
        submit.configure(state="normal")
        reset.configure(state="normal")
        keep.configure(state="normal" if vault else "disabled")
        message.set(str(error) if error else
                    "Jeżeli konto istnieje, otrzymasz e-mail z instrukcją zmiany hasła.")
        root.after(100, poll)

    def submit_login():
        address, secret, keep_session = email.get(), password.get(), remember.get()
        password.set("")
        launch("login", lambda: client.login(address, secret), keep_session)

    def reset_password():
        address = email.get()
        launch("reset", lambda: client.reset_password(address))

    submit = tk.Button(panel, text="Zaloguj się", command=submit_login,
                       bg="#3978e5", fg="white", activebackground="#2864cf",
                       activeforeground="white", relief="flat", padx=16, pady=8,
                       font=("Segoe UI", 11, "bold"))
    submit.pack(fill="x")
    reset = tk.Button(panel, text="Nie pamiętasz hasła?", command=reset_password,
                      fg="#8bb5ff", bg="#101720", activebackground="#101720",
                      activeforeground="white", relief="flat")
    reset.pack(pady=(7, 0))
    root.bind("<Return>", lambda _event: submit_login() if not busy else None)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    email_entry.focus_set()
    if vault is not None:
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
