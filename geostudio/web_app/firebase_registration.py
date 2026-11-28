"""A compact two-step registration wizard. No passwords or tokens on disk."""
from __future__ import annotations

import queue
import threading
import time

from .firebase_auth import AuthError

BG = "#101720"
PANEL = "#172230"
FIELD = "#0e1824"
INK = "#e9eff7"
MUTED = "#a5b2c4"
LINK = "#8bb5ff"
PRIMARY = "#3978e5"
BORDER = "#35485e"


def open_registration(root, client, initial_email=""):
    import tkinter as tk

    win = tk.Toplevel(root)
    win.title("GeoStudio — Utwórz konto")
    win.configure(bg=BG)
    win.transient(root)
    win.resizable(False, False)
    win.grab_set()
    panel = tk.Frame(win, bg=PANEL, padx=24, pady=20,
                     highlightthickness=1, highlightbackground=BORDER)
    panel.pack(fill="both", expand=True, padx=14, pady=14)
    stage_label = tk.StringVar(value="KROK 1 Z 2")
    title = tk.StringVar(value="Utwórz konto")
    description = tk.StringVar(value="Wprowadź dane i kod otrzymany od administratora.")
    tk.Label(panel, textvariable=stage_label, bg=PANEL, fg=LINK,
             font=("Segoe UI", 9, "bold")).pack(anchor="w")
    tk.Label(panel, textvariable=title, bg=PANEL, fg=INK,
             font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(3, 5))
    tk.Label(panel, textvariable=description, bg=PANEL, fg=MUTED,
             font=("Segoe UI", 10), wraplength=342,
             justify="left", anchor="w").pack(fill="x", pady=(0, 17))

    pages = tk.Frame(panel, bg=PANEL)
    pages.pack(fill="x")
    form = tk.Frame(pages, bg=PANEL)
    verify = tk.Frame(pages, bg=PANEL)
    form.pack(fill="x")
    email, password, code = tk.StringVar(value=initial_email), tk.StringVar(), tk.StringVar()
    message = tk.StringVar()
    recipient = tk.StringVar()
    entries = []
    shown = False
    busy = False
    page = "form"
    session = None
    result = None
    sent_at = None
    poll_id = None
    pending = queue.Queue()

    def field(label, var, secret=False):
        tk.Label(form, text=label, fg=INK, bg=PANEL,
                 font=("Segoe UI", 10)).pack(anchor="w")
        line = tk.Frame(form, bg=FIELD, highlightthickness=1,
                        highlightbackground=BORDER)
        line.pack(fill="x", pady=(4, 12))
        entry = tk.Entry(line, textvariable=var, show="•" if secret else "",
                         font=("Segoe UI", 11), bg=FIELD, fg=INK,
                         disabledbackground=FIELD, disabledforeground=MUTED,
                         insertbackground=INK, relief="flat", bd=0, width=30)
        entry.pack(side="left", fill="x", expand=True, padx=(10, 5), ipady=7)
        entry.bind("<FocusIn>", lambda _: line.configure(highlightbackground=PRIMARY))
        entry.bind("<FocusOut>", lambda _: line.configure(highlightbackground=BORDER))
        entries.append(entry)
        return entry, line

    first, _ = field("Adres e-mail", email)
    password_entry, password_line = field("Hasło", password, True)

    def toggle_password():
        nonlocal shown
        shown = not shown
        password_entry.configure(show="" if shown else "•")
        eye.configure(text="Ukryj" if shown else "Pokaż")
        password_entry.focus_set()

    eye = tk.Button(password_line, text="Pokaż", command=toggle_password,
                    bg=FIELD, fg=LINK, disabledforeground=MUTED,
                    activebackground=BORDER, activeforeground="white",
                    font=("Segoe UI", 9), relief="flat", bd=0, padx=6)
    eye.pack(side="right", padx=(0, 4))
    tk.Label(form, text="Co najmniej 12 znaków", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 9))
    field("Kod zaproszenia", code)
    tk.Label(verify, text="Wiadomość weryfikacyjna", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 10)).pack(anchor="w")
    tk.Label(verify, textvariable=recipient, bg=FIELD, fg=INK, padx=12, pady=11,
             wraplength=324, justify="left", anchor="w",
             font=("Segoe UI", 11, "bold")).pack(fill="x", pady=(5, 14))
    tk.Label(verify, text="Otwórz wiadomość i kliknij link potwierdzający. "
             "Następnie wróć tutaj. Sprawdź również folder spam.",
             bg=PANEL, fg=MUTED, wraplength=342, justify="left",
             anchor="w", font=("Segoe UI", 10)).pack(fill="x")

    status = tk.Label(panel, textvariable=message, bg=PANEL, fg="#f0c482",
                      wraplength=342, justify="left", anchor="nw",
                      font=("Segoe UI", 9))
    # Do not reserve a large blank error box before the first interaction.
    def notice(text="", error=False):
        message.set(text)
        status.configure(fg="#f0c482" if error else MUTED)
        if text:
            status.pack(fill="x", pady=(3, 10), before=primary)
        else:
            status.pack_forget()

    def center():
        win.update_idletasks()
        width = max(390, win.winfo_reqwidth())
        height = win.winfo_reqheight()
        win.geometry("%dx%d+%d+%d" % (width, height,
                     max(0, (win.winfo_screenwidth()-width)//2),
                     max(0, (win.winfo_screenheight()-height)//2)))

    def close():
        nonlocal result, session, poll_id
        if busy:
            return
        if session is not None:
            if result is None:
                result = (session.email, "Aby wznowić rejestrację, wybierz Utwórz konto.")
            session.clear()
            session = None
        password.set("")
        code.set("")
        if poll_id is not None:
            win.after_cancel(poll_id)
            poll_id = None
        win.destroy()

    def refresh_controls():
        state = "disabled" if busy else "normal"
        for widget in entries + [eye, primary, back]:
            widget.configure(state=state)
        if page == "verify":
            wait = 0 if sent_at is None else max(0, 30-int(time.monotonic()-sent_at))
            can_resend = not busy and not wait and not (session and session.email_verified)
            resend.configure(state="normal" if can_resend else "disabled",
                             text=("Nie dotarł e-mail? Wyślij ponownie"
                                   if not wait else "Wyślij ponownie za %d s" % wait))

    def show_verification():
        nonlocal page, sent_at
        page = "verify"
        form.pack_forget()
        verify.pack(fill="x")
        stage_label.set("KROK 2 Z 2")
        title.set("Potwierdź e-mail")
        description.set("Ostatni krok przed rozpoczęciem pracy w GeoStudio.")
        recipient.set(session.email)
        code.set("")
        primary.configure(text="Potwierdziłem e-mail")
        resend.pack(fill="x", pady=(5, 0), before=back)
        if session.email_verified:
            notice("Adres jest już potwierdzony. Kliknij, aby zakończyć rejestrację.")
        elif session.email_sent:
            sent_at = time.monotonic()
            notice("Link został wysłany.")
        else:
            notice("Konto utworzono, ale wysyłka linku nie została potwierdzona. Wyślij go ponownie.", True)
        refresh_controls()
        primary.focus_set()
        center()

    def launch(action):
        nonlocal busy
        if busy:
            return
        if action == "begin":
            address, secret, invitation = email.get(), password.get(), code.get()
            try:
                client._registration_input(address, secret, invitation)
            except AuthError as error:
                notice(str(error), True)
                center()
                return
            password.set("")
            if shown:
                toggle_password()
            task = lambda: client.begin_registration(address, secret, invitation)
        else:
            if session is None:
                return
            task = (lambda: client.finish_registration(session)) if action == "finish" else (
                lambda: client.resend_registration(session))
        busy = True
        refresh_controls()
        notice("Łączenie z usługą…")
        center()

        def worker():
            try:
                pending.put((action, task(), None))
            except AuthError as error:
                pending.put((action, None, str(error)))
            except Exception:
                pending.put((action, None, "Nie udało się wykonać operacji. Spróbuj ponownie."))
        threading.Thread(target=worker, daemon=True, name="GeoStudioRegistration").start()

    def primary_action():
        launch("begin" if page == "form" else "finish")

    primary = tk.Button(panel, text="Utwórz konto", command=primary_action,
                        bg=PRIMARY, fg="white", activebackground="#2864cf",
                        activeforeground="white", disabledforeground=MUTED,
                        relief="flat", padx=12, pady=9,
                        font=("Segoe UI", 11, "bold"))
    primary.pack(fill="x")
    resend = tk.Button(panel, text="Nie dotarł e-mail? Wyślij ponownie",
                       command=lambda: launch("resend"), bg=PANEL, fg=LINK,
                       activebackground=PANEL, activeforeground="white",
                       disabledforeground=MUTED, relief="flat", bd=0,
                       font=("Segoe UI", 9))
    back = tk.Button(panel, text="Wróć do logowania", command=close,
                     bg=PANEL, fg=LINK, activebackground=PANEL,
                     activeforeground="white", disabledforeground=MUTED,
                     relief="flat", bd=0, font=("Segoe UI", 10))
    back.pack(pady=(8, 0))

    def poll():
        nonlocal busy, session, result, sent_at, poll_id
        poll_id = None
        try:
            action, data, error = pending.get_nowait()
        except queue.Empty:
            refresh_controls()
        else:
            busy = False
            if error:
                notice(error, True)
                refresh_controls()
                center()
                if page == "form":
                    password_entry.focus_set()
            elif action == "begin":
                session = data
                show_verification()
            elif action == "resend":
                session = data
                if session.email_verified:
                    notice("Adres jest już potwierdzony. Kliknij, aby zakończyć.")
                else:
                    sent_at = time.monotonic()
                    notice("Link wysłano ponownie.")
                refresh_controls()
                center()
            elif action == "finish":
                if data.get("pending"):
                    info = "Konto oczekuje na akceptację administratora."
                elif data.get("active"):
                    info = "Konto gotowe! Zaloguj się."
                else:
                    info = "Konto nie ma aktywnego dostępu. Skontaktuj się z administratorem."
                result = (session.email, info)
                close()
                return
        poll_id = win.after(150, poll)

    win.protocol("WM_DELETE_WINDOW", close)
    def enter(_event):
        primary_action()
        return "break"
    def escape(_event):
        close()
        return "break"
    win.bind("<Return>", enter)
    win.bind("<Escape>", escape)
    center()
    first.focus_set()
    poll_id = win.after(150, poll)
    root.wait_window(win)
    return result
