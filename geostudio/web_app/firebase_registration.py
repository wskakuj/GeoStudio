"""Modal registration window; Firebase email verification precedes access."""
from __future__ import annotations

import queue
import threading

from .firebase_auth import AuthError


def open_registration(root, client, initial_email=""):
    import tkinter as tk
    from tkinter import messagebox

    win = tk.Toplevel(root)
    win.title("GeoStudio — rejestracja z zaproszeniem")
    win.configure(bg="#101720")
    win.transient(root)
    win.resizable(False, False)
    win.grab_set()
    panel = tk.Frame(win, bg="#172230", padx=22, pady=20)
    panel.pack(fill="both", expand=True, padx=16, pady=16)
    tk.Label(panel, text="Utwórz konto GeoStudio", bg="#172230", fg="#e9eff7",
             font=("Segoe UI", 17, "bold")).pack(anchor="w")
    tk.Label(panel, text="1. Wpisz dane i kod, utwórz konto.\n"
             "2. Kliknij link w wiadomości weryfikacyjnej.\n"
             "3. Zakończ rejestrację. Kod musi być nadal ważny.",
             bg="#172230", fg="#a5b2c4", justify="left",
             wraplength=420, font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 14))
    email = tk.StringVar(value=initial_email)
    password = tk.StringVar()
    repeat = tk.StringVar()
    code = tk.StringVar()
    entries = []
    secret_entries = []

    def field(label, var, secret=False):
        tk.Label(panel, text=label, fg="#e9eff7", bg="#172230",
                 font=("Segoe UI", 10)).pack(anchor="w")
        entry = tk.Entry(panel, textvariable=var, show="•" if secret else "",
                         font=("Segoe UI", 11), bg="#0e1824", fg="#e9eff7",
                         disabledbackground="#0e1824", disabledforeground="#a5b2c4",
                         insertbackground="#e9eff7", relief="flat",
                         highlightthickness=1, highlightbackground="#35485e",
                         highlightcolor="#3978e5", width=39)
        entry.pack(fill="x", ipady=7, pady=(3, 10))
        entries.append(entry)
        if secret:
            secret_entries.append(entry)
        return entry

    first = field("Adres e-mail", email)
    field("Hasło (minimum 12 znaków)", password, True)
    field("Powtórz hasło (tylko przy tworzeniu konta)", repeat, True)
    field("Kod zaproszenia", code)
    reveal = tk.BooleanVar(value=False)

    def reveal_passwords():
        for entry in secret_entries:
            entry.configure(show="" if reveal.get() else "•")

    eye = tk.Checkbutton(panel, text="Pokaż hasła", variable=reveal,
                         command=reveal_passwords, bg="#172230", fg="#e9eff7",
                         selectcolor="#25364b", activebackground="#172230",
                         activeforeground="white")
    eye.pack(anchor="w")
    message = tk.StringVar(value="Nie masz kodu? Poproś administratora.")
    tk.Label(panel, textvariable=message, bg="#172230", fg="#f0c482",
             justify="left", anchor="nw", wraplength=420, height=3,
             font=("Segoe UI", 10)).pack(fill="x", pady=(6, 8))
    pending = queue.Queue()
    buttons = []
    busy = False
    result = ""

    def close():
        if busy:
            return
        password.set("")
        repeat.set("")
        code.set("")
        win.destroy()

    def launch(action):
        nonlocal busy
        if busy:
            return
        address, secret, invitation = email.get(), password.get(), code.get()
        try:
            client._registration_input(address, secret, invitation)
            if action == "create" and secret != repeat.get():
                raise AuthError("Hasła muszą być jednakowe.")
        except AuthError as error:
            message.set(str(error))
            return
        password.set("")
        repeat.set("")
        reveal.set(False)
        reveal_passwords()
        busy = True
        for widget in entries + buttons + [eye]:
            widget.configure(state="disabled")
        message.set("Łączenie z usługą…")

        def worker():
            try:
                operation = {"create": client.begin_registration,
                             "resend": client.resend_registration,
                             "finish": client.finish_registration}[action]
                pending.put((action, operation(address, secret, invitation), None))
            except AuthError as error:
                pending.put((action, None, str(error)))
            except Exception:
                pending.put((action, None, "Nie udało się wykonać operacji. Spróbuj ponownie."))
        threading.Thread(target=worker, daemon=True, name="GeoStudioRegistration").start()

    def poll():
        nonlocal busy, result
        try:
            action, data, error = pending.get_nowait()
        except queue.Empty:
            win.after(100, poll)
            return
        busy = False
        for widget in entries + buttons + [eye]:
            widget.configure(state="normal")
        if error:
            message.set(error)
        elif action == "finish":
            if data.get("pending"):
                info = "E-mail potwierdzony. Konto oczekuje na akceptację administratora."
            elif data.get("active"):
                info = "Rejestracja zakończona. Możesz zalogować się do GeoStudio."
            else:
                info = "Konto ma już uprawnienia, ale dostęp nie jest aktywny. Skontaktuj się z administratorem."
            result = email.get()
            messagebox.showinfo("GeoStudio", info, parent=win)
            close()
            return
        else:
            message.set("Wysłano link. Sprawdź pocztę (także spam), potwierdź e-mail, "
                        "wpisz hasło ponownie i zakończ rejestrację.")
        win.after(100, poll)

    def add_button(text, command, primary=False):
        button = tk.Button(panel, text=text, command=command, fg="white",
                           bg="#3978e5" if primary else "#25364b",
                           activebackground="#35485e", activeforeground="white",
                           relief="flat", pady=7, font=("Segoe UI", 10))
        button.pack(fill="x", pady=(0, 5))
        buttons.append(button)

    add_button("Utwórz konto i wyślij link", lambda: launch("create"), True)
    add_button("Wyślij link ponownie", lambda: launch("resend"))
    add_button("Potwierdziłem e-mail — zakończ rejestrację", lambda: launch("finish"), True)
    add_button("Wróć do logowania", close)
    win.protocol("WM_DELETE_WINDOW", close)
    win.update_idletasks()
    width, height = win.winfo_reqwidth(), win.winfo_reqheight()
    win.geometry("%dx%d+%d+%d" % (width, height,
                 max(0, (win.winfo_screenwidth()-width)//2),
                 max(0, (win.winfo_screenheight()-height)//2)))
    first.focus_set()
    win.bind("<Return>", lambda e: "break")
    win.after(100, poll)
    root.wait_window(win)
    return result
