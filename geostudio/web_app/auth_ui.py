"""Lightweight native authentication UI.

Only small static icons use Pillow; surfaces and controls use native Tk/ttk.
The viewport has a fixed width and a one-way content layout.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk, ImageOps

BG = "#0B111C"
CARD = "#151F2E"
FIELD = "#0F1826"
BORDER = "#2D3C50"
INK = "#F2F6FC"
MUTED = "#A5B5CA"
LINK = "#8CB8FF"
BLUE = "#326DE3"
FOCUS = "#79ACFF"
DISABLED = "#697A90"
INFO_BG, INFO_EDGE, INFO_INK = "#142D47", "#294E75", "#B6D7FF"
ERROR_BG, ERROR_EDGE, ERROR_INK = "#34222D", "#75404C", "#FFD0D5"
SUCCESS_BG, SUCCESS_EDGE, SUCCESS_INK = "#17352E", "#2B6653", "#A9E9CB"
WARN_BG, WARN_EDGE, WARN_INK = "#362D22", "#735A33", "#FFE0A6"


class Theme:
    """One local image/style registry per Tk interpreter."""
    def __init__(self, root):
        self.root = root
        self.scale = max(.75, min(3.0, root.winfo_fpixels("1i") / 96.0))
        self.family = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self.images = {}
        self._button_styles()
        self._checkbox_style()
        self.style.configure("GS.Vertical.TScrollbar", background=BORDER,
                             troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                             relief="flat", arrowsize=self.dp(10))

    def dp(self, x):
        return max(1, round(x*self.scale)) if x else 0

    def font(self, size=10, bold=False):
        return (self.family, size, "bold") if bold else (self.family, size)

    def label(self, parent, text="", *, size=10, bold=False, fg=INK,
              bg=CARD, wrap=354, **kwargs):
        return tk.Label(parent, text=text, font=self.font(size, bold),
                        fg=fg, bg=bg, wraplength=self.dp(wrap) if wrap else 0,
                        justify="left", anchor="w", borderwidth=0, **kwargs)

    def _button_styles(self):
        # The standard clam TButton draws its own flat surface. Do not
        # introduce stretched image elements or custom geometry managers.
        palettes = {
            "Primary": (BLUE, "#255BCB", "#417DF0", "#243953", "#5489F0", "#FFFFFF"),
            "Secondary": ("#1C2A3D", "#152235", "#273C55", "#1C2838", BORDER, INK),
            "Link": (CARD, "#24354A", "#202E40", CARD, CARD, LINK),
            "Eye": (FIELD, "#23354C", "#1C2C40", FIELD, FIELD, LINK),
        }
        for kind, (fill, press, hover, disabled, edge, fg) in palettes.items():
            name="GS."+kind+".TButton"
            padding=(self.dp(14),self.dp(10)) if kind in ("Primary","Secondary") else (
                self.dp(7),self.dp(5))
            self.style.configure(name,background=fill,foreground=fg,
                bordercolor=edge,lightcolor=fill,darkcolor=fill,focuscolor=FOCUS,
                relief="flat",borderwidth=1,anchor="center",padding=padding,
                font=self.font(11 if kind in ("Primary","Secondary") else 9,kind=="Primary"))
            self.style.map(name,foreground=[("disabled",DISABLED)],
                background=[("disabled",disabled),("pressed",press),("active",hover)],
                lightcolor=[("disabled",disabled),("pressed",press),("active",hover)],
                darkcolor=[("disabled",disabled),("pressed",press),("active",hover)],
                bordercolor=[("disabled",disabled),("focus",FOCUS),("active",edge)],
                relief=[("pressed","flat"),("!pressed","flat")])

    def icon(self, name, size=18, color=MUTED):
        key = ("icon", name, size, color)
        if key in self.images:
            return self.images[key]
        dim = self.dp(size)
        aa = 4
        im = Image.new("RGBA", (dim*aa, dim*aa))
        draw = ImageDraw.Draw(im)
        def xy(points):
            return [(round(x*dim*aa/24), round(y*dim*aa/24)) for x,y in points]
        stroke = max(1, round(dim*aa*1.65/24))
        def line(points):
            draw.line(xy(points), fill=color, width=stroke, joint="curve")
        def ellipse(box, fill=None):
            p = xy([(box[0],box[1]),(box[2],box[3])])
            draw.ellipse((*p[0],*p[1]), fill=fill, outline=color, width=stroke)
        def rounded(box, radius=2):
            p = xy([(box[0],box[1]),(box[2],box[3])])
            draw.rounded_rectangle((*p[0],*p[1]), radius=round(radius*dim*aa/24),
                                   outline=color, width=stroke)
        if name == "mail":
            rounded((2.5,5,21.5,19)); line([(3,6.5),(12,13),(21,6.5)])
        elif name == "lock":
            rounded((5,10,19,21)); line([(8,10),(8,6),(10,3),(14,3),(16,6),(16,10)])
            line([(12,14),(12,17)])
        elif name == "key":
            ellipse((2.5,3,13,13.5)); line([(11,12),(21,22),(22,18),(19,15),(16,18)])
        elif name in ("eye","eye-off"):
            line([(2,12),(5,8),(9,6),(15,6),(19,8),(22,12),(19,16),(15,18),(9,18),(5,16),(2,12)])
            ellipse((9,9,15,15))
            if name == "eye-off": line([(3,3),(21,21)])
        elif name == "check":
            line([(4,12),(9,17),(20,6)])
        elif name == "shield":
            line([(12,2),(21,6),(20,13),(17,18),(12,22),(7,18),(4,13),(3,6),(12,2)])
            line([(8,12),(11,15),(16,9)])
        elif name == "arrow":
            line([(4,12),(20,12)]); line([(14,6),(20,12),(14,18)])
        elif name == "layers":
            line([(12,3),(22,8),(12,13),(2,8),(12,3)])
            line([(2,12),(12,17),(22,12)]); line([(2,16),(12,21),(22,16)])
        elif name == "alert":
            ellipse((3,3,21,21)); line([(12,7),(12,12)]); ellipse((11.3,15,12.7,16.4),color)
        elif name == "info":
            ellipse((3,3,21,21)); line([(12,11),(12,17)]); ellipse((11.3,7,12.7,8.4),color)
        else:
            raise ValueError("Unknown auth icon")
        self.images[key] = ImageTk.PhotoImage(
            im.resize((dim,dim),Image.Resampling.LANCZOS),master=self.root)
        return self.images[key]

    def logo(self):
        key = "brand-logo"
        if key not in self.images:
            try:
                source = Path(__file__).parent / "static" / "geostudio-icon.png"
                with Image.open(source) as im:
                    icon = ImageOps.contain(im.convert("RGBA"), (self.dp(34),self.dp(34)),
                                            Image.Resampling.LANCZOS)
                self.images[key] = ImageTk.PhotoImage(icon,master=self.root)
            except (OSError,ValueError):
                self.images[key] = self.icon("layers",32,LINK)
        return self.images[key]

    def _checkbox_style(self):
        # Retain native checkbox semantics, focus and keyboard navigation.
        name="GS.TCheckbutton"
        self.style.configure(name,background=CARD,foreground=INK,
            font=self.font(9),padding=(self.dp(2),self.dp(4)),
            indicatorbackground=FIELD,indicatorforeground=INK,
            indicatorcolor=FIELD,focuscolor=FOCUS,bordercolor=BORDER)
        self.style.map(name,foreground=[("disabled",DISABLED)],
            background=[("active",CARD)],
            indicatorbackground=[("disabled",CARD),("selected",BLUE)],
            indicatorcolor=[("disabled",CARD),("selected",BLUE)])

    def button(self,parent,text,command,kind="Primary",**kwargs):
        return ttk.Button(parent,text=text,command=command,style="GS."+kind+".TButton",
                          takefocus=True,**kwargs)

    def checkbox(self,parent,text,variable):
        return ttk.Checkbutton(parent,text="  "+text,variable=variable,
                               style="GS.TCheckbutton",takefocus=True)


def theme_for(window):
    root=window._root()
    theme=getattr(root,"_geostudio_auth_theme",None)
    if theme is None:
        theme=Theme(root)
        root._geostudio_auth_theme=theme
    return theme


class Surface(tk.Frame):
    """Flat native surface; changing focus changes a single border color."""
    def __init__(self,parent,theme,*,fill=CARD,border=BORDER,padx=22,pady=20):
        super().__init__(parent,bg=fill,bd=0,highlightthickness=theme.dp(1),
                         highlightbackground=border,highlightcolor=border)
        self.theme=theme
        self.fill,self.border=fill,border
        self.inner=tk.Frame(self,bg=fill,bd=0,highlightthickness=0)
        self.inner.pack(fill="both",expand=True,padx=theme.dp(padx),pady=theme.dp(pady))

    def recolor(self,fill=None,border=None):
        if fill is not None and fill!=self.fill:
            self.fill=fill
            self.configure(bg=fill)
            self.inner.configure(bg=fill)
        if border is not None and border!=self.border:
            self.border=border
            self.configure(highlightbackground=border,highlightcolor=border)


class Field(tk.Frame):
    """Native text entry and a cheap focus border, with no text-change callbacks."""
    def __init__(self,parent,theme,label,variable,*,icon,placeholder="",secret=False):
        super().__init__(parent,bg=CARD,bd=0)
        self.theme,self.variable,self.secret=theme,variable,secret
        self.revealed=False
        theme.label(self,label,size=10,bold=True).pack(fill="x",pady=(0,theme.dp(6)))
        self.surface=Surface(self,theme,fill=FIELD,border=BORDER,padx=11,pady=7)
        self.surface.pack(fill="x")
        row=self.surface.inner
        tk.Label(row,image=theme.icon(icon,18),bg=FIELD,bd=0).pack(
            side="left",padx=(0,theme.dp(9)))
        self.entry=tk.Entry(row,textvariable=variable,show="•" if secret else "",
                            font=theme.font(11),bg=FIELD,fg=INK,insertbackground=INK,
                            disabledbackground=FIELD,disabledforeground=DISABLED,
                            selectbackground=BLUE,selectforeground="white",
                            relief="flat",bd=0,highlightthickness=0,width=17,
                            exportselection=False)
        self.entry.pack(side="left",fill="x",expand=True,ipady=theme.dp(5))
        self.eye=None
        if secret:
            self.eye=theme.button(row,"Pokaż",self.toggle,"Eye",
                                  image=theme.icon("eye",16,LINK),compound="left",width=9)
            self.eye.pack(side="right",padx=(theme.dp(4),0))
            self.eye.bind("<FocusIn>",self._focus,add="+")
            self.eye.bind("<FocusOut>",self._focus,add="+")
        # Labels above each field identify it. Avoid an overlaid placeholder,
        # variable traces and place/pack interaction during editing.
        self.entry.bind("<FocusIn>",self._focus,add="+")
        self.entry.bind("<FocusOut>",self._focus,add="+")
    def _focus(self,event):
        self.surface.recolor(border=FOCUS if event.type==tk.EventType.FocusIn else BORDER)

    def toggle(self):
        if not self.secret:return
        self.revealed=not self.revealed
        self.entry.configure(show="" if self.revealed else "•")
        self.eye.configure(text="Ukryj" if self.revealed else "Pokaż",
                           image=self.theme.icon("eye-off" if self.revealed else "eye",16,LINK))
    def mask(self):
        if self.revealed:self.toggle()
    def set_enabled(self,enabled):
        state="normal" if enabled else "disabled"
        if self.entry.cget("state")!=state:self.entry.configure(state=state)
        if self.eye is not None and str(self.eye.cget("state"))!=state:self.eye.configure(state=state)
    def focus(self):
        self.entry.focus_set()


class Notice(Surface):
    def __init__(self,parent,theme):
        super().__init__(parent,theme,fill=INFO_BG,border=INFO_EDGE,padx=10,pady=9)
        self.icon_label=tk.Label(self.inner,bg=INFO_BG,bd=0)
        self.icon_label.pack(side="left",anchor="n",padx=(0,theme.dp(8)))
        self.text=theme.label(self.inner,fg=INFO_INK,bg=INFO_BG,wrap=316,size=9)
        self.text.pack(side="left",fill="x",expand=True)
        self._notice_key=None
    def show(self,text,kind="info",*,before=None):
        key=(text,kind,before)
        if key==self._notice_key:return
        self._notice_key=key
        if not text:
            self.pack_forget()
            return
        fill,edge,ink,icon={
            "info":(INFO_BG,INFO_EDGE,INFO_INK,"info"),
            "error":(ERROR_BG,ERROR_EDGE,ERROR_INK,"alert"),
            "success":(SUCCESS_BG,SUCCESS_EDGE,SUCCESS_INK,"check"),
            "warning":(WARN_BG,WARN_EDGE,WARN_INK,"alert"),
        }[kind]
        self.recolor(fill,border=edge)
        self.icon_label.configure(bg=fill,image=self.theme.icon(icon,18,ink))
        self.text.configure(text=text,bg=fill,fg=ink)
        args={"fill":"x","pady":(0,self.theme.dp(12))}
        if before is not None:args["before"]=before
        self.pack(**args)


class Progress(tk.Canvas):
    def __init__(self,parent,theme):
        super().__init__(parent,height=theme.dp(3),bg=FIELD,bd=0,highlightthickness=0)
        self.theme=theme
        self.bar=self.create_rectangle(0,0,0,theme.dp(3),fill=FOCUS,width=0)
        self.job=None
        self.phase=0
    def start(self,*,before=None):
        if self.job is not None:return
        args={"fill":"x","pady":(0,self.theme.dp(10))}
        if before is not None:args["before"]=before
        self.pack(**args)
        self.phase=0
        self._animate()
    def _animate(self):
        w=max(1,self.winfo_width())
        part=max(self.theme.dp(22),w//4)
        x=self.phase%(w+part)-part
        self.coords(self.bar,x,0,x+part,self.theme.dp(3))
        self.phase+=self.theme.dp(10)
        self.job=self.after(45,self._animate)
    def stop(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job=None
        self.pack_forget()


def dark_titlebar(window):
    """Keep the native Windows frame (drag, close, accessibility); dark if supported."""
    if os.name!="nt":return
    try:
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        user32.GetAncestor.argtypes=(wintypes.HWND,wintypes.UINT)
        user32.GetAncestor.restype=wintypes.HWND
        hwnd=user32.GetAncestor(window.winfo_id(),2) or window.winfo_id()
        setter=ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes=(wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD)
        setter.restype=ctypes.c_long
        enabled=ctypes.c_int(1)
        for attribute in (20,19):
            if setter(hwnd,attribute,ctypes.byref(enabled),ctypes.sizeof(enabled))==0:
                break
    except (OSError,AttributeError,tk.TclError):
        pass


class Shell:
    """Consistent brand, card, footer and scrolling for login and registration."""
    def __init__(self,window,version="",*,privacy=False):
        self.window=window
        self.theme=t=theme_for(window)
        self._fit_job=None
        self._size=None
        self._scrolling=False
        self._scrollregion=None
        self._titlebar_applied=False
        self._closed=False
        window.configure(bg=BG)
        window.resizable(False,False)
        self.viewport=tk.Frame(window,bg=BG)
        self.viewport.pack(fill="both",expand=True)
        # Set the content width once. Reserve a scrollbar gutter regardless of
        # whether scrolling is needed. There is no canvas <Configure> binding
        # that resizes its embedded frame in response to geometry changes.
        self.scroll=ttk.Scrollbar(self.viewport,orient="vertical",style="GS.Vertical.TScrollbar")
        gutter=max(t.dp(14),self.scroll.winfo_reqwidth())
        screen_w=window.winfo_screenwidth()
        self._width=min(t.dp(448)+gutter,max(200,screen_w-t.dp(30)))
        content_width=max(1,self._width-gutter)
        self.viewport.grid_columnconfigure(0,weight=1)
        self.viewport.grid_columnconfigure(1,minsize=gutter)
        self.viewport.grid_rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(self.viewport,width=content_width,height=1,bg=BG,
                              highlightthickness=0,bd=0)
        self.scroll.configure(command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0,column=0,sticky="nsew")
        self.scroll.grid(row=0,column=1,sticky="ns")
        self.scroll.grid_remove()
        self.body=tk.Frame(self.canvas,bg=BG,padx=t.dp(20),pady=t.dp(17))
        self.body_id=self.canvas.create_window(0,0,window=self.body,anchor="nw",
                                               width=content_width)
        self.body.bind("<Configure>",self._body_changed,add="+")
        window.bind("<Map>",self._on_map,add="+")
        window.bind("<Destroy>",self._on_destroy,add="+")
        window.bind("<MouseWheel>",self._wheel,add="+")
        window.bind("<Button-4>",lambda _:self._scroll(-1),add="+")
        window.bind("<Button-5>",lambda _:self._scroll(1),add="+")
        window.bind("<FocusIn>",self._focus_visible,add="+")
        brand=tk.Frame(self.body,bg=BG)
        brand.pack(fill="x",pady=(0,t.dp(17)))
        self.brand_logo=t.logo()
        tk.Label(brand,image=self.brand_logo,bg=BG,bd=0).pack(side="left",padx=(0,t.dp(11)))
        names=tk.Frame(brand,bg=BG)
        names.pack(side="left",fill="x",expand=True)
        t.label(names,"GeoStudio",size=17,bold=True,bg=BG).pack(fill="x")
        t.label(names,"2.0  /  Edytor map",size=9,fg=MUTED,bg=BG).pack(fill="x")
        tk.Label(brand,image=t.icon("shield",20,LINK),bg=BG,bd=0).pack(side="right")
        try:window.iconphoto(True,self.brand_logo)
        except tk.TclError:pass
        card=Surface(self.body,t,padx=22,pady=21)
        card.pack(fill="x")
        self.card=card.inner
        self.stage=tk.Frame(self.card,bg=CARD)
        self.step_label=t.label(self.stage,"",size=9,bold=True,fg=LINK)
        self.step_label.pack(side="left",fill="x")
        self.dots=[]
        for _ in range(2):
            dot=tk.Frame(self.stage,bg=BORDER,width=t.dp(25),height=t.dp(4))
            dot.pack(side="right",padx=(t.dp(4),0))
            self.dots.insert(0,dot)
        self.heading_label=t.label(self.card,"",size=21,bold=True)
        self.heading_label.pack(fill="x")
        self.desc_label=t.label(self.card,"",fg=MUTED,size=10)
        self.desc_label.pack(fill="x",pady=(t.dp(4),t.dp(19)))
        self.content=tk.Frame(self.card,bg=CARD)
        self.content.pack(fill="x")
        foot=tk.Frame(self.body,bg=BG)
        foot.pack(fill="x",pady=(t.dp(14),0))
        version_text="GeoStudio "+version if version else "GeoStudio 2.0"
        t.label(foot,version_text+"  ·  Dostęp dla uprawnionych",
                size=9,fg=MUTED,bg=BG).pack(fill="x")
        if privacy:
            t.label(foot,"Usługa zapisuje czas połączeń, ID i nazwę komputera. "
                    "Mapy oraz ścieżki plików pozostają lokalne.",size=8,fg=MUTED,bg=BG,
                    wrap=390).pack(fill="x",pady=(t.dp(4),0))
    def heading(self,title,description,step=None):
        self.heading_label.configure(text=title)
        self.desc_label.configure(text=description)
        if step is None:self.stage.pack_forget()
        else:
            self.step_label.configure(text="KROK %d Z 2"%step)
            for i,dot in enumerate(self.dots):dot.configure(bg=BLUE if i<step else BORDER)
            self.stage.pack(fill="x",pady=(0,self.theme.dp(10)),before=self.heading_label)
    def _scroll(self,direction):
        if self.scroll.winfo_ismapped():
            self.canvas.yview_scroll(direction,"units")
            return "break"
    def _wheel(self,event):
        return self._scroll(-1 if event.delta>0 else 1)
    def _focus_visible(self,event):
        if not self.scroll.winfo_ismapped():return
        widget=event.widget
        try:
            if not str(widget).startswith(str(self.body)+"."):return
            total=self.body.winfo_height()
            y=widget.winfo_rooty()-self.body.winfo_rooty()
            top=self.canvas.canvasy(0)
            height=self.canvas.winfo_height()
            bottom=y+widget.winfo_height()
            if y<top:self.canvas.yview_moveto(max(0,y-self.theme.dp(12))/max(total,1))
            elif bottom>top+height:self.canvas.yview_moveto(max(0,bottom-height+self.theme.dp(12))/max(total,1))
        except tk.TclError:pass
    def _body_changed(self,event):
        # The embedded frame follows its children's natural height only.
        # Update the scroll range without changing the frame's dimensions.
        bounds=(0,0,event.width,event.height)
        if bounds!=self._scrollregion:
            self._scrollregion=bounds
            self.canvas.configure(scrollregion=bounds)
            if self._size is not None:
                self.request_fit()

    def _on_map(self,event):
        if event.widget is self.window and not self._titlebar_applied:
            self._titlebar_applied=True
            dark_titlebar(self.window)

    def _on_destroy(self,event):
        if event.widget is self.window:
            self._closed=True
            if self._fit_job is not None:
                self.window.after_cancel(self._fit_job)
                self._fit_job=None

    def request_fit(self):
        """One deferred layout measurement, never a nested Tk event loop."""
        if not self._closed and self._fit_job is None:
            self._fit_job=self.window.after_idle(self._fit_requested)

    def _fit_requested(self):
        self._fit_job=None
        if not self._closed:
            self._fit()

    def fit(self):
        # Called at initial construction, before the window is mapped.
        # Do not call update/update_idletasks from subsequent UI callbacks.
        if self._size is None:
            self.window.update_idletasks()
        self._fit()

    def _fit(self):
        w=self.window;t=self.theme
        ideal_height=self.body.winfo_reqheight()
        screen_w,screen_h=w.winfo_screenwidth(),w.winfo_screenheight()
        limit_h=max(150,screen_h-t.dp(90))
        has_scroll=ideal_height>limit_h
        if has_scroll!=self._scrolling:
            self._scrolling=has_scroll
            if has_scroll:
                self.scroll.grid()
            else:
                self.scroll.grid_remove()
                self.canvas.yview_moveto(0)
        width=self._width
        height=min(limit_h,max(t.dp(160),ideal_height))
        size=(width,height)
        if size!=self._size:
            if self._size is None:
                x,y=max(0,(screen_w-width)//2),max(0,(screen_h-height)//2)
            else:
                x=max(0,min(w.winfo_x(),screen_w-width))
                y=max(0,min(w.winfo_y(),screen_h-height-t.dp(40)))
            self._size=size
            w.geometry("%dx%d+%d+%d"%(width,height,x,y))


def selftest_widgets():
    """Frozen-runtime check: no login, network, user credentials or editor."""
    root=None
    try:
        # Ensure both actual controller modules are importable in the bundle.
        from .firebase_login import LoginWindow
        from .firebase_registration import RegistrationWindow
        root=tk.Tk()
        root.withdraw()
        shell=Shell(root,"diagnostic")
        shell.heading("Test", "Diagnostic only", 1)
        theme=shell.theme
        variable=tk.StringVar(master=root,value="synthetic")
        field=Field(shell.content,theme,"Password",variable,icon="lock",secret=True)
        field.pack(fill="x")
        button=theme.button(shell.content,"Continue",lambda:None)
        button.pack(fill="x")
        theme.checkbox(shell.content,"Remember",tk.BooleanVar(master=root)).pack()
        notice=Notice(shell.content,theme)
        notice.show("Test","success",before=button)
        root.update_idletasks()
        if not field.entry.cget("show"):
            return False
        field.toggle()
        if field.entry.cget("show") or variable.get()!="synthetic":
            return False
        field.mask()
        return bool(field.entry.cget("show") and button.winfo_reqwidth()>0
                    and theme.style.layout("GS.Primary.TButton")
                    and LoginWindow and RegistrationWindow)
    except Exception:
        return False
    finally:
        if root is not None:
            root.destroy()
