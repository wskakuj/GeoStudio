"""Two-step registration wizard using the same design as the sign-in window."""
from __future__ import annotations

import queue
import threading
import time

from .firebase_auth import AuthError


class RegistrationWindow:
    def __init__(self, root, client, initial_email="", *, version=""):
        import tkinter as tk
        from tkinter import ttk
        from .auth_ui import CARD, FIELD, BORDER, LINK, MUTED, Field, Notice, Progress, RoundedPanel, Shell

        self.client = client
        self.win = win = tk.Toplevel(root)
        win.withdraw()
        win.title("GeoStudio — Utwórz konto")
        win.transient(root)
        self.shell = Shell(win, version)
        t = self.shell.theme
        self.shell.heading("Utwórz konto", "Wprowadź dane i kod otrzymany od administratora.", 1)
        self.email = tk.StringVar(master=win, value=initial_email)
        self.password = tk.StringVar(master=win)
        self.code = tk.StringVar(master=win)
        self.recipient = tk.StringVar(master=win)
        self.busy = False
        self.page = "form"
        self.session = None
        self.result = None
        self.sent_at = None
        self.poll_id = None
        self.resend_id = None
        self.pending = queue.Queue()
        content = self.shell.content
        self.pages = tk.Frame(content, bg=CARD)
        self.pages.pack(fill="x")
        self.form = tk.Frame(self.pages, bg=CARD)
        self.form.pack(fill="x")
        self.verify = tk.Frame(self.pages, bg=CARD)
        self.email_field = Field(self.form,t,"Adres e-mail",self.email,
                                 icon="mail",placeholder="nazwa@domena.pl")
        self.email_field.pack(fill="x",pady=(0,t.dp(14)))
        self.password_field = Field(self.form,t,"Hasło",self.password,
                                    icon="lock",placeholder="Ustaw hasło",secret=True)
        self.password_field.pack(fill="x",pady=(0,t.dp(4)))
        t.label(self.form,"Co najmniej 12 znaków",size=9,fg=MUTED).pack(
            fill="x",pady=(0,t.dp(13)))
        self.code_field = Field(self.form,t,"Kod zaproszenia",self.code,
                                icon="key",placeholder="Wklej otrzymany kod")
        self.code_field.pack(fill="x",pady=(0,t.dp(18)))
        self.fields = (self.email_field,self.password_field,self.code_field)

        illustration = RoundedPanel(self.verify,t,fill="#1C3454",border="#315780",
                                    outer=CARD,radius=18,padx=15,pady=13)
        illustration.pack(anchor="center",pady=(0,t.dp(18)))
        tk.Label(illustration.inner,image=t.icon("mail",36,LINK),bg="#1C3454",bd=0).pack()
        recipient = RoundedPanel(self.verify,t,fill=FIELD,border=BORDER,outer=CARD,
                                 radius=10,padx=13,pady=10)
        recipient.pack(fill="x",pady=(0,t.dp(14)))
        t.label(recipient.inner,"Twój adres e-mail",size=9,fg=MUTED,bg=FIELD).pack(fill="x")
        t.label(recipient.inner,"",size=11,bold=True,bg=FIELD,wrap=319,
                textvariable=self.recipient).pack(fill="x",pady=(t.dp(3),0))
        t.label(self.verify,"Kliknij link w wiadomości, a następnie wróć tutaj. "
                "Sprawdź też folder spam.",fg=MUTED).pack(fill="x",pady=(0,t.dp(18)))
        self.notice = Notice(content,t)
        self.progress = Progress(content,t)
        self.primary = t.button(content,"Utwórz konto",self.primary_action)
        self.primary.pack(fill="x")
        self.resend = t.button(content,"Nie dotarł e-mail? Wyślij ponownie",
                               lambda:self.launch("resend"),"Link")
        self.back = t.button(content,"Wróć do logowania",self.close,"Link")
        self.back.pack(anchor="center",pady=(t.dp(9),0))

        def enter(event):
            if isinstance(event.widget, ttk.Button) and event.widget is not self.primary:
                event.widget.invoke()
            else:
                self.primary_action()
            return "break"
        win.bind("<Return>",enter)
        win.bind("<Escape>",lambda _:self.close() or "break")
        win.protocol("WM_DELETE_WINDOW",self.close)
        self.shell.fit()
        win.deiconify()
        win.grab_set()
        self.email_field.focus()

    def show_notice(self,text="",kind="info"):
        self.notice.show(text,kind,before=self.primary)
        self.shell.request_fit()

    def refresh_controls(self):
        for field in self.fields:
            field.set_enabled(not self.busy)
        state="disabled" if self.busy else "normal"
        self.primary.configure(state=state)
        self.back.configure(state=state)
        if self.page=="verify":
            self.update_resend()

    def update_resend(self):
        if self.resend_id is not None:
            self.win.after_cancel(self.resend_id)
            self.resend_id=None
        wait=0 if self.sent_at is None else max(0,30-int(time.monotonic()-self.sent_at))
        can_resend=not self.busy and not wait and not (self.session and self.session.email_verified)
        text=("Nie dotarł e-mail? Wyślij ponownie" if not wait else "Wyślij ponownie za %d s"%wait)
        if self.resend.cget("text")!=text:self.resend.configure(text=text)
        state="normal" if can_resend else "disabled"
        if str(self.resend.cget("state"))!=state:self.resend.configure(state=state)
        # Only the actual resend countdown needs an idle timer.
        if wait and not self.busy and not (self.session and self.session.email_verified):
            self.resend_id=self.win.after(1000,self._resend_tick)

    def _resend_tick(self):
        self.resend_id=None
        self.update_resend()

    def primary_action(self):
        self.launch("begin" if self.page=="form" else "finish")

    def launch(self,action):
        if self.busy:
            return
        if action=="begin":
            address,secret,invitation=self.email.get(),self.password.get(),self.code.get()
            try:
                self.client._registration_input(address,secret,invitation)
            except AuthError as error:
                self.show_notice(str(error),"error")
                return
            self.password.set("")
            self.password_field.mask()
            task=lambda:self.client.begin_registration(address,secret,invitation)
        else:
            if self.session is None:
                return
            task=(lambda:self.client.finish_registration(self.session)) if action=="finish" else (
                lambda:self.client.resend_registration(self.session))
        self.busy=True
        self.notice.show("")
        self.primary.configure(text={"begin":"Tworzenie konta…","finish":"Sprawdzanie e-maila…",
                                     "resend":"Wysyłanie wiadomości…"}[action])
        self.refresh_controls()
        self.progress.start(before=self.primary)
        self.shell.request_fit()

        def worker():
            try:
                self.pending.put((action,task(),None))
            except AuthError as error:
                self.pending.put((action,None,str(error)))
            except Exception:
                self.pending.put((action,None,"Nie udało się wykonać operacji. Spróbuj ponownie."))
        threading.Thread(target=worker,daemon=True,name="GeoStudioRegistration").start()
        self.poll_id=self.win.after(40,self.poll)

    def show_verification(self):
        self.page="verify"
        self.form.pack_forget()
        self.verify.pack(fill="x")
        self.shell.heading("Potwierdź e-mail","Ostatni krok przed rozpoczęciem pracy w GeoStudio.",2)
        self.recipient.set(self.session.email)
        self.code.set("")
        self.primary.configure(text="Potwierdziłem e-mail")
        self.resend.pack(fill="x",pady=(self.shell.theme.dp(5),0),before=self.back)
        if self.session.email_verified:
            self.show_notice("Adres jest już potwierdzony. Kliknij, aby zakończyć rejestrację.","success")
        elif self.session.email_sent:
            self.sent_at=time.monotonic()
            self.show_notice("Link został wysłany.","success")
        else:
            self.show_notice("Konto utworzono, ale wysyłka linku nie została potwierdzona. "
                             "Wyślij go ponownie.","warning")
        self.refresh_controls()
        self.primary.focus_set()

    def poll(self):
        self.poll_id=None
        try:
            action,data,error=self.pending.get_nowait()
        except queue.Empty:
            self.poll_id=self.win.after(40,self.poll)
            return
        else:
            self.busy=False
            self.progress.stop()
            self.primary.configure(text="Utwórz konto" if self.page=="form" else "Potwierdziłem e-mail")
            if error:
                self.refresh_controls()
                self.show_notice(error,"error")
                if self.page=="form":self.password_field.focus()
            elif action=="begin":
                self.session=data
                self.show_verification()
            elif action=="resend":
                self.session=data
                if self.session.email_verified:
                    self.show_notice("Adres jest już potwierdzony. Kliknij, aby zakończyć.","success")
                else:
                    self.sent_at=time.monotonic()
                    self.show_notice("Link wysłano ponownie.","success")
                self.refresh_controls()
            elif action=="finish":
                if data.get("pending"):
                    info="Konto oczekuje na akceptację administratora."
                elif data.get("active"):
                    info="Konto gotowe! Zaloguj się."
                else:
                    info="Konto nie ma aktywnego dostępu. Skontaktuj się z administratorem."
                self.result=(self.session.email,info)
                self.close()
                return

    def close(self):
        if self.busy:
            return
        if self.session is not None:
            if self.result is None:
                self.result=(self.session.email,"Aby wznowić rejestrację, wybierz Utwórz konto.")
            self.session.clear()
            self.session=None
        self.password.set("")
        self.code.set("")
        self.progress.stop()
        if self.poll_id is not None:
            self.win.after_cancel(self.poll_id)
            self.poll_id=None
        if self.resend_id is not None:
            self.win.after_cancel(self.resend_id)
            self.resend_id=None
        self.win.destroy()


def open_registration(root,client,initial_email="",*,version=""):
    window=RegistrationWindow(root,client,initial_email,version=version)
    root.wait_window(window.win)
    return window.result
