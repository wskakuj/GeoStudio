"""Separate, local administrator tool. Never bundled in the user EXE.

Uses Google IAM / Application Default Credentials, not a GeoStudio user's
Firebase ID token. Run only on a trusted administrator workstation.
"""
from __future__ import annotations

import argparse
import queue
import re
import secrets
import threading
from datetime import datetime, timezone


def parse_expiry(value):
    """Empty means unlimited; explicit UTC or timezone offset is required."""
    value = value.strip()
    if not value:
        return None
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Podaj datę i godzinę wraz ze strefą, np. 2027-01-31T23:59:00+01:00.")
    return date.astimezone(timezone.utc)


def policy_changes(old, *, email, name, notes, active, expires, limit, removed, offline=False):
    """Pure policy validation; applied transactionally to the current document."""
    if type(active) is not bool or type(limit) is not int or not 0 <= limit <= 20:
        raise ValueError("Limit komputerów musi wynosić 0–20.")
    if expires is not None and expires.tzinfo is None:
        raise ValueError("Termin musi mieć strefę czasową.")
    if type(offline) is not bool or (offline and not limit):
        raise ValueError("Tryb offline wymaga włączonego limitu komputerów.")
    existing = old.get("devices", [])
    if (not isinstance(existing, list)
            or any(not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{64}", item)
                   for item in existing)
            or len(existing) != len(set(existing))):
        raise ValueError("Nieprawidłowa lista komputerów. Sprawdź dokument w Firestore.")
    devices = [item for item in existing if item not in removed]
    if limit and len(devices) > limit:
        raise ValueError("Usuń zbędne komputery przed obniżeniem limitu.")
    return {"email": email, "name": name.strip()[:160], "notes": notes.strip()[:500],
            "active": active, "expiresAt": expires, "deviceLimit": limit,
            "devices": devices, "offlineHours": 72 if offline else 0}


class AdminStore:
    def __init__(self, project_id):
        import firebase_admin
        from firebase_admin import auth, firestore

        self.auth = auth
        self.firestore = firestore
        self.app = firebase_admin.initialize_app(options={"projectId": project_id})
        self.db = firestore.client(app=self.app)
        self.collection = self.db.collection("geostudio_access")

    def accounts(self):
        policies = {snap.id: snap.to_dict() or {} for snap in self.collection.stream()}
        rows = []
        for user in self.auth.list_users(app=self.app).iterate_all():
            policy = policies.get(user.uid)
            rows.append({"uid": user.uid, "email": user.email or "",
                         "name": user.display_name or "", "auth_disabled": user.disabled,
                         "policy": policy})
        return sorted(rows, key=lambda row: row["email"].casefold())

    def save(self, uid, *, name, notes, active, expires, limit, removed=(), offline=False):
        user = self.auth.get_user(uid, app=self.app)
        ref = self.collection.document(uid)

        @self.firestore.transactional
        def apply(transaction):
            current = ref.get(transaction=transaction).to_dict() or {}
            data = policy_changes(current, email=user.email or "", name=name,
                                  notes=notes, active=active, expires=expires,
                                  limit=limit, removed=removed, offline=offline)
            transaction.set(ref, data, merge=True)

        apply(self.db.transaction())

    def create(self, email):
        # Never choose or display a permanent password for another person.
        # New account stays blocked unless the Firestore grant succeeds.
        user = self.auth.create_user(email=email, password=secrets.token_urlsafe(32),
                                     app=self.app)
        try:
            self.save(user.uid, name="", notes="", active=True,
                      expires=None, limit=2)
        except Exception:
            raise ValueError("Konto Authentication utworzono, ale nie nadano dostępu. "
                             "Odśwież listę i ustaw uprawnienia dla tego konta.") from None
        return user.uid

    def reset_link(self, uid):
        user = self.auth.get_user(uid, app=self.app)
        if not user.email:
            raise ValueError("Konto nie ma adresu e-mail.")
        return self.auth.generate_password_reset_link(user.email, app=self.app)


def run_panel(project_id):
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk

    root = tk.Tk()
    root.title("GeoStudio — Administrator | " + project_id)
    root.geometry("1000x570")
    root.minsize(760, 420)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Zarządzanie dostępem do GeoStudio",
              font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Projekt: " + project_id + "  ·  Uprawnienia Google IAM",
              foreground="#627185").pack(anchor="w", pady=(2, 12))
    toolbar = ttk.Frame(frame)
    toolbar.pack(fill="x", pady=(0, 8))
    search = tk.StringVar()
    ttk.Entry(toolbar, textvariable=search, width=28).pack(side="left", padx=(0, 8))
    ttk.Label(toolbar, text="Szukaj e-mail / nazwa").pack(side="left")
    table_frame = ttk.Frame(frame)
    table_frame.pack(fill="both", expand=True)
    cols = ("email", "name", "state", "expiry", "devices")
    table = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
    for col, label, width in zip(cols,
                                 ("Adres e-mail", "Nazwa", "Dostęp", "Ważność (UTC)", "Komputery"),
                                 (240, 150, 140, 180, 95)):
        table.heading(col, text=label)
        table.column(col, width=width, minwidth=75, stretch=col in ("email", "name"))
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    table.tag_configure("blocked", foreground="#b04747")
    table.tag_configure("active", foreground="#207044")
    message = tk.StringVar(value="Łączenie z Firebase…")
    ttk.Label(frame, textvariable=message, wraplength=900).pack(fill="x", pady=(10, 0))

    store = None
    rows = []
    busy = False
    pending = queue.Queue()
    actions = []

    def submit(task, on_success):
        nonlocal busy
        if busy:
            return
        busy = True
        message.set("Łączenie z Firebase…")
        for button in actions:
            button.configure(state="disabled")

        def worker():
            try:
                pending.put((on_success, task(), None))
            except ValueError as exc:
                pending.put((on_success, None, str(exc)))
            except Exception:
                # Do not log request/credential/response details.
                pending.put((on_success, None,
                             "Operacja nie powiodła się. Sprawdź uprawnienia IAM, projekt i internet."))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        nonlocal busy
        try:
            callback, result, error = pending.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        busy = False
        for button in actions:
            button.configure(state="normal")
        if error:
            message.set(error)
            messagebox.showerror("GeoStudio — administrator", error, parent=root)
        else:
            callback(result)
        root.after(100, poll)

    def state(row):
        p = row["policy"]
        if row["auth_disabled"]:
            return "Auth wyłączone"
        if not p or p.get("active") is not True:
            return "Zablokowany"
        expiry = p.get("expiresAt")
        if expiry and expiry <= datetime.now(timezone.utc):
            return "Wygasł"
        return "Aktywny"

    def redraw(*_):
        chosen = table.selection()
        table.delete(*table.get_children())
        term = search.get().strip().casefold()
        for row in rows:
            p = row["policy"] or {}
            name = p.get("name") or row["name"]
            if term and term not in (row["email"] + " " + name).casefold():
                continue
            expiry = p.get("expiresAt")
            limit = p.get("deviceLimit", 0)
            count = len(p.get("devices", []))
            status = state(row)
            table.insert("", "end", iid=row["uid"], values=(
                row["email"], name, status,
                expiry.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if expiry else "Bezterminowo",
                f"{count}/{limit}" if limit else "Bez limitu"),
                tags=("active" if status == "Aktywny" else "blocked",))
        if chosen and table.exists(chosen[0]):
            table.selection_set(chosen[0])

    def loaded(result):
        nonlocal store, rows
        store, rows = result
        redraw()
        message.set(f"Użytkownicy: {len(rows)}   ·   Aktywni: {sum(state(r)=='Aktywny' for r in rows)}")

    def refresh():
        def task():
            backend = store or AdminStore(project_id)
            return backend, backend.accounts()
        submit(task, loaded)

    def selected():
        chosen = table.selection()
        if not chosen or store is None:
            messagebox.showinfo("GeoStudio", "Wybierz użytkownika z listy.", parent=root)
            return None
        return next((row for row in rows if row["uid"] == chosen[0]), None)

    def edit():
        row = selected()
        if not row:
            return
        p = row["policy"] or {}
        win = tk.Toplevel(root)
        win.title("Uprawnienia — " + row["email"])
        win.transient(root)
        win.grab_set()
        content = ttk.Frame(win, padding=18)
        content.pack(fill="both", expand=True)
        name = tk.StringVar(value=p.get("name", row["name"]))
        notes = tk.StringVar(value=p.get("notes", ""))
        expiry = p.get("expiresAt")
        expires = tk.StringVar(value=expiry.isoformat() if expiry else "")
        active = tk.BooleanVar(value=p.get("active", False))
        limit = tk.StringVar(value=str(p.get("deviceLimit", 0)))
        offline = tk.BooleanVar(value=p.get("offlineHours") == 72)
        def field(label, var):
            ttk.Label(content, text=label).pack(anchor="w")
            ttk.Entry(content, textvariable=var, width=56).pack(fill="x", pady=(2, 8))
        field("Nazwa", name)
        field("Opis (widoczny dla użytkownika własnego dokumentu)", notes)
        ttk.Checkbutton(content, text="Aktywny dostęp do GeoStudio", variable=active).pack(anchor="w", pady=6)
        field("Ważność ISO ze strefą (puste = bezterminowo)", expires)
        field("Limit komputerów (0 = bez limitu; 1–20)", limit)
        ttk.Checkbutton(content, text="Zezwól na 72 h pracy offline (wymaga podpisującej usługi)",
                        variable=offline).pack(anchor="w", pady=6)
        ttk.Label(content, text="Komputery — zaznacz te, które chcesz usunąć").pack(anchor="w")
        devices = list(p.get("devices", []))
        listing = tk.Listbox(content, selectmode="extended", height=min(6, max(2, len(devices))), width=64)
        for identifier in devices:
            listing.insert("end", identifier)
        listing.pack(fill="x", pady=(4, 8))
        ttk.Label(content, text="Usunięty komputer może zarejestrować się ponownie, jeśli jest wolne miejsce.",
                  wraplength=420).pack(anchor="w")

        def save():
            try:
                cap = int(limit.get())
                date = parse_expiry(expires.get())
                removed = tuple(devices[i] for i in listing.curselection())
                values = dict(name=name.get(), notes=notes.get(), active=active.get(),
                              expires=date, limit=cap, removed=removed, offline=offline.get())
                policy_changes(p, email=row["email"], **values)
            except ValueError as exc:
                messagebox.showerror("Nieprawidłowe ustawienia", str(exc), parent=win)
                return
            if removed and not messagebox.askyesno("Komputery", "Usunąć zaznaczone rejestracje?", parent=win):
                return
            win.destroy()
            submit(lambda: store.save(row["uid"], **values), lambda _: refresh())
        ttk.Button(content, text="Zapisz uprawnienia", command=save).pack(fill="x", pady=(10, 0))
        ttk.Button(content, text="Anuluj", command=win.destroy).pack(fill="x", pady=(4, 0))

    def create():
        if store is None:
            return
        email = simpledialog.askstring("Nowy użytkownik", "Adres e-mail:", parent=root)
        if not email or "@" not in email:
            return
        if not messagebox.askyesno("Nowe konto", "Utworzyć konto z limitem dwóch komputerów? "
                                   "Następnie wygeneruj link ustawienia hasła.", parent=root):
            return
        def created(_):
            messagebox.showinfo("GeoStudio", "Utworzono konto. Wygeneruj link ustawienia hasła.",
                                parent=root)
            refresh()
        submit(lambda: store.create(email.strip()), created)

    def reset():
        row = selected()
        if not row:
            return
        def show(link):
            # Sensitive bearer link: never print or persist it.
            if messagebox.askyesno("Link ustawienia hasła",
                                   "Skopiować jednorazowy link do schowka? "
                                   "Przekaż go wyłącznie właścicielowi konta.", parent=root):
                root.clipboard_clear()
                root.clipboard_append(link)
                message.set("Link skopiowany. Przekaż go bezpiecznie i wyczyść schowek.")
        submit(lambda: store.reset_link(row["uid"]), show)

    for label, fn in (("Odśwież", refresh), ("Nowe konto", create),
                      ("Uprawnienia", edit), ("Link hasła", reset)):
        button = ttk.Button(toolbar, text=label, command=fn)
        button.pack(side="right", padx=(5, 0))
        actions.append(button)
    search.trace_add("write", redraw)
    table.bind("<Double-1>", lambda _: edit() if not busy else None)
    root.after(100, poll)
    root.after(0, refresh)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="GeoStudio — oddzielny panel administratora")
    parser.add_argument("--project", required=True, help="Firebase Project ID")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project):
        parser.error("Nieprawidłowy identyfikator projektu.")
    run_panel(args.project)


if __name__ == "__main__":
    main()
