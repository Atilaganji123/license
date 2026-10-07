# -*- coding: utf-8 -*-
"""
FAST OCR 8 - Grid Finder
- F7: select the whole game panel once
- F8: scan
- Finds the LARGE 8-digit target at the top, not a random grid row
- Splits target into 4 pairs
- Finds those pairs in the grid
- Draws hollow boxes directly on matching grid numbers
- Boxes automatically disappear after 10 seconds
- Pressing F8 replaces the old boxes immediately
"""

import os
import re
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
import math
import json
import time
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont

import cv2
import mss
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageTk
import pytesseract
import keyboard

# ======================================================================
#  نصب خودکار OCR (Tesseract)
# ======================================================================
import os
import shutil
import hashlib
import threading
import subprocess
import urllib.request
import zipfile
import tkinter as tk
from tkinter import ttk, messagebox


# ----------------------------------------------------------------------
#  تنظیمات — لینک مستقیم فایل را اینجا بگذار
# ----------------------------------------------------------------------
# لینک مستقیم (HTTPS) به فایل نصب (.exe) یا نسخه‌ی پرتابل (.zip)
TESSERACT_URL = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
# اختیاری ولی توصیه می‌شود: هش SHA256 فایل (برای اطمینان از سالم بودن دانلود)
TESSERACT_SHA256 = ""

APP_DIR = os.path.join(os.path.expanduser("~"), "FastOCR8")
TESS_DIR = os.path.join(APP_DIR, "Tesseract-OCR")


# ----------------------------------------------------------------------
#  پیدا کردن Tesseract
# ----------------------------------------------------------------------
def find_tesseract():
    fixed = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        shutil.which("tesseract") or "",
    ]
    for p in fixed:
        if p and os.path.exists(p):
            return p
    # نسخه‌ای که خود برنامه نصب کرده (ممکن است داخل زیرپوشه باشد)
    for folder, _dirs, files in os.walk(TESS_DIR):
        if "tesseract.exe" in files:
            return os.path.join(folder, "tesseract.exe")
    return None


# ----------------------------------------------------------------------
#  دانلود
# ----------------------------------------------------------------------
def _download(url, dest, state, cancel):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        state["total"] = int(r.headers.get("Content-Length") or 0)
        while True:
            if cancel.is_set():
                raise RuntimeError("دانلود لغو شد.")
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            state["got"] += len(chunk)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------
#  نصب
# ----------------------------------------------------------------------
def _run_elevated_and_wait(exe, params):
    """اجرای installer با دسترسی ادمین (UAC) و صبر تا پایان نصب."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    k32 = ctypes.windll.kernel32
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x00000040          # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = 0                   # SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise RuntimeError("اجازه‌ی نصب (UAC) داده نشد.")
    k32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD(0)
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    if code.value != 0:
        raise RuntimeError(f"نصب Tesseract ناموفق بود (کد {code.value}).")


def _install(path):
    os.makedirs(TESS_DIR, exist_ok=True)
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            z.extractall(TESS_DIR)
    else:
        # NSIS: /S = بی‌صدا ، /D باید آخرین پارامتر و بدون گیومه باشد
        _run_elevated_and_wait(path, "/S /D=" + TESS_DIR)


# ----------------------------------------------------------------------
#  تابع اصلی
# ----------------------------------------------------------------------
def ensure_tesseract(theme=None, parent=None):
    """اگر Tesseract نصب نباشد دانلود و نصبش می‌کند. True = آماده است."""
    p = find_tesseract()
    if p:
        pytesseract.pytesseract.tesseract_cmd = p
        return True

    if not TESSERACT_URL.lower().startswith("http"):
        messagebox.showerror("Tesseract", "لینک دانلود Tesseract تنظیم نشده است.", parent=parent)
        return False

    c = theme or {"bg": "#071426", "panel": "#0b1d33", "text": "#f3f8ff",
                  "muted": "#91abc5", "accent": "#19aaff"}
    st = {"got": 0, "total": 0, "phase": "download", "err": None, "done": False}
    cancel = threading.Event()

    def work():
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            ext = ".zip" if TESSERACT_URL.lower().split("?")[0].endswith(".zip") else ".exe"
            dest = os.path.join(APP_DIR, "tesseract_setup" + ext)
            _download(TESSERACT_URL, dest, st, cancel)
            if TESSERACT_SHA256 and _sha256(dest) != TESSERACT_SHA256.strip().lower():
                os.remove(dest)
                raise RuntimeError("فایل دانلودشده سالم نیست (SHA256 نمی‌خواند).")
            st["phase"] = "install"
            _install(dest)
            if not find_tesseract():
                raise RuntimeError("نصب انجام شد ولی tesseract.exe پیدا نشد.")
            try:
                os.remove(dest)
            except Exception:
                pass
        except Exception as e:
            st["err"] = str(e) or e.__class__.__name__
        finally:
            st["done"] = True

    own = parent is None
    root = tk.Tk() if own else tk.Toplevel(parent)
    if not own:
        root.attributes("-topmost", True)
    root.title("نصب OCR")
    root.configure(bg=c["bg"])
    root.resizable(False, False)
    w, h = 440, 170
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")

    lbl = tk.Label(root, text="در حال دانلود موتور OCR ...", bg=c["bg"], fg=c["text"],
                   font=("Segoe UI", 11, "bold"))
    lbl.pack(pady=(22, 8))
    bar = ttk.Progressbar(root, length=380, mode="determinate", maximum=100)
    bar.pack()
    sub = tk.Label(root, text="", bg=c["bg"], fg=c["muted"], font=("Segoe UI", 9))
    sub.pack(pady=6)

    def on_cancel():
        cancel.set()
        root.destroy()

    btn = tk.Button(root, text="لغو", command=on_cancel, bg=c["accent"], fg="#06101b",
                    relief="flat", bd=0, padx=16, pady=4, font=("Segoe UI", 9, "bold"),
                    cursor="hand2")
    btn.pack()
    root.protocol("WM_DELETE_WINDOW", on_cancel)

    def poll():
        if st["done"]:
            root.destroy()
            return
        if st["phase"] == "download":
            if st["total"]:
                pct = st["got"] * 100 / st["total"]
                bar.configure(mode="determinate", value=pct)
                sub.configure(text=f"{st['got'] / 1048576:.1f} / {st['total'] / 1048576:.1f} MB")
            else:
                sub.configure(text=f"{st['got'] / 1048576:.1f} MB")
        else:
            lbl.configure(text="در حال نصب ... (اگر پنجره‌ی UAC آمد، Yes بزن)")
            bar.configure(mode="indeterminate")
            bar.start(15)
            sub.configure(text="")
            btn.configure(state="disabled")
            st["phase"] = "installing"
        root.after(120, poll)

    threading.Thread(target=work, daemon=True).start()
    root.after(120, poll)
    if own:
        root.mainloop()
    else:
        root.wait_window(root)

    if st["err"] and not cancel.is_set():
        messagebox.showerror("Tesseract", st["err"], parent=parent)
        return False

    p = find_tesseract()
    if p:
        pytesseract.pytesseract.tesseract_cmd = p
        return True
    return False





APP_DIR = os.path.join(os.path.expanduser("~"), "FastOCR8")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

DEFAULT_SCAN_KEY = "f4"
DEFAULT_SELECT_KEY = "f7"
BOX_SECONDS = 10.0
DEBUG_SAVE = True          # saves last_capture.png / last_processed.png in ~/FastOCR8 for troubleshooting
UI_SCALE = 1.0             # 1.0 = default size (700x470). e.g. 0.9 smaller, 1.2 bigger
TRACK_MOVEMENT = True      # boxes follow the moving numbers
TRACK_INTERVAL_MS = 30
LICENSE_CHECK_MS = 15_000   # هر ۱۵ ثانیه لایسنس (و لیست ابطال) چک می‌شود
# True: numbers form one continuous "snake" in reading order. A number that leaves
# the LEFT side of a row re-enters at the RIGHT side of the row above it, and a
# number leaving the top row re-enters at the bottom-right of the grid.
WRAP_ROWS_CHAIN = True

# Common Windows installation path.
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

for p in TESSERACT_CANDIDATES:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break
_found = find_tesseract()
if _found:
    pytesseract.pytesseract.tesseract_cmd = _found


def load_config():
    os.makedirs(APP_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "region": None,
        "scan_key": DEFAULT_SCAN_KEY,
        "theme": "blue",
    }


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class RegionSelector:
    def __init__(self, callback):
        self.callback = callback
        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        self.root.attributes("-alpha", 0.25)

        self.canvas = tk.Canvas(
            self.root, bg="black", highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.down)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.up)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.canvas.create_text(
            20, 20,
            anchor="nw",
            fill="white",
            text="کل پنل بازی را انتخاب کن — ESC برای لغو",
            font=("Segoe UI", 16, "bold"),
        )

    def down(self, e):
        self.start_x = e.x
        self.start_y = e.y
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            e.x, e.y, e.x, e.y,
            outline="#00ffff", width=3
        )

    def move(self, e):
        if self.rect:
            self.canvas.coords(
                self.rect, self.start_x, self.start_y, e.x, e.y
            )

    def up(self, e):
        x1, y1 = self.start_x, self.start_y
        x2, y2 = e.x, e.y

        left = min(x1, x2)
        top = min(y1, y2)
        width = abs(x2 - x1)
        height = abs(y2 - y1)

        if width >= 100 and height >= 100:
            self.callback({
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
            })

        self.root.destroy()


class BoxOverlay:
    """Transparent full-screen overlay. Boxes vanish automatically."""

    def __init__(self):
        self.root = None
        self.lock = threading.Lock()
        self.wrap = None

    def show(self, boxes, seconds=10.0, color="#00ffff"):
        self.color = color
        self.wrap = None
        # GUI work must happen on Tk's main thread, so this method is called
        # through the main application's root.after().
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

        if not boxes:
            return

        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(
            f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0"
        )

        # Magenta is made transparent by Windows/Tk.
        transparent = "#ff00ff"
        self.root.configure(bg=transparent)
        try:
            self.root.wm_attributes("-transparentcolor", transparent)
        except Exception:
            # Fallback: still make the window mostly transparent.
            self.root.attributes("-alpha", 0.95)

        canvas = tk.Canvas(
            self.root,
            bg=transparent,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)

        # Hollow boxes only. No filled rectangle.
        self.canvas = canvas
        self.base = [dict(b) for b in boxes]
        self.items = []
        for b in boxes:
            self.items.append(canvas.create_rectangle(
                b["x1"], b["y1"], b["x2"], b["y2"],
                outline=getattr(self, "color", "#00ffff"),
                width=3,
            ))

        self.root.after(int(seconds * 1000), self.hide)

    def set_wrap(self, fn):
        self.wrap = fn

    def move(self, dx, dy, clip=None):
        """Shift all boxes by (dx, dy) from their original position.
        If a wrap function is set, each box centre is wrapped around the grid
        (left edge -> right edge of the row above, top row -> bottom row)."""
        if self.root is None:
            return
        for item, b in zip(self.items, self.base):
            hw = (b["x2"] - b["x1"]) / 2.0
            hh = (b["y2"] - b["y1"]) / 2.0
            cx = (b["x1"] + b["x2"]) / 2.0 + dx
            cy = (b["y1"] + b["y2"]) / 2.0 + dy
            if self.wrap is not None:
                cx, cy = self.wrap(cx, cy)
            x1, y1, x2, y2 = cx - hw, cy - hh, cx + hw, cy + hh
            self.canvas.coords(item, x1, y1, x2, y2)
            visible = True
            if clip is not None:
                visible = x2 > clip[0] and x1 < clip[2] and y2 > clip[1] and y1 < clip[3]
            self.canvas.itemconfigure(item, state="normal" if visible else "hidden")

    def place(self, centers, clip=None):
        """Put each box at an absolute screen centre (per-box tracking)."""
        if self.root is None:
            return
        for item, b, (cx, cy) in zip(self.items, self.base, centers):
            hw = (b["x2"] - b["x1"]) / 2.0
            hh = (b["y2"] - b["y1"]) / 2.0
            x1, y1, x2, y2 = cx - hw, cy - hh, cx + hw, cy + hh
            self.canvas.coords(item, x1, y1, x2, y2)
            visible = True
            if clip is not None:
                visible = x2 > clip[0] and x1 < clip[2] and y2 > clip[1] and y1 < clip[3]
            self.canvas.itemconfigure(item, state="normal" if visible else "hidden")

    def hide(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None


# ======================================================================
#  Graphics (Pillow) — anti-aliased neon/glass rendering
# ======================================================================
SS = 3     # supersampling for the window base
CSS = 2    # supersampling for cards

THEME_DOTS = ["#19aaff", "#b84cff", "#ffd21c", "#20e58a"]


def rgb(h):
    if not isinstance(h, str):
        return tuple(h)
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mixc(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# ----------------------------------------------------------------------
#  Layout (all numbers are scaled by S, so one constant resizes the app)
# ----------------------------------------------------------------------
def layout(S=1.0):
    f = lambda v: int(round(v * S))

    def bx(*v):
        return tuple(f(i) for i in v)

    L = {"S": S, "W": f(700), "H": f(470), "cut": f(24)}
    L["tab"] = [(f(20), f(14)), (f(300), f(14)), (f(334), f(50)), (f(20), f(50))]
    L["logo"] = (f(50), f(32))
    L["title_xy"] = (f(82), f(32))
    L["btn"] = {"min": (f(588), f(32)), "pin": (f(620), f(32)), "close": (f(652), f(32))}
    L["lp"] = bx(22, 60, 292, 408)
    L["rp"] = bx(300, 60, 678, 408)
    L["cards"] = [
        ("region", bx(30, 68, 284, 122)),
        ("ocr", bx(30, 130, 284, 184)),
        ("keys", bx(30, 192, 284, 246)),
        ("set", bx(30, 254, 284, 308)),
        ("theme", bx(30, 316, 284, 400)),
    ]
    L["rc"] = (f(489), f(238))
    L["rtitle"] = (f(489), f(90))
    L["rdiv"] = (f(338), f(112), f(640), f(112))
    L["result"] = (f(489), f(238))
    L["status"] = (f(489), f(300))
    L["footer"] = (f(30), f(434))
    return L


def card_points(box, kind, S):
    """Absolute pixel positions of a card's content."""
    x1, y1, x2, y2 = box
    cy = (y1 + y2) / 2
    P = {
        "icon": (x1 + 34 * S, cy if kind != "theme" else y1 + 46 * S),
        "text_x": x1 + 68 * S,
        "title_y": cy - 10 * S,
        "sub_y": cy + 10 * S,
        "chev": (x2 - 22 * S, cy),
        "badge": (x2 - 66 * S, cy - 14 * S, x2 - 10 * S, cy + 14 * S),
    }
    if kind == "theme":
        P["label"] = (x1 + 68 * S, y1 + 16 * S)
        P["dots"] = [(x1 + (86 + 42 * i) * S, y1 + 44 * S) for i in range(4)]
        P["names_y"] = y1 + 68 * S
    return P


# ----------------------------------------------------------------------
#  small drawing helpers
# ----------------------------------------------------------------------
def chamfer_pts(x1, y1, x2, y2, c):
    return [(x1 + c, y1), (x2 - c, y1), (x2, y1 + c), (x2, y2 - c),
            (x2 - c, y2), (x1 + c, y2), (x1, y2 - c), (x1, y1 + c)]


def _closed(d, pts, fill, width):
    pts = list(pts)
    d.line(pts + [pts[0], pts[1]], fill=fill, width=width, joint="curve")


def _capline(d, pts, fill, w):
    d.line(pts, fill=fill, width=int(round(w)), joint="curve")
    r = w / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _disc(d, cx, cy, r, **kw):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)


# ---- icons (u = pixels per design unit) ---------------------------------
def icon_region(d, cx, cy, u, col, col2):
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        _capline(d, [(cx + sx * 15 * u, cy + sy * 8 * u), (cx + sx * 15 * u, cy + sy * 15 * u),
                     (cx + sx * 8 * u, cy + sy * 15 * u)], col, 2.8 * u)
    _disc(d, cx, cy, 3.4 * u, fill=col2)
    _disc(d, cx, cy, 7.5 * u, outline=col + (120,), width=int(1.2 * u))


def icon_ocr(d, cx, cy, u, col, col2):
    _disc(d, cx, cy, 14 * u, outline=col, width=int(2.8 * u))
    _disc(d, cx, cy, 7.5 * u, outline=col2, width=int(2.2 * u))
    _disc(d, cx, cy, 2.8 * u, fill=col)
    for ang in (0, 90, 180, 270):
        a = math.radians(ang)
        _capline(d, [(cx + math.cos(a) * 17 * u, cy + math.sin(a) * 17 * u),
                     (cx + math.cos(a) * 21 * u, cy + math.sin(a) * 21 * u)], col2, 2.2 * u)


def icon_keyboard(d, cx, cy, u, col, col2):
    d.rounded_rectangle([cx - 20 * u, cy - 13 * u, cx + 20 * u, cy + 13 * u], radius=int(5 * u),
                        outline=col2, width=int(2.2 * u))
    for row, (yy, n, off) in enumerate(((-6, 5, 0), (-0.5, 4, 3.2))):
        for i in range(n):
            x = cx - 13.5 * u + (i * 6.8 + off) * u
            d.rounded_rectangle([x, cy + yy * u - 1.6 * u, x + 3.6 * u, cy + yy * u + 1.9 * u],
                                radius=int(0.9 * u), fill=col)
    d.rounded_rectangle([cx - 9 * u, cy + 5 * u, cx + 9 * u, cy + 8.5 * u], radius=int(1.5 * u), fill=col2)


def icon_download(d, cx, cy, u, col, col2):
    _capline(d, [(cx, cy - 15 * u), (cx, cy + 6 * u)], col, 3 * u)
    _capline(d, [(cx - 8 * u, cy - 2 * u), (cx, cy + 7 * u), (cx + 8 * u, cy - 2 * u)], col2, 3 * u)
    _capline(d, [(cx - 15 * u, cy + 10 * u), (cx - 15 * u, cy + 15 * u),
                 (cx + 15 * u, cy + 15 * u), (cx + 15 * u, cy + 10 * u)], col, 2.6 * u)


def icon_gear(d, cx, cy, u, col, col2, hole):
    n = 8
    pts = []
    ro, ri = 16 * u, 12 * u
    b = 2 * math.pi / n
    for k in range(n):
        a = k * b
        for r, da in ((ri, -0.5), (ro, -0.27), (ro, 0.27), (ri, 0.5)):
            pts.append((cx + math.cos(a + da * b) * r, cy + math.sin(a + da * b) * r))
    d.polygon(pts, fill=col)
    _disc(d, cx, cy, 6.2 * u, fill=hole)
    _disc(d, cx, cy, 6.2 * u, outline=col2, width=int(1.6 * u))
    _disc(d, cx, cy, 2.2 * u, fill=col2)


def icon_palette(d, cx, cy, u, col, hole, body):
    d.ellipse([cx - 18 * u, cy - 15 * u, cx + 18 * u, cy + 15 * u], fill=body, outline=col, width=int(2.2 * u))
    _disc(d, cx + 8 * u, cy + 7 * u, 4.4 * u, fill=hole, outline=col, width=int(1.4 * u))
    for (dx, dy), colr in zip(((-9, -2), (-3.5, -8), (4.5, -6.5), (-10, 6)), THEME_DOTS):
        _disc(d, cx + dx * u, cy + dy * u, 3.3 * u, fill=rgb(colr))


def icon_chevron(d, cx, cy, u, col):
    _capline(d, [(cx - 3.5 * u, cy - 7 * u), (cx + 3.5 * u, cy), (cx - 3.5 * u, cy + 7 * u)], col, 2.4 * u)


def icon_logo(d, cx, cy, u, c):
    R = 19 * u
    hexa = [(cx + math.cos(math.radians(30 + 60 * i)) * R, cy + math.sin(math.radians(30 + 60 * i)) * R)
            for i in range(6)]
    d.polygon(hexa, fill=rgb(c["accent"]))
    R2 = 15.5 * u
    hex2 = [(cx + math.cos(math.radians(30 + 60 * i)) * R2, cy + math.sin(math.radians(30 + 60 * i)) * R2)
            for i in range(6)]
    _closed(d, hex2, rgb(c["accent2"]) + (200,), int(1.2 * u))
    d.rounded_rectangle([cx - 11 * u, cy - 4.5 * u, cx + 11 * u, cy + 8 * u], radius=int(4 * u),
                        fill=rgb(c["bg"]))
    for dx in (-4.6, 4.6):
        _disc(d, cx + dx * u, cy + 1.6 * u, 2.5 * u, fill=rgb(c["accent2"]))
    # hood peak
    d.polygon([(cx - 6 * u, cy - 9 * u), (cx, cy - 15 * u), (cx + 6 * u, cy - 9 * u)],
              fill=mixc(c["accent"], "#ffffff", 0.25))


# ----------------------------------------------------------------------
#  window base
# ----------------------------------------------------------------------
def render_base(L, c, pinned=False):
    W, H, S, k = L["W"], L["H"], L["S"], SS
    yy = np.linspace(0, 1, H)[:, None]
    xx = np.linspace(0, 1, W)[None, :]
    bgc = np.array(rgb(c["bg"]), float)
    acc = np.array(rgb(c["accent"]), float)
    a = (0.12 * np.exp(-(((xx - 0.85) ** 2) / 0.10 + ((yy - 0.0) ** 2) / 0.22))
         + 0.06 * np.exp(-(((xx - 0.05) ** 2) / 0.18 + ((yy - 1.0) ** 2) / 0.18)))[..., None]
    base = Image.fromarray((bgc * (1 - a) + acc * a).astype(np.uint8), "RGB").convert("RGBA")

    ins = max(2, int(round(3 * S)))
    outer = chamfer_pts(ins, ins, W - ins, H - ins, L["cut"] - ins)
    inner_o = ins + int(round(7 * S))
    inner = chamfer_pts(inner_o, inner_o, W - inner_o, H - inner_o, max(6, L["cut"] - inner_o))

    # neon glow around the frame
    m = Image.new("L", (W * k, H * k), 0)
    _closed(ImageDraw.Draw(m), [(x * k, y * k) for x, y in outer], 255, int(5 * S * k))
    m = m.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(5 * S))
    glow = Image.new("RGBA", (W, H), rgb(c["accent"]) + (0,))
    glow.putalpha(m.point(lambda v: min(255, int(v * 0.9))))
    base = Image.alpha_composite(base, glow)

    lay = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    u = S * k

    def sc(pts):
        return [(x * k, y * k) for x, y in pts]

    _closed(d, sc(outer), rgb(c["accent"]) + (255,), max(2, int(2.2 * u)))
    _closed(d, sc(inner), mixc(c["accent"], c["bg"], 0.6) + (255,), max(1, int(1.1 * u)))

    # title tab
    d.polygon(sc(L["tab"]), fill=rgb(c["panel"]) + (255,))
    _closed(d, sc(L["tab"]), mixc(c["panel"], c["accent"], 0.55) + (255,), int(1.6 * u))

    # panels
    for box in (L["lp"], L["rp"]):
        d.rounded_rectangle([v * k for v in box], radius=int(14 * u), fill=rgb(c["panel"]) + (255,),
                            outline=rgb(c["border"]) + (255,), width=max(1, int(1.2 * u)))

    # decorative scanner rings in the status panel
    cx, cy = L["rc"]
    for r, al in ((104, 40), (74, 32), (44, 26)):
        _disc(d, cx * k, cy * k, r * u, outline=rgb(c["accent"]) + (al,), width=int(1.6 * u))
    for ang in range(0, 360, 90):
        aa = math.radians(ang + 45)
        _disc(d, (cx + math.cos(aa) * 104 * S) * k, (cy + math.sin(aa) * 104 * S) * k, 2.6 * u,
              fill=rgb(c["accent2"]) + (150,))

    # divider under the status title
    x1, y1, x2, _ = L["rdiv"]
    d.line([(x1 * k, y1 * k), (x2 * k, y1 * k)], fill=rgb(c["accent"]) + (150,), width=int(1.6 * u))
    _disc(d, ((x1 + x2) / 2) * k, y1 * k, 3.2 * u, fill=rgb(c["accent2"]))

    # logo
    icon_logo(d, L["logo"][0] * k, L["logo"][1] * k, u, c)

    # window buttons
    col2 = rgb(c["accent2"]) + (255,)
    bx_, by_ = L["btn"]["min"]
    _capline(d, [((bx_ - 7 * S) * k, by_ * k), ((bx_ + 7 * S) * k, by_ * k)], col2, 2.4 * u)
    bx_, by_ = L["btn"]["pin"]
    box = [(bx_ - 7 * S) * k, (by_ - 7 * S) * k, (bx_ + 7 * S) * k, (by_ + 7 * S) * k]
    if pinned:
        d.rounded_rectangle(box, radius=int(2 * u), fill=rgb(c["accent"]) + (110,),
                            outline=rgb(c["accent"]) + (255,), width=int(2.6 * u))
    else:
        d.rounded_rectangle(box, radius=int(2 * u), outline=col2, width=int(2.2 * u))
    bx_, by_ = L["btn"]["close"]
    _capline(d, [((bx_ - 7 * S) * k, (by_ - 7 * S) * k), ((bx_ + 7 * S) * k, (by_ + 7 * S) * k)], col2, 2.4 * u)
    _capline(d, [((bx_ + 7 * S) * k, (by_ - 7 * S) * k), ((bx_ - 7 * S) * k, (by_ + 7 * S) * k)], col2, 2.4 * u)

    lay = lay.resize((W, H), Image.LANCZOS)
    return Image.alpha_composite(base, lay).convert("RGB")


def render_overlay(base_rgb, L):
    """Copy of the base with a transparent hole over the status panel,
    so the mouse glow sprite is clipped to that panel."""
    W, H, S = L["W"], L["H"], L["S"]
    k = 3
    m = Image.new("L", (W * k, H * k), 255)
    x1, y1, x2, y2 = L["rp"]
    i = 2 * S
    ImageDraw.Draw(m).rounded_rectangle([(x1 + i) * k, (y1 + i) * k, (x2 - i) * k, (y2 - i) * k],
                                        radius=int(12 * S * k), fill=0)
    m = m.resize((W, H), Image.LANCZOS)
    ov = base_rgb.convert("RGBA")
    ov.putalpha(m)
    return ov


def render_glow(c, R):
    n = int(2 * R)
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.hypot(xx - R, yy - R) / R
    a = np.clip(1 - d, 0, 1) ** 2
    out = np.zeros((n, n, 4), np.uint8)
    out[..., :3] = rgb(c["accent"])
    out[..., 3] = (a * 78).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


# ----------------------------------------------------------------------
#  glass cards
# ----------------------------------------------------------------------
def make_card_art(L, c, kind, box, base_rgb, hotkeys=True, selected="blue", themes=None):
    S, k = L["S"], CSS
    p = int(round(8 * S))
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    GW, GH = (w + 2 * p) * k, (h + 2 * p) * k
    ox, oy = x1 - p, y1 - p
    u = k * S
    X = lambda v: (v - ox) * k
    Y = lambda v: (v - oy) * k
    rad = int(16 * u)

    mask = Image.new("L", (GW, GH), 0)
    ImageDraw.Draw(mask).rounded_rectangle([p * k, p * k, (p + w) * k - 1, (p + h) * k - 1],
                                           radius=rad, fill=255)

    yy, xx = np.mgrid[0:GH, 0:GW]
    yy = yy.astype(np.float32)
    xx = xx.astype(np.float32)
    t = np.clip((xx - p * k) / (w * k) * 0.62 + (1 - (yy - p * k) / (h * k)) * 0.38, 0, 1)[..., None]
    dark = np.array(mixc(c["card"], c["bg"], 0.5), np.float32)
    lite = np.array(mixc(c["card"], c["accent2"], 0.24), np.float32)
    grad = dark * (1 - t) + lite * t

    glow_mask = mask.filter(ImageFilter.GaussianBlur(5 * u))

    sh = np.clip(1 - (yy - p * k) / (h * k * 0.5), 0, 1) ** 1.7 * 60
    sh = np.where(yy < p * k, 0, sh)
    sa = ImageChops.multiply(Image.fromarray(sh.astype(np.uint8), "L"), mask)
    sheen = Image.new("RGBA", (GW, GH), (255, 255, 255, 0))
    sheen.putalpha(sa)

    circ = Image.new("RGBA", (GW, GH), (0, 0, 0, 0))
    cd = ImageDraw.Draw(circ)
    ccx, ccy, cr = X(x1 + 24 * S), Y(y2 - 1 * S), 33 * u
    _disc(cd, ccx, ccy, cr, fill=(255, 255, 255, 16), outline=rgb(c["accent2"]) + (110,), width=int(2 * u))
    circ.putalpha(ImageChops.multiply(circ.split()[3], mask))

    border = Image.new("L", (GW, GH), 0)
    ImageDraw.Draw(border).rounded_rectangle([p * k, p * k, (p + w) * k - 1, (p + h) * k - 1],
                                             radius=rad, outline=255, width=max(2, int(1.7 * u)))

    ov = Image.new("RGBA", (GW, GH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    col, col2 = rgb(c["accent"]), rgb(c["accent2"])
    P = card_points(box, kind, S)
    ix, iy = P["icon"]
    if kind == "region":
        icon_region(d, X(ix), Y(iy), u, col, col2)
    elif kind == "ocr":
        icon_ocr(d, X(ix), Y(iy), u, col, col2)
    elif kind == "keys":
        icon_download(d, X(ix), Y(iy), u, col, col2)
    elif kind == "set":
        icon_gear(d, X(ix), Y(iy), u, col, col2, mixc(c["card"], c["bg"], 0.3))
    elif kind == "theme":
        icon_palette(d, X(ix), Y(iy), u, col, mixc(c["card"], c["bg"], 0.4),
                     mixc(c["card"], "#ffffff", 0.14))

    if kind in ("region", "set", "keys"):
        icon_chevron(d, X(P["chev"][0]), Y(P["chev"][1]), u, col2)
    if kind == "ocr":
        active = True
        bx1, by1, bx2, by2 = P["badge"]
        bb = [X(bx1), Y(by1), X(bx2), Y(by2)]
        fill = mixc(c["card"], c["accent"], 0.42 if active else 0.08)
        d.rounded_rectangle(bb, radius=int(8 * u), fill=fill,
                            outline=col2 if active else rgb(c["border"]), width=int(1.7 * u))
        if active:
            d.rounded_rectangle([bb[0] + 3 * u, bb[1] + 3 * u, bb[2] - 3 * u, (bb[1] + bb[3]) / 2],
                                radius=int(5 * u), fill=(255, 255, 255, 26))
    if kind == "theme":
        for i, ((dx, dy), name) in enumerate(zip(P["dots"], ("blue", "purple", "yellow", "green"))):
            colr = rgb(THEME_DOTS[i] if themes is None else themes[name]["accent"])
            cx_, cy_ = X(dx), Y(dy)
            if name == selected:
                _disc(d, cx_, cy_, 17 * u, outline=col2, width=int(2.2 * u))
                _disc(d, cx_, cy_, 15 * u, outline=colr + (90,), width=int(1.2 * u))
            _disc(d, cx_, cy_, 11.5 * u, fill=colr)
            _disc(d, cx_, cy_, 11.5 * u, outline=mixc(colr, "#000000", 0.35) + (255,), width=int(1.2 * u))
            _disc(d, cx_ - 3.5 * u, cy_ - 4 * u, 3.6 * u, fill=(255, 255, 255, 120))

    crop = base_rgb.crop((ox, oy, ox + w + 2 * p, oy + h + 2 * p)).convert("RGBA")
    return {
        "c": c, "k": k, "p": p, "S": S, "grad": grad, "mask": mask, "glow": glow_mask, "sheen": sheen,
        "circ": circ, "border": border, "ov": ov, "xx": xx, "yy": yy, "crop": crop,
        "size": (GW, GH), "size1": (w + 2 * p, h + 2 * p), "origin": (ox, oy),
        "lite2": np.array(mixc(c["accent2"], "#ffffff", 0.1), np.float32),
    }


def render_card(art, light=None, level=0.0):
    c, k, p, S = art["c"], art["k"], art["p"], art["S"]
    arr = art["grad"]
    if light is not None and level > 0:
        lx, ly = light
        d = np.hypot(art["xx"] - (lx + p) * k, art["yy"] - (ly + p) * k) / (150 * S * k)
        a = (np.clip(1 - d, 0, 1) ** 2 * (0.62 * level))[..., None]
        arr = arr * (1 - a) + art["lite2"] * a
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    img.putalpha(art["mask"])

    gl = Image.new("RGBA", art["size"], rgb(c["accent"]) + (0,))
    gl.putalpha(art["glow"].point(lambda v: int(v * (0.38 + 0.6 * level))))
    out = Image.alpha_composite(gl, img)
    out = Image.alpha_composite(out, art["sheen"])
    out = Image.alpha_composite(out, art["circ"])
    bcol = mixc(c["accent2"], "#ffffff", 0.10 + 0.5 * level)
    b = Image.new("RGBA", art["size"], bcol + (0,))
    b.putalpha(art["border"].point(lambda v: int(v * (0.72 + 0.28 * level))))
    out = Image.alpha_composite(out, b)
    out = Image.alpha_composite(out, art["ov"])
    out = out.resize(art["size1"], Image.LANCZOS)
    return Image.alpha_composite(art["crop"], out).convert("RGB")


FUZZY_CONFUSABLES = True   # O/0  I/1  S/5  B/8  Z/2 are treated as equal when comparing
_CONF = str.maketrans("OQDILSBZG", "000115826")


def norm_cell(s):
    if not s:
        return s
    return s.translate(_CONF) if FUZZY_CONFUSABLES else s


class FastOCR:
    THEMES = {
        "blue": {
            "name": "آبی",
            "bg": "#071426",
            "panel": "#0b1d33",
            "card": "#102944",
            "card2": "#0d223b",
            "accent": "#19aaff",
            "accent2": "#00eaff",
            "text": "#f3f8ff",
            "muted": "#91abc5",
            "border": "#16466f",
            "input": "#081a2d",
        },
        "purple": {
            "name": "بنفش",
            "bg": "#10091b",
            "panel": "#1a0e2b",
            "card": "#291442",
            "card2": "#211032",
            "accent": "#b84cff",
            "accent2": "#e08aff",
            "text": "#fbf5ff",
            "muted": "#c0a9d2",
            "border": "#63308b",
            "input": "#160b25",
        },
        "yellow": {
            "name": "زرد",
            "bg": "#171205",
            "panel": "#211a08",
            "card": "#352a0b",
            "card2": "#2b2209",
            "accent": "#ffd21c",
            "accent2": "#ffe77a",
            "text": "#fffdf2",
            "muted": "#cfc39a",
            "border": "#806d18",
            "input": "#1a1506",
        },
        "green": {
            "name": "سبز",
            "bg": "#06160e",
            "panel": "#0a2116",
            "card": "#103522",
            "card2": "#0c2a1b",
            "accent": "#20e58a",
            "accent2": "#6dffb8",
            "text": "#effff7",
            "muted": "#9bc7b0",
            "border": "#176440",
            "input": "#071a11",
        },
    }

    def __init__(self, license_info=None):
        self.license_info = license_info
        self.cfg = load_config()
        self.region = self.cfg.get("region")
        self.scan_key = self.cfg.get("scan_key", DEFAULT_SCAN_KEY)
        if "theme" not in self.cfg:
            self.cfg["theme"] = "blue"
        self.theme_name = self.cfg.get("theme", "blue")
        if self.theme_name not in self.THEMES:
            self.theme_name = "blue"
        self.theme = self.THEMES[self.theme_name]

        self.sct = mss.mss()
        self.busy = False
        self.ocr_ok = bool(find_tesseract())
        self.track_sct = None
        self.track_token = 0

        self.L = layout(UI_SCALE)
        self.hotkeys_enabled = True
        self.pinned = False

        self.root = tk.Tk()
        self.root.title("Hack Sikim Robbery")
        x = (self.root.winfo_screenwidth() - self.L["W"]) // 2
        y = (self.root.winfo_screenheight() - self.L["H"]) // 2
        self.root.geometry(f"{self.L['W']}x{self.L['H']}+{x}+{y}")
        self.root.overrideredirect(True)
        self.root.configure(bg=self.theme["bg"])

        self.overlay = BoxOverlay()
        self.overlay.color = self.theme["accent"]

        self.status_var = tk.StringVar(value="آماده به کار")
        self.matches_var = tk.StringVar(value="پیدا شد: ---")
        self.region_var = tk.StringVar(value="محدوده مورد نظر خود را انتخاب کنید")

        self.build_ui()
        self.bind_hotkeys()
        self.update_region_label()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self._fix_taskbar)
        self.root.after(LICENSE_CHECK_MS, self._license_tick)

    def _license_tick(self):
        """هر چند دقیقه لایسنس دوباره چک می‌شود (انقضا / تغییر ساعت)."""
        def work():
            try:
                ok, info, msg = license_core.check_saved()
            except Exception as e:
                ok, info, msg = True, self.license_info, ""
            try:
                self.root.after(0, lambda: self._license_done(ok, info, msg))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _license_done(self, ok, info, msg):
        if not ok:
            try:
                messagebox.showerror("لایسنس", msg or "لایسنس معتبر نیست.")
            except Exception:
                pass
            self.close()
            return
        self.license_info = info
        self.root.after(LICENSE_CHECK_MS, self._license_tick)

    # ------------------------------------------------------------------
    #  Neon UI — all graphics are rendered with Pillow (anti-aliased),
    #  text is drawn by Tk on top so it stays sharp.
    # ------------------------------------------------------------------
    def F(self, n):
        return max(6, int(round(n * self.L["S"])))

    def build_ui(self):
        L = self.L
        self.canvas = tk.Canvas(self.root, width=L["W"], height=L["H"], bg=self.theme["bg"],
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._mouse = None
        self._light_pending = False
        self._drag = None
        self._cache = {}
        self.hits = []
        self.cards = []

        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self.status_var.trace_add("write", self._sync_texts)
        self.matches_var.trace_add("write", self._sync_texts)
        self.region_var.trace_add("write", self._sync_texts)

        self.draw()

    def _sync_texts(self, *args):
        try:
            self.canvas.itemconfigure(self.matches_item, text=self.matches_var.get())
            self.canvas.itemconfigure(self.status_item, text=self.status_var.get())
            self.canvas.itemconfigure(self.region_item, text=self.region_var.get())
        except Exception:
            pass

    def _assets(self):
        """Pre-rendered images for the current theme/state (cached)."""
        key = (self.theme_name, self.pinned, self.hotkeys_enabled)
        a = self._cache.get(key)
        if a:
            return a
        c, L = self.theme, self.L
        base = render_base(L, c, self.pinned)
        cards = []
        for kind, box in L["cards"]:
            art = make_card_art(L, c, kind, box, base, self.hotkeys_enabled, self.theme_name, self.THEMES)
            cards.append({"kind": kind, "box": box, "art": art,
                          "photos": {None: ImageTk.PhotoImage(render_card(art))}})
        a = {
            "base": ImageTk.PhotoImage(base),
            "ov": ImageTk.PhotoImage(render_overlay(base, L)),
            "glow": ImageTk.PhotoImage(render_glow(c, int(110 * L["S"]))),
            "cards": cards,
        }
        self._cache[key] = a
        return a

    def draw(self):
        c, L, S, cv = self.theme, self.L, self.L["S"], self.canvas
        F = self.F
        a = self._assets()
        cv.delete("all")
        cv.configure(cursor="")
        self.hits = []
        self.cards = []

        cv.create_image(0, 0, image=a["base"], anchor="nw")
        self.glow_item = cv.create_image(0, 0, image=a["glow"], state="hidden")
        cv.create_image(0, 0, image=a["ov"], anchor="nw")   # clips the glow to the status panel

        # ---- title
        f1 = tkfont.Font(family="Segoe UI", size=F(17), weight="bold", slant="italic")
        tx, ty = L["title_xy"]
        cv.create_text(tx, ty, text="Hack Sikim ", anchor="w", fill=c["text"], font=f1)
        cv.create_text(tx + f1.measure("Hack Sikim "), ty, text="Robbery", anchor="w",
                       fill=c["accent"], font=f1)

        # ---- window buttons
        hb = 15 * S
        for name, cmd in (("min", self.minimize), ("pin", self.toggle_pin), ("close", self.close)):
            bx, by = L["btn"][name]
            self.hits.append(((bx - hb, by - hb, bx + hb, by + hb), cmd))

        # ---- cards
        ft_title = ("Segoe UI", F(12), "bold")
        ft_sub = ("Segoe UI", F(8))
        ft_badge = ("Segoe UI", F(12), "bold")
        titles = {
            "region": ("انتخاب منطقه", None),
            "ocr": ("OCR", "استخراج از متن تصویر"),
            "keys": ("نصب OCR", "دانلود و نصب موتور OCR"),
            "set": ("تنظیمات", "OCR و برنامه تنظیمات"),
            "theme": (None, None),
        }
        actions = {"region": self.select_region, "ocr": self.start_scan,
                   "keys": self.install_ocr, "set": self.open_settings}
        theme_hits = []
        for card in a["cards"]:
            kind, box, art = card["kind"], card["box"], card["art"]
            ox, oy = art["origin"]
            item = cv.create_image(ox, oy, image=card["photos"][None], anchor="nw")
            self.cards.append({"kind": kind, "box": box, "art": art, "item": item,
                               "key": None, "photos": card["photos"]})
            P = card_points(box, kind, S)
            if kind in actions:
                self.hits.append((box, actions[kind]))
            title, sub = titles[kind]
            if title:
                cv.create_text(P["text_x"], P["title_y"], text=title, anchor="w",
                               fill=c["text"], font=ft_title)
            if kind == "region":
                self.region_item = cv.create_text(P["text_x"], P["sub_y"], text=self.region_var.get(),
                                                  anchor="w", fill=c["accent2"], font=ft_sub)
            elif sub:
                cv.create_text(P["text_x"], P["sub_y"], text=sub, anchor="w",
                               fill=c["accent2"], font=ft_sub)
            if kind == "ocr":
                bx1, by1, bx2, by2 = P["badge"]
                label = self.scan_key.upper()
                on = True
                cv.create_text((bx1 + bx2) / 2, (by1 + by2) / 2, text=label,
                               fill=c["text"] if on else c["muted"], font=ft_badge)
            if kind == "theme":
                lx, ly = P["label"]
                cv.create_text(lx, ly, text="تم برنامه", anchor="w", fill=c["accent2"],
                               font=("Segoe UI", F(9), "bold"))
                for name, (dx, dy) in zip(("blue", "purple", "yellow", "green"), P["dots"]):
                    cv.create_text(dx, P["names_y"], text=self.THEMES[name]["name"],
                                   fill=c["text"], font=("Segoe UI", F(8)))
                    theme_hits.append(((dx - 15 * S, dy - 15 * S, dx + 15 * S, dy + 22 * S),
                                       lambda n=name: self.root.after(1, lambda: None if self._need_ocr() else self.apply_theme(n))))
        self.hits.extend(theme_hits)   # checked first (reversed order)

        # ---- status panel
        cv.create_text(*L["rtitle"], text="وضعیت اسکن", fill=c["text"], font=("Segoe UI", F(15), "bold"))
        self.matches_item = cv.create_text(*L["result"], text=self.matches_var.get(), fill=c["accent2"],
                                           font=("Segoe UI", F(13), "bold"), width=int(330 * S),
                                           justify="center")
        self.status_item = cv.create_text(*L["status"], text=self.status_var.get(), fill=c["muted"],
                                          font=("Segoe UI", F(10)), width=int(330 * S), justify="center")

        # ---- footer
        cv.create_text(*L["footer"], text="Created by Atila", anchor="w", fill=c["accent2"],
                       font=("Segoe UI", F(13), "bold"))
        self.apply_light()

    # ---- mouse handling ------------------------------------------------
    @staticmethod
    def _inside(box, x, y):
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def _on_press(self, e):
        for box, cmd in reversed(self.hits):
            if self._inside(box, e.x, e.y):
                cmd()
                return
        if e.y < 58 * self.L["S"]:
            self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _on_release(self, e):
        self._drag = None

    def _on_motion(self, e):
        self._mouse = (e.x, e.y)
        hand = any(self._inside(b, e.x, e.y) for b, _ in self.hits)
        self.canvas.configure(cursor="hand2" if hand else "")
        if not self._light_pending:
            self._light_pending = True
            self.root.after(22, self.apply_light)

    def _on_leave(self, e):
        self._mouse = None
        self.canvas.configure(cursor="")
        self.apply_light()

    def apply_light(self):
        self._light_pending = False
        m, L, cv = self._mouse, self.L, self.canvas
        S = L["S"]
        for cd in self.cards:
            x1, y1, x2, y2 = cd["box"]
            level, light = 0.0, None
            if m:
                dx = max(x1 - m[0], 0, m[0] - x2)
                dy = max(y1 - m[1], 0, m[1] - y2)
                t = max(0.0, 1 - math.hypot(dx, dy) / (90 * S))
                level = round((t ** 1.2) * 4) / 4
                if level > 0:
                    lx = min(max(m[0], x1), x2) - x1
                    ly = min(max(m[1], y1), y2) - y1
                    light = (int(lx // 8 * 8 + 4), int(ly // 8 * 8 + 4))
            key = None if level == 0 else (light, level)
            if key == cd["key"]:
                continue
            cd["key"] = key
            photos = cd["photos"]
            ph = photos.get(key)
            if ph is None:
                if len(photos) > 120:
                    keep = photos[None]
                    photos.clear()
                    photos[None] = keep
                ph = ImageTk.PhotoImage(render_card(cd["art"], light, level))
                photos[key] = ph
            cv.itemconfigure(cd["item"], image=ph)

        rp = L["rp"]
        if m and rp[0] < m[0] < rp[2] and rp[1] < m[1] < rp[3]:
            cv.coords(self.glow_item, m[0], m[1])
            cv.itemconfigure(self.glow_item, state="normal")
        else:
            cv.itemconfigure(self.glow_item, state="hidden")

    # ---- window behaviour ----------------------------------------------
    def minimize(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            self.root.withdraw()
            self.root.after(300, self.root.deiconify)

    def _on_map(self, e):
        pass

    def _apply_region(self):
        """Cut the chamfered corners with a Windows window region (keeps text anti-aliased)."""
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            W, H, cut = self.L["W"], self.L["H"], self.L["cut"]
            pts = [(cut, 0), (W - cut, 0), (W, cut), (W, H - cut),
                   (W - cut, H), (cut, H), (0, H - cut), (0, cut)]
            arr = (POINT * len(pts))(*[POINT(x, y) for x, y in pts])
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            rgn = ctypes.windll.gdi32.CreatePolygonRgn(arr, len(pts), 1)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _fix_taskbar(self):
        """Keep a taskbar icon even though the window has no native title bar."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)
            style = (style & ~0x00000080) | 0x00040000
            user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
        except Exception:
            pass
        self.root.after(80, self._apply_region)

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.draw()
        self.status_var.set("پنجره همیشه روی صفحه است." if self.pinned else "حالت همیشه-بالا خاموش شد.")

    def toggle_hotkeys(self):
        self.hotkeys_enabled = not self.hotkeys_enabled
        if self.hotkeys_enabled:
            self.bind_hotkeys()
            self.status_var.set("کلیدهای میانبر فعال شدند.")
        else:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            self.status_var.set("کلیدهای میانبر غیرفعال شدند.")
        self.draw()

    def _need_ocr(self):
        """True یعنی OCR نصب نیست و عملیات باید متوقف شود."""
        if self.ocr_ok:
            return False
        if find_tesseract():
            self.ocr_ok = True
            return False
        self.status_var.set("OCR را نصب کنید")
        return True

    def install_ocr(self):
        p = find_tesseract()
        if p:
            pytesseract.pytesseract.tesseract_cmd = p
            self.ocr_ok = True
            self.status_var.set("OCR از قبل نصب است ✓")
            return
        self.status_var.set("در حال نصب OCR ...")
        self.root.update_idletasks()
        ok = ensure_tesseract(self.theme, parent=self.root)
        self.ocr_ok = bool(ok)
        self.status_var.set("OCR با موفقیت نصب شد ✓" if ok else "نصب OCR انجام نشد.")

    def open_settings(self):
        if self._need_ocr():
            return
        c = self.theme
        win = tk.Toplevel(self.root)
        win.title("تنظیمات")
        win.configure(bg=c["bg"])
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.geometry("+%d+%d" % (self.root.winfo_x() + 120, self.root.winfo_y() + 120))

        tk.Label(win, text="کلید اسکن", bg=c["bg"], fg=c["text"],
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(16, 6))
        row = tk.Frame(win, bg=c["bg"])
        row.pack(fill="x", padx=18, pady=(0, 10))
        self.key_entry = tk.Entry(row, width=8, justify="center", bg=c["input"], fg=c["text"],
                                  insertbackground=c["text"], relief="flat",
                                  font=("Segoe UI", 11, "bold"))
        self.key_entry.insert(0, self.scan_key.upper())
        self.key_entry.pack(side="left", padx=(0, 8), ipady=6)

        def apply_and_refresh():
            self.apply_key()
            self._cache.clear()
            self.draw()

        tk.Button(row, text="اعمال", command=apply_and_refresh, bg=c["accent"], fg="#06101b",
                  activebackground=c["accent2"], relief="flat", bd=0, padx=14, pady=6,
                  font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="left")
        tk.Button(win, text="مخفی کردن کادرها", command=self.hide_boxes, bg=c["card2"], fg=c["text"],
                  activebackground=c["accent2"], relief="flat", bd=0, padx=14, pady=8,
                  font=("Segoe UI", 10, "bold"), cursor="hand2").pack(fill="x", padx=18, pady=(0, 16))

    def apply_theme(self, name, save=True):
        if name not in self.THEMES:
            name = "blue"
        self.theme_name = name
        self.theme = self.THEMES[name]
        if save:
            self.cfg["theme"] = name
            save_config(self.cfg)
        if hasattr(self, "overlay"):
            self.overlay.color = self.theme["accent"]
        self.root.configure(bg=self.theme["bg"])
        self.canvas.configure(bg=self.theme["bg"])
        self.draw()

    def bind_hotkeys(self):
        try:
            keyboard.add_hotkey(self.scan_key, self.start_scan)
        except Exception:
            pass

        try:
            keyboard.add_hotkey(DEFAULT_SELECT_KEY, self.select_region)
        except Exception:
            pass

    def rebind_scan_key(self, old_key, new_key):
        try:
            keyboard.remove_hotkey(old_key)
        except Exception:
            pass
        try:
            keyboard.add_hotkey(new_key, self.start_scan)
        except Exception as e:
            self.status_var.set(f"خطا در کلید {new_key}: {e}")

    def apply_key(self):
        try:
            new_key = self.key_entry.get().strip().lower()
        except Exception:
            return
        if not new_key:
            return

        old = self.scan_key
        self.scan_key = new_key
        self.cfg["scan_key"] = new_key
        save_config(self.cfg)
        self.rebind_scan_key(old, new_key)
        self.status_var.set(f"کلید اسکن: {new_key.upper()}")

    def update_region_label(self):
        if self.region:
            r = self.region
            self.region_var.set(
                f"X={r['left']} Y={r['top']} W={r['width']} H={r['height']}"
            )
        else:
            self.region_var.set("محدوده مورد نظر خود را انتخاب کنید")

    def select_region(self):
        if self._need_ocr():
            return
        self.root.withdraw()

        def done(region):
            self.region = region
            self.cfg["region"] = region
            save_config(self.cfg)
            self.root.deiconify()
            self.update_region_label()
            self.status_var.set(f"محدوده ذخیره شد. حالا {self.scan_key.upper()} را بزن.")

        self.root.after(150, lambda: RegionSelector(done))

    def hide_boxes(self):
        self.overlay.hide()
        self.status_var.set("کادرها مخفی شدند.")

    def capture(self):
        if not self.region:
            return None

        r = self.region
        monitor = {
            "left": int(r["left"]),
            "top": int(r["top"]),
            "width": int(r["width"]),
            "height": int(r["height"]),
        }
        img = np.array(self.sct.grab(monitor))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    @staticmethod
    def preprocess(img, scale=2, mode=0):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        # Tuned on a synthetic serif grid: 150 (fast pass) / 170 (retry pass).
        # No morphological opening: it erased the thin serifs of letters.
        _, th = cv2.threshold(gray, 150 if mode == 0 else 170, 255, cv2.THRESH_BINARY)

        # Red highlighted cells are dark in grayscale -> add them separately.
        b, g, r = cv2.split(img)
        red = ((r > 150) & (g < 120) & (b < 120)).astype(np.uint8) * 255
        red = cv2.resize(red, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        th = cv2.bitwise_or(th, red)

        # Tesseract reads black text on white best.
        th = 255 - th
        return cv2.copyMakeBorder(th, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

    @staticmethod
    def ocr_data(img):
        config = (
            "--oem 1 --psm 11 -c load_system_dawg=0 -c load_freq_dawg=0 "
            "-c user_defined_dpi=300 "
            "-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        return pytesseract.image_to_data(
            img,
            config=config,
            output_type=pytesseract.Output.DICT
        )

    @staticmethod
    def clean_digits(text):
        return re.sub(r"[^0-9A-Z]", "", (text or "").upper())

    def extract_tokens(self, data, scale):
        tokens = []

        n = len(data.get("text", []))
        for i in range(n):
            raw = data["text"][i]
            digits = self.clean_digits(raw)
            if not digits:
                continue

            try:
                conf = float(data["conf"][i])
            except Exception:
                conf = -1

            x = int((data["left"][i] - 10) / scale)
            y = int((data["top"][i] - 10) / scale)
            w = int(data["width"][i] / scale)
            h = int(data["height"][i] / scale)

            if w <= 0 or h <= 0:
                continue

            tokens.append({
                "text": digits,
                "conf": conf,
                "x": x, "y": y, "w": w, "h": h,
                "cx": x + w / 2,
                "cy": y + h / 2,
            })

        return tokens

    def find_target(self, tokens, img_h):
        """
        Find the LARGE 8-digit target.

        We do NOT simply take the first OCR result.
        Instead:
        1) only upper ~35% of the selected panel
        2) prefer tall/larger text
        3) group tokens on the same line
        4) accept a line whose digits total exactly 8
        """

        upper = [
            t for t in tokens
            if t["cy"] < img_h * 0.38
            and t["h"] >= max(6, img_h * 0.02)
        ]

        if not upper:
            return None, []

        # Sort top-to-bottom, then left-to-right.
        upper.sort(key=lambda t: (t["cy"], t["cx"]))

        lines = []
        for t in upper:
            placed = False
            for line in lines:
                avg_y = sum(x["cy"] for x in line) / len(line)
                avg_h = sum(x["h"] for x in line) / len(line)
                if abs(t["cy"] - avg_y) <= max(12, avg_h * 0.65):
                    line.append(t)
                    placed = True
                    break
            if not placed:
                lines.append([t])

        candidates = []

        for line in lines:
            line.sort(key=lambda t: t["cx"])

            # Join nearby OCR pieces on the same target line.
            joined = ""
            used = []

            for t in line:
                if len(t["text"]) > 4 or len(t["text"]) % 2:
                    continue

                if used:
                    prev = used[-1]
                    gap = t["x"] - (prev["x"] + prev["w"])
                    if gap > max(80, int(prev["w"] * 2.5)):
                        # Too far apart to be the same target.
                        joined = ""
                        used = []

                joined += t["text"]
                used.append(t)

                if len(joined) == 8:
                    digits = joined
                    heights = [x["h"] for x in used]
                    confs = [x["conf"] for x in used if x["conf"] >= 0]
                    score = (
                        np.mean(heights) * 5
                        + (np.mean(confs) if confs else 0)
                        - (used[0]["cy"] * 0.08)
                    )
                    candidates.append((score, digits, used))
                    break

                if len(joined) > 8:
                    joined = ""
                    used = []

        # Also support one OCR token that contains all 8 digits.
        for t in upper:
            if len(t["text"]) == 8:
                score = t["h"] * 8 + max(t["conf"], 0) * 1.5 - t["cy"] * 0.08
                candidates.append((score, t["text"], [t]))

        if not candidates:
            return None, []

        candidates.sort(key=lambda x: x[0], reverse=True)
        _, target, target_tokens = candidates[0]

        if len(target) != 8:
            return None, []

        return target, target_tokens

    def refine_target(self, img, tokens):
        """Second chance: the target is the TALLEST text line near the top.
        Crop that line and re-read it alone in single-line mode (much more
        accurate than the sparse full-panel pass)."""
        H, W = img.shape[:2]
        up = [t for t in tokens
              if t["cy"] < H * 0.45 and t["h"] >= max(5, H * 0.015)]
        if not up:
            return None, []
        up.sort(key=lambda t: (t["cy"], t["cx"]))
        lines = []
        for t in up:
            for line in lines:
                avg_y = sum(x["cy"] for x in line) / len(line)
                avg_h = sum(x["h"] for x in line) / len(line)
                if abs(t["cy"] - avg_y) <= max(8, avg_h * 0.65):
                    line.append(t)
                    break
            else:
                lines.append([t])

        best = None
        for line in lines:
            nchars = sum(len(t["text"]) for t in line)
            if not (5 <= nchars <= 14):
                continue
            mh = float(np.mean([t["h"] for t in line]))
            key = (mh, -line[0]["cy"])
            if best is None or key > best[0]:
                best = (key, line)
        if best is None:
            return None, []
        line = best[1]

        x1 = max(0, int(min(t["x"] for t in line)) - 10)
        x2 = min(W, int(max(t["x"] + t["w"] for t in line)) + 10)
        y1 = max(0, int(min(t["y"] for t in line)) - 6)
        y2 = min(H, int(max(t["y"] + t["h"] for t in line)) + 6)
        gray = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)

        votes = {}
        for thr in (150, 170, 120):
            if thr:
                _, th = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)
            else:
                _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            th = cv2.copyMakeBorder(255 - th, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            for psm in (7,):
                cfg = (f"--oem 1 --psm {psm} "
                       "-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                try:
                    txt = pytesseract.image_to_string(th, config=cfg)
                except pytesseract.TesseractNotFoundError:
                    raise
                except Exception:
                    continue
                txt = self.clean_digits(txt)
                if len(txt) == 8:
                    votes[txt] = votes.get(txt, 0) + 1
            if votes and max(votes.values()) >= 2:
                break
        if not votes:
            return None, []
        target = max(votes, key=votes.get)
        bottom = max(t["y"] + t["h"] for t in line)
        fake = [{"text": target, "conf": 50, "x": x1, "y": y1, "w": x2 - x1,
                 "h": bottom - y1, "cx": (x1 + x2) / 2.0, "cy": (y1 + bottom) / 2.0}]
        return target, fake

    def find_grid_matches(self, tokens, img_h, target, min_y=None):
        pairs = [target[i:i+2] for i in range(0, 8, 2)]
        lo = min_y if min_y is not None else img_h * 0.28

        # Grid starts below the target. Exclude the upper target area.
        grid = [
            t for t in tokens
            if t["cy"] > lo
            and t["cy"] < img_h * 0.98
            and 1 <= len(t["text"]) <= 2
            and t["conf"] >= 5
        ]

        # IMPORTANT:
        # A target pair can appear more than once in the grid.
        # Example: 38 may exist on the first row AND lower in the grid.
        # We use the other target matches as an anchor and choose the
        # duplicate closest to their row, instead of simply taking the
        # highest-confidence OCR result.
        all_candidates = {}
        for pair in pairs:
            all_candidates[pair] = [
                (idx, t) for idx, t in enumerate(grid)
                if norm_cell(t["text"]) == norm_cell(pair)
            ]

        # Unique matches are reliable row anchors.
        unique_y = [
            candidates[0][1]["cy"]
            for pair, candidates in all_candidates.items()
            if len(candidates) == 1
        ]

        # If there are duplicates, the unique target numbers tell us
        # roughly which grid band the answer belongs to.
        anchor_y = float(np.median(unique_y)) if unique_y else None

        results = []
        used_indices = set()

        grid_heights = [g["h"] for g in grid]
        median_h = float(np.median(grid_heights)) if grid_heights else 20.0

        for pair in pairs:
            candidates = all_candidates.get(pair, [])
            if not candidates:
                continue

            def candidate_score(item):
                idx, t = item

                # Strongly prefer the candidate on the same/nearest row
                # as the other target matches.
                if anchor_y is not None:
                    row_distance = abs(t["cy"] - anchor_y)
                    row_score = -row_distance * 4.0
                else:
                    row_score = 0.0

                confidence_score = max(t["conf"], 0) * 0.8
                size_score = -abs(t["h"] - median_h) * 0.5

                return row_score + confidence_score + size_score

            candidates.sort(key=candidate_score, reverse=True)

            chosen = None
            for idx, t in candidates:
                if idx not in used_indices:
                    chosen = (idx, t)
                    break

            if chosen is None:
                chosen = candidates[0]

            idx, t = chosen
            used_indices.add(idx)
            results.append((pair, t))

        return results

    # ---- grid model: rows/columns, 4-in-a-row search ---------------------
    def build_grid(self, tokens, img_h, min_y=None):
        """Rebuild the grid (rows x columns) from OCR tokens.
        Missing/misread cells become placeholders so positions stay complete."""
        cells_in = []
        for t in tokens:
            if not ((min_y if min_y is not None else img_h * 0.28) < t["cy"] < img_h * 0.98) or t["conf"] < 5:
                continue
            txt = t["text"]
            if len(txt) in (1, 2):
                cells_in.append(t)
            elif len(txt) == 4:          # two cells merged by OCR -> split
                hw = t["w"] / 2.0
                for k in range(2):
                    x = t["x"] + k * hw
                    cells_in.append({
                        "text": txt[2 * k:2 * k + 2], "conf": t["conf"],
                        "x": int(x), "y": t["y"], "w": int(hw), "h": t["h"],
                        "cx": x + hw / 2.0, "cy": t["cy"],
                    })
        if len(cells_in) < 8:
            return None

        hs = float(np.median([c["h"] for c in cells_in]))
        ws = float(np.median([c["w"] for c in cells_in]))

        cells_in.sort(key=lambda c: c["cy"])
        rows = []
        for t in cells_in:
            for row in rows:
                if abs(t["cy"] - np.mean([c["cy"] for c in row])) <= hs * 0.6:
                    row.append(t)
                    break
            else:
                rows.append([t])
        rows = [r for r in rows if len(r) >= 2]
        if not rows:
            return None
        rows.sort(key=lambda r: np.mean([c["cy"] for c in r]))
        for r in rows:
            r.sort(key=lambda c: c["cx"])

        diffs = [b["cx"] - a["cx"] for r in rows for a, b in zip(r, r[1:])]
        diffs = [d for d in diffs if d > 0]
        if not diffs:
            return None
        m = float(np.median(diffs))
        good = [d for d in diffs if 0.6 * m <= d <= 1.4 * m]
        pitch = float(np.median(good)) if good else m
        if pitch < 4:
            return None

        # --- column lattice: fit phase with a circular mean (robust when the first
        #     column is missing / misread), then a per-row shift (rows may be offset
        #     from each other while the grid is sliding).
        def _phase(vals):
            ang = 2 * math.pi * (np.asarray(vals, float) / pitch)
            return math.atan2(float(np.sin(ang).mean()), float(np.cos(ang).mean())) / (2 * math.pi) * pitch

        def _wrap_half(v):
            return (v + pitch / 2.0) % pitch - pitch / 2.0

        glob_phase = _phase([c["cx"] for r in rows for c in r])
        first_med = float(np.median([r[0]["cx"] for r in rows]))
        last_med = float(np.median([r[-1]["cx"] for r in rows]))
        x_min = glob_phase + round((first_med - glob_phase) / pitch) * pitch
        ncols = int(round((last_med - x_min) / pitch)) + 1
        if ncols < 2:
            return None

        rows_cy = [float(np.mean([c["cy"] for c in r])) for r in rows]
        grid = []
        for r, rcy in zip(rows, rows_cy):
            shift = _wrap_half(_phase([c["cx"] for c in r]) - glob_phase)
            arr = [None] * ncols
            for t in r:
                c = int(round((t["cx"] - x_min - shift) / pitch))
                if 0 <= c < ncols and (arr[c] is None or t["conf"] > arr[c]["conf"]):
                    arr[c] = t
            real = [(c, arr[c]) for c in range(ncols) if arr[c] is not None]
            for c in range(ncols):
                if arr[c] is None:
                    # Missing cell: extrapolate from the NEAREST REAL cell of the same row
                    # (uses its true on-screen position, so no lattice offset error).
                    if real:
                        cn, tn = min(real, key=lambda it: abs(it[0] - c))
                        cxp = tn["cx"] + (c - cn) * pitch
                    else:
                        cxp = x_min + shift + c * pitch
                    arr[c] = {
                        "text": None, "conf": 0,
                        "x": int(cxp - ws / 2),
                        "y": int(rcy - hs / 2),
                        "w": int(ws), "h": int(hs),
                        "cx": cxp, "cy": rcy,
                    }
            grid.append(arr)

        row_h = float(np.median(np.diff(rows_cy))) if len(rows_cy) > 1 else 0.0
        geom = {
            "left": x_min - pitch / 2.0,
            "row_w": ncols * pitch,
            "row_h": row_h,
            "pitch": pitch,
            "top": rows_cy[0] - (row_h / 2.0 if row_h else hs),
            "nrows": len(rows),
        }
        return grid, geom

    @staticmethod
    def find_sequence(grid, pairs):
        """Find the 4 target pairs as 4 NEIGHBOURING cells, read left -> right
        (reading order, so a window may continue on the next row; also cyclic).
        Duplicates elsewhere in the grid are ignored because order + adjacency
        must match. At least 3 of 4 must match (one may be an OCR miss)."""
        seq = [c for row in grid for c in row]
        n = len(seq)
        if n < 4:
            return None
        best = None
        for need in (4, 3, 2):          # strict first, then relaxed
            for i in range(n):
                hit, conf = 0, 0.0
                for k in range(4):
                    c = seq[(i + k) % n]
                    if norm_cell(c["text"]) == norm_cell(pairs[k]):
                        hit += 1
                        conf += c["conf"]
                if hit >= need and (best is None or (hit, conf) > best[0]):
                    best = ((hit, conf), i)
            if best:
                break
        if best is None:
            return None
        i = best[1]
        return [(pairs[k], seq[(i + k) % n]) for k in range(4)]

    def make_wrap(self, g):
        """Screen-space wrap function for tracked box centres."""
        def wrap(x, y):
            k = math.floor((x - g["left"]) / g["row_w"])
            if k:
                x -= k * g["row_w"]
                if WRAP_ROWS_CHAIN:
                    y += k * g["row_h"]
            if WRAP_ROWS_CHAIN and g["nrows"] > 1 and g["row_h"]:
                total = g["nrows"] * g["row_h"]
                y = g["top"] + ((y - g["top"]) % total)
            return x, y
        return wrap

    def _analyze(self, img, scale, mode):
        """One OCR pass. Returns dict or None if the target was not found."""
        processed = self.preprocess(img, scale=scale, mode=mode)
        if DEBUG_SAVE:
            try:
                cv2.imwrite(os.path.join(APP_DIR, "last_capture.png"), img)
                cv2.imwrite(os.path.join(APP_DIR, "last_processed_%d.png" % mode), processed)
            except Exception:
                pass
        data = self.ocr_data(processed)
        tokens = self.extract_tokens(data, scale=scale)

        target, target_tokens = self.refine_target(img, tokens)
        if not target:
            target, target_tokens = self.find_target(tokens, img.shape[0])
        if not target:
            return None

        pairs = [target[i:i + 2] for i in range(0, 8, 2)]
        geom = None
        matches = None
        min_y = max(t["y"] + t["h"] for t in target_tokens)
        grid_info = self.build_grid(tokens, img.shape[0], min_y)
        if grid_info:
            grid, geom = grid_info
            matches = self.find_sequence(grid, pairs)
        if not matches:
            geom = None
            matches = self.find_grid_matches(tokens, img.shape[0], target, min_y)

        quality = sum(1 for pair, t in matches
                      if t["text"] and norm_cell(t["text"]) == norm_cell(pair))
        return {"target": target, "target_tokens": target_tokens, "geom": geom,
                "matches": matches, "quality": quality}

    def scan_worker(self):
        try:
            img = self.capture()
            if img is None:
                self.root.after(
                    0, lambda: self.status_var.set(
                        "اول F7 بزن و کل پنل بازی را انتخاب کن."
                    )
                )
                return

            res = self._analyze(img, 2, 0)
            if res is None or res["quality"] < 4:
                res2 = self._analyze(img, 3, 1)      # slower retry, only when needed
                if res2 is not None and (res is None or res2["quality"] > res["quality"]):
                    res = res2

            if res is None:
                self.root.after(
                    0, lambda: self.status_var.set(
                        "هدف ۸ رقمی بزرگ پیدا نشد. محدوده را کامل‌تر انتخاب کن."
                    )
                )
                self.root.after(
                    0, lambda: self.matches_var.set("پیدا شد: ---")
                )
                return

            target, target_tokens = res["target"], res["target_tokens"]
            geom, matches = res["geom"], res["matches"]

            boxes = []
            found_names = []

            r = self.region

            for pair, t in matches:
                # Add a small padding around the OCR box.
                pad_x = max(4, int(t["w"] * 0.25))
                pad_y = max(4, int(t["h"] * 0.30))

                x1 = r["left"] + t["x"] - pad_x
                y1 = r["top"] + t["y"] - pad_y
                x2 = r["left"] + t["x"] + t["w"] + pad_x
                y2 = r["top"] + t["y"] + t["h"] + pad_y

                boxes.append({
                    "x1": x1, "y1": y1,
                    "x2": x2, "y2": y2,
                })
                found_names.append(pair)

            try:
                ref_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                y0 = int(max(t["y"] + t["h"] for t in target_tokens)) + 2
                if ref_gray.shape[0] - y0 < 40:
                    y0 = 0
            except Exception:
                ref_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                y0 = 0

            full_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            Hh, Ww = full_gray.shape[:2]
            cells = []
            for (pair, t), b in zip(matches, boxes):
                tx1 = max(0, int(t["x"]) - 2)
                ty1 = max(0, int(t["y"]) - 2)
                tx2 = min(Ww, int(t["x"] + t["w"]) + 2)
                ty2 = min(Hh, int(t["y"] + t["h"]) + 2)
                tpl = None
                if tx2 - tx1 >= 6 and ty2 - ty1 >= 6:
                    tpl = full_gray[ty1:ty2, tx1:tx2].copy()
                tcx, tcy = (tx1 + tx2) / 2.0, (ty1 + ty2) / 2.0
                bcx = (b["x1"] + b["x2"]) / 2.0 - r["left"]
                bcy = (b["y1"] + b["y2"]) / 2.0 - r["top"]
                cells.append({"tpl": tpl, "cx": tcx, "cy": tcy,
                              "bdx": bcx - tcx, "bdy": bcy - tcy})

            def update_ui():
                if found_names:
                    self.matches_var.set(
                        "پیدا شد: " + " | ".join(found_names)
                    )
                    self.overlay.show(boxes, BOX_SECONDS)
                    if TRACK_MOVEMENT:
                        self.start_tracking(ref_gray[y0:, :], y0, geom, cells)
                    self.status_var.set(
                        "اسکن موفق — کادرها تا ۱۰ ثانیه نمایش داده می‌شوند."
                    )
                else:
                    self.matches_var.set("پیدا شد: هیچ‌کدام")
                    self.overlay.hide()
                    self.status_var.set(
                        f"هدف «{target}» خوانده شد، ولی در جدول پیدا نشد."
                    )

            self.root.after(0, update_ui)

        except pytesseract.TesseractNotFoundError:
            self.root.after(
                0, lambda: self.status_var.set(
                    "OCR نصب نیست. روی «نصب OCR» بزن."
                )
            )
        except Exception as e:
            msg = str(e)
            self.root.after(
                0, lambda: self.status_var.set("خطا: " + msg[:120])
            )
        finally:
            self.busy = False

    # ---- follow the moving numbers ------------------------------------
    def start_tracking(self, ref_crop, y0, geom=None, cells=None):
        self.track_token += 1
        self.track_use_dy = geom is None
        self.track_cells = cells or []
        self.track_wrap = None
        self.track_pitch = 0.0
        if geom is not None:
            r0 = self.region
            g = dict(geom)
            g["left"] += r0["left"]
            g["top"] += r0["top"]
            self.track_wrap = self.make_wrap(g)
            self.track_pitch = float(geom.get("pitch", 0.0))
            self.overlay.set_wrap(self.track_wrap)
        else:
            self.overlay.set_wrap(None)
        token = self.track_token
        self.track_prev = ref_crop
        self.track_y0 = y0
        self.track_dx = 0.0
        self.track_dy = 0.0
        r = self.region
        self.track_clip = (r["left"], r["top"],
                           r["left"] + r["width"], r["top"] + r["height"])
        self.root.after(TRACK_INTERVAL_MS, lambda: self.track_tick(token))

    def grab_full(self):
        if self.track_sct is None:
            self.track_sct = mss.mss()   # created on the main (Tk) thread
        r = self.region
        monitor = {"left": int(r["left"]), "top": int(r["top"]),
                   "width": int(r["width"]), "height": int(r["height"])}
        img = np.array(self.track_sct.grab(monitor))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)

    def grab_crop(self):
        return self.grab_full()[self.track_y0:, :]

    @staticmethod
    def refine_cell(gray, tpl, px, py, pitch):
        """Re-lock one box onto its own glyphs by template matching around the
        predicted position (small window first, wider window as a fallback)."""
        if tpl is None:
            return px, py, False
        th, tw = tpl.shape[:2]
        H, W = gray.shape[:2]
        pitch = pitch if pitch > 0 else tw * 1.6
        for frac, thr in ((0.45, 0.55), (1.6, 0.75)):
            hx = max(8.0, pitch * frac)
            hy = max(5.0, th * 0.6)
            x0 = int(max(0, px - tw / 2.0 - hx))
            x1 = int(min(W, px + tw / 2.0 + hx))
            y0 = int(max(0, py - th / 2.0 - hy))
            y1 = int(min(H, py + th / 2.0 + hy))
            if x1 - x0 < tw or y1 - y0 < th:
                continue
            res = cv2.matchTemplate(gray[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx >= thr:
                return x0 + loc[0] + tw / 2.0, y0 + loc[1] + th / 2.0, True
        return px, py, False

    @staticmethod
    def estimate_shift(prev, cur):
        if prev.shape != cur.shape:
            return 0.0, 0.0
        prev = cv2.resize(prev, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        cur = cv2.resize(cur, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        h, w = prev.shape[:2]
        win = cv2.createHanningWindow((w, h), cv2.CV_32F)
        (dx, dy), resp = cv2.phaseCorrelate(np.float32(prev), np.float32(cur), win)
        dx *= 2.0
        dy *= 2.0
        if resp < 0.03 or abs(dx) > w or abs(dy) > h:
            return 0.0, 0.0
        if abs(dx) < 0.3:
            dx = 0.0
        if abs(dy) < 0.3:
            dy = 0.0
        return dx, dy

    def track_tick(self, token):
        if token != self.track_token or self.overlay.root is None:
            return
        try:
            full = self.grab_full()
            cur = full[self.track_y0:, :]
            dx, dy = self.estimate_shift(self.track_prev, cur)
            if not self.track_use_dy:
                dy = 0.0          # numbers move horizontally; vertical = wrap
            if getattr(self, "track_cells", None):
                # Per-box tracking: global shift predicts, template matching locks each
                # box onto its own cell (so every box follows its numbers exactly).
                rl, rt = self.region["left"], self.region["top"]
                centers = []
                for cell in self.track_cells:
                    px, py = cell["cx"] + dx, cell["cy"] + dy
                    if self.track_wrap is not None:
                        sx, sy = self.track_wrap(px + rl, py + rt)
                        px, py = sx - rl, sy - rt
                    px, py, _ok = self.refine_cell(full, cell["tpl"], px, py, self.track_pitch)
                    cell["cx"], cell["cy"] = px, py
                    centers.append((px + cell["bdx"] + rl, py + cell["bdy"] + rt))
                self.overlay.place(centers, self.track_clip)
                self.track_prev = cur
                self.root.after(TRACK_INTERVAL_MS, lambda: self.track_tick(token))
                return
            if dx or dy:
                self.track_dx += dx
                self.track_dy += dy
                self.overlay.move(self.track_dx, self.track_dy, self.track_clip)
            self.track_prev = cur
        except Exception:
            pass
        self.root.after(TRACK_INTERVAL_MS, lambda: self.track_tick(token))

    def start_scan(self):
        if self._need_ocr():
            return
        if self.busy:
            return

        self.busy = True
        self.overlay.hide()
        self.status_var.set("در حال اسکن...")
        threading.Thread(
            target=self.scan_worker,
            daemon=True
        ).start()

    def close(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        try:
            self.overlay.hide()
        except Exception:
            pass
        try:
            self.sct.close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()




# ======================================================================
#  بخش لایسنس
# ======================================================================

import os
import sys
import time
import hmac
import json
import base64
import struct
import hashlib
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

# کلید عمومی (با کلید خصوصیِ license_private.key جفت است)
PUBLIC_KEY_B64 = "9wjAiRYUHejv8xPB8V5hyD0jhfCbGCB+WlS6AXhEsOA="

APP_DIR = os.path.join(os.path.expanduser("~"), "FastOCR8")
LICENSE_FILE = os.path.join(APP_DIR, "license.dat")
REG_PATH = r"Software\FastOCR8"
REG_VALUE = "ls"

# آدرس فایل متنی «لیست ابطال» (مثلاً لینک raw در GitHub). خالی = ابطال آنلاین خاموش
REVOKE_URL = "https://raw.githubusercontent.com/Atilaganji123/license/main/revoked.txt"
REVOKE_FLAG = os.path.join(APP_DIR, "rv.dat")
REVOKE_EVERY = 12              # ثانیه — هر چند وقت لیست ابطال دوباره خوانده شود
_last_fetch = [0]

KEY_VERSION = 1
HWID_SALT = b"FastOCR8-HWID-v1"
CLOCK_TOLERANCE = 300          # ثانیه — اختلاف مجاز ساعت سیستم


class LicenseError(Exception):
    pass


# ----------------------------------------------------------------------
#  HWID
# ----------------------------------------------------------------------
def _reg_read(hive, path, name, wow64=True):
    try:
        import winreg
        flags = winreg.KEY_READ
        if wow64:
            flags |= winreg.KEY_WOW64_64KEY
        with winreg.OpenKey(hive, path, 0, flags) as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except Exception:
        return ""


def get_hwid():
    """شناسه دستگاه به شکل XXXX-XXXX-XXXX-XXXX-XXXX"""
    parts = []
    try:
        import winreg
        HK = winreg.HKEY_LOCAL_MACHINE
        parts.append(_reg_read(HK, r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"))
        parts.append(_reg_read(HK, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                               "ProcessorNameString", wow64=False))
        bios = r"HARDWARE\DESCRIPTION\System\BIOS"
        for n in ("SystemManufacturer", "SystemProductName", "BaseBoardManufacturer", "BaseBoardProduct"):
            parts.append(_reg_read(HK, bios, n, wow64=False))
    except Exception:
        pass
    if not any(parts):
        import uuid
        parts = [str(uuid.getnode()), os.environ.get("COMPUTERNAME", "") or os.uname().nodename]
    h = hashlib.sha256(HWID_SALT + "|".join(parts).encode("utf-8", "ignore")).hexdigest().upper()[:20]
    return "-".join(h[i:i + 4] for i in range(0, 20, 4))


def normalize_hwid(s):
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def hwid_digest(hwid):
    return hashlib.sha256(HWID_SALT + normalize_hwid(hwid).encode()).digest()[:16]


# ----------------------------------------------------------------------
#  ساخت / خواندن کلید
# ----------------------------------------------------------------------
def make_key(private_key, hwid, username, expiry_ts):
    """expiry_ts = 0  → دائمی.  private_key: Ed25519PrivateKey"""
    if len(normalize_hwid(hwid)) != 20:
        raise LicenseError("HWID نامعتبر است (باید ۲۰ حرف/رقم باشد).")
    name = (username or "").strip().encode("utf-8")[:60]
    payload = struct.pack(">BII16sB", KEY_VERSION, int(time.time()), int(expiry_ts),
                          hwid_digest(hwid), len(name)) + name
    raw = payload + private_key.sign(payload)
    b32 = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(b32[i:i + 6] for i in range(0, len(b32), 6))


def _decode_key(key):
    s = "".join(ch for ch in (key or "").upper() if ch.isalnum())
    if not s:
        raise LicenseError("کلید لایسنس وارد نشده است.")
    s += "=" * (-len(s) % 8)
    try:
        return base64.b32decode(s)
    except Exception:
        raise LicenseError("فرمت کلید درست نیست.")


def verify_key(key, hwid=None, now=None):
    """کلید را بررسی می‌کند و دیکشنری اطلاعات را برمی‌گرداند؛ در صورت خطا LicenseError."""
    raw = _decode_key(key)
    if len(raw) < 26 + 64:
        raise LicenseError("کلید ناقص است.")
    payload, sig = raw[:-64], raw[-64:]
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64))
        pub.verify(sig, payload)
    except (InvalidSignature, ValueError):
        raise LicenseError("کلید لایسنس معتبر نیست.")
    ver, issued, expiry, hd, nlen = struct.unpack(">BII16sB", payload[:26])
    if ver != KEY_VERSION or len(payload) != 26 + nlen:
        raise LicenseError("نسخه کلید پشتیبانی نمی‌شود.")
    hwid = hwid or get_hwid()
    if not hmac.compare_digest(hd, hwid_digest(hwid)):
        raise LicenseError("این کلید برای این دستگاه صادر نشده است.")
    now = time.time() if now is None else now
    if expiry and now > expiry:
        raise LicenseError("مدت اعتبار لایسنس تمام شده است.")
    return {
        "user": payload[26:].decode("utf-8", "ignore"),
        "issued": issued,
        "expiry": expiry,                       # 0 = دائمی
        "left": (expiry - now) if expiry else None,
    }


# ----------------------------------------------------------------------
#  ذخیره‌سازی و جلوگیری از عقب کشیدن ساعت
# ----------------------------------------------------------------------
def _mac(key, seen, hwid):
    k = hashlib.sha256(b"state" + HWID_SALT + normalize_hwid(hwid).encode()).digest()
    return hmac.new(k, f"{key}|{seen}".encode(), hashlib.sha256).hexdigest()


def _load_file(hwid):
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        key, seen = d["key"], int(d["seen"])
        if hmac.compare_digest(d["mac"], _mac(key, seen, hwid)):
            return key, seen
    except Exception:
        pass
    return None, 0


def _load_reg_seen(hwid):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            v = winreg.QueryValueEx(k, REG_VALUE)[0]
        seen, mac = v.split(":")
        if hmac.compare_digest(mac, _mac("reg", int(seen), hwid)):
            return int(seen)
    except Exception:
        pass
    return 0


def _save(key, seen, hwid):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump({"key": key, "seen": int(seen), "mac": _mac(key, int(seen), hwid)}, f)
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            winreg.SetValueEx(k, REG_VALUE, 0, winreg.REG_SZ,
                              f"{int(seen)}:{_mac('reg', int(seen), hwid)}")
    except Exception:
        pass


def _check_clock(seen, now):
    if now + CLOCK_TOLERANCE < seen:
        raise LicenseError("ساعت/تاریخ سیستم تغییر کرده است. آن را درست کنید.")


def activate(key):
    """کلید را بررسی و ذخیره می‌کند. info برمی‌گرداند یا LicenseError."""
    hwid = get_hwid()
    now = int(time.time())
    seen = max(_load_file(hwid)[1], _load_reg_seen(hwid))
    _check_clock(seen, now)
    info = verify_key(key, hwid, now)
    _check_revoked(key, hwid, force=True)
    _save("".join(ch for ch in key.upper() if ch.isalnum()), max(seen, now), hwid)
    return info


def check_saved():
    """
    لایسنس ذخیره‌شده را بررسی می‌کند.
    خروجی: (ok, info, message)   — اگر چیزی ذخیره نشده باشد message خالی است.
    """
    hwid = get_hwid()
    key, seen_f = _load_file(hwid)
    if not key:
        return False, None, ""
    now = int(time.time())
    try:
        _check_clock(max(seen_f, _load_reg_seen(hwid)), now)
        info = verify_key(key, hwid, now)
        _check_revoked(key, hwid)
    except LicenseError as e:
        return False, None, str(e)
    _save(key, max(seen_f, _load_reg_seen(hwid), now), hwid)
    return True, info, ""


def key_id(key):
    """شناسه کوتاه کلید (برای لیست ابطال)"""
    k = "".join(ch for ch in (key or "").upper() if ch.isalnum())
    return hashlib.sha256(k.encode()).hexdigest()[:12]


def _flag_mac(kid, hwid):
    return _mac("revoked:" + kid, 0, hwid)


def _check_revoked(key, hwid, force=False):
    """اگر کلید در لیست ابطال باشد LicenseError. اگر اینترنت نبود، آخرین وضعیت ذخیره‌شده ملاک است."""
    kid = key_id(key)
    try:
        with open(REVOKE_FLAG, "r") as f:
            if hmac.compare_digest(f.read().strip(), _flag_mac(kid, hwid)):
                raise LicenseError("این لایسنس باطل شده است.")
    except FileNotFoundError:
        pass
    if not REVOKE_URL:
        return
    now = time.time()
    if not force and now - _last_fetch[0] < REVOKE_EVERY:
        return
    try:
        url = REVOKE_URL + ("&" if "?" in REVOKE_URL else "?") + "t=%d" % int(now * 1000)   # دور زدن کش
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
        text = urllib.request.urlopen(req, timeout=5).read().decode("utf-8", "ignore")
    except Exception:
        return
    _last_fetch[0] = now
    ids = {ln.split("#")[0].strip().lower() for ln in text.splitlines()}
    if kid in ids:
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(REVOKE_FLAG, "w") as f:
                f.write(_flag_mac(kid, hwid))
        except Exception:
            pass
        raise LicenseError("این لایسنس باطل شده است.")


def fmt_left(info):
    if not info or not info.get("expiry"):
        return "دائمی"
    s = int(info["left"])
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d} روز و {h} ساعت"
    if h:
        return f"{h} ساعت و {m} دقیقه"
    return f"{m} دقیقه"


# ======================================================================
#  ظاهر نئونی و پنجره فعال‌سازی
# ======================================================================

import math
import tkinter as tk
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


SS = 3


# ----------------------------------------------------------------------
#  helpers (همان توابع برنامه اصلی)
# ----------------------------------------------------------------------
def rgb(h):
    if not isinstance(h, str):
        return tuple(h)
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mixc(a, b, t):
    a, b = rgb(a), rgb(b)
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def hx(t):
    return "#%02x%02x%02x" % tuple(t)


def mixh(a, b, t):
    return hx(mixc(a, b, t))


def chamfer_pts(x1, y1, x2, y2, c):
    return [(x1 + c, y1), (x2 - c, y1), (x2, y1 + c), (x2, y2 - c),
            (x2 - c, y2), (x1 + c, y2), (x1, y2 - c), (x1, y1 + c)]


def _closed(d, pts, fill, width):
    pts = list(pts)
    d.line(pts + [pts[0], pts[1]], fill=fill, width=width, joint="curve")


def _capline(d, pts, fill, w):
    d.line(pts, fill=fill, width=int(round(w)), joint="curve")
    r = w / 2
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _disc(d, cx, cy, r, **kw):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)


def icon_logo(d, cx, cy, u, c):
    R = 19 * u
    hexa = [(cx + math.cos(math.radians(30 + 60 * i)) * R, cy + math.sin(math.radians(30 + 60 * i)) * R)
            for i in range(6)]
    d.polygon(hexa, fill=rgb(c["accent"]))
    R2 = 15.5 * u
    hex2 = [(cx + math.cos(math.radians(30 + 60 * i)) * R2, cy + math.sin(math.radians(30 + 60 * i)) * R2)
            for i in range(6)]
    _closed(d, hex2, rgb(c["accent2"]) + (200,), int(1.2 * u))
    d.rounded_rectangle([cx - 11 * u, cy - 4.5 * u, cx + 11 * u, cy + 8 * u], radius=int(4 * u),
                        fill=rgb(c["bg"]))
    for dx in (-4.6, 4.6):
        _disc(d, cx + dx * u, cy + 1.6 * u, 2.5 * u, fill=rgb(c["accent2"]))
    d.polygon([(cx - 6 * u, cy - 9 * u), (cx, cy - 15 * u), (cx + 6 * u, cy - 9 * u)],
              fill=mixc(c["accent"], "#ffffff", 0.25))


def gradient(W, H, colors):
    """گرادیان افقی بین چند رنگ (۱ رنگ = تک‌رنگ)."""
    cols = np.array([rgb(c) for c in colors], float)
    if len(cols) == 1:
        arr = np.tile(cols[0], (H, W, 1))
    else:
        t = np.linspace(0, len(cols) - 1, W)
        i = np.minimum(t.astype(int), len(cols) - 2)
        f = (t - i)[:, None]
        row = cols[i] * (1 - f) + cols[i + 1] * f
        arr = np.tile(row[None], (H, 1, 1))
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _masked(grad_img, mask):
    layer = grad_img.convert("RGBA")
    layer.putalpha(mask)
    return layer


# ----------------------------------------------------------------------
#  رندر قاب نئونی (همان قاب برنامه اصلی؛ palette می‌تواند ۱ یا ۴ رنگ باشد)
# ----------------------------------------------------------------------
def render_frame(W, H, c, palette, cut=24, tab_w=334):
    k = SS
    g = gradient(W, H, palette)
    garr = np.asarray(g, float)
    yy = np.linspace(0, 1, H)[:, None]
    xx = np.linspace(0, 1, W)[None, :]
    bgc = np.array(rgb(c["bg"]), float)
    a = (0.12 * np.exp(-(((xx - 0.85) ** 2) / 0.10 + ((yy - 0.0) ** 2) / 0.22))
         + 0.06 * np.exp(-(((xx - 0.05) ** 2) / 0.18 + ((yy - 1.0) ** 2) / 0.18)))[..., None]
    base = Image.fromarray((bgc * (1 - a) + garr * a).astype(np.uint8), "RGB").convert("RGBA")

    ins = 3
    outer = chamfer_pts(ins, ins, W - ins, H - ins, cut - ins)
    io = ins + 7
    inner = chamfer_pts(io, io, W - io, H - io, max(6, cut - io))

    def sc(pts):
        return [(x * k, y * k) for x, y in pts]

    # درخشش دور قاب
    m = Image.new("L", (W * k, H * k), 0)
    _closed(ImageDraw.Draw(m), sc(outer), 255, int(5 * k))
    m = m.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(5))
    base = Image.alpha_composite(base, _masked(g, m.point(lambda v: min(255, int(v * 0.9)))))

    # خط‌های قاب
    m1 = Image.new("L", (W * k, H * k), 0)
    _closed(ImageDraw.Draw(m1), sc(outer), 255, max(2, int(2.2 * k)))
    m1 = m1.resize((W, H), Image.LANCZOS)
    base = Image.alpha_composite(base, _masked(g, m1))

    g_soft = gradient(W, H, [mixh(p, c["bg"], 0.6) for p in palette])
    m2 = Image.new("L", (W * k, H * k), 0)
    _closed(ImageDraw.Draw(m2), sc(inner), 255, max(1, int(1.1 * k)))
    m2 = m2.resize((W, H), Image.LANCZOS)
    base = Image.alpha_composite(base, _masked(g_soft, m2))

    lay = Image.new("RGBA", (W * k, H * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    u = k

    tab = [(20, 14), (tab_w - 34, 14), (tab_w, 50), (20, 50)]
    d.polygon(sc(tab), fill=rgb(c["panel"]) + (255,))
    _closed(d, sc(tab), mixc(palette[0], c["panel"], 0.45) + (255,), int(1.6 * u))

    d.rounded_rectangle([v * k for v in (22, 60, W - 22, H - 24)], radius=int(14 * u),
                        fill=rgb(c["panel"]) + (255,), outline=rgb(c["border"]) + (255,),
                        width=max(1, int(1.2 * u)))

    icon_logo(d, 50 * k, 32 * k, u, c)

    col2 = rgb(c["accent2"]) + (255,)
    bx, by = W - 80, 32
    _capline(d, [((bx - 7) * k, by * k), ((bx + 7) * k, by * k)], col2, 2.4 * u)
    bx, by = W - 48, 32
    _capline(d, [((bx - 7) * k, (by - 7) * k), ((bx + 7) * k, (by + 7) * k)], col2, 2.4 * u)
    _capline(d, [((bx + 7) * k, (by - 7) * k), ((bx - 7) * k, (by + 7) * k)], col2, 2.4 * u)

    lay = lay.resize((W, H), Image.LANCZOS)
    return Image.alpha_composite(base, lay).convert("RGB")


# ----------------------------------------------------------------------
#  ویجت‌های هم‌سبک
# ----------------------------------------------------------------------
def make_button(parent, text, cmd, color, fg="#06101b", size=10, padx=14, pady=6):
    hover = mixh(color, "#ffffff", 0.22)
    b = tk.Button(parent, text=text, command=cmd, bg=color, fg=fg, activebackground=hover,
                  activeforeground=fg, relief="flat", bd=0, padx=padx, pady=pady,
                  font=("Segoe UI", size, "bold"), cursor="hand2")
    b.bind("<Enter>", lambda e: b.configure(bg=hover))
    b.bind("<Leave>", lambda e: b.configure(bg=color))
    return b


def _ctrl_keys(w):
    """Ctrl+C / Ctrl+V / Ctrl+A با هر زبان کیبورد (فارسی هم) کار کند."""
    def h(e):
        if e.keycode == 86:
            w.event_generate("<<Paste>>")
            return "break"
        if e.keycode == 67:
            w.event_generate("<<Copy>>")
            return "break"
        if e.keycode == 65:
            if isinstance(w, tk.Text):
                w.tag_add("sel", "1.0", "end-1c")
            else:
                w.select_range(0, "end")
            return "break"
    w.bind("<Control-KeyPress>", h)


def make_entry(parent, c, font=("Consolas", 12, "bold"), justify="left", **kw):
    e = tk.Entry(parent, bg=c["input"], fg=c["text"], insertbackground=c["text"], relief="flat",
                 highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"],
                 disabledbackground=c["input"], readonlybackground=c["input"],
                 font=font, justify=justify, **kw)
    _ctrl_keys(e)
    return e


def make_text(parent, c, height=3, font=("Consolas", 11, "bold")):
    t = tk.Text(parent, height=height, wrap="char", bg=c["input"], fg=c["text"],
                insertbackground=c["text"], relief="flat", highlightthickness=1,
                highlightbackground=c["border"], highlightcolor=c["accent"], font=font,
                padx=8, pady=6)
    _ctrl_keys(t)
    return t


# ----------------------------------------------------------------------
#  پنجره بی‌قاب نئونی
# ----------------------------------------------------------------------
class NeonWindow:
    def __init__(self, W, H, c, palette, title=("Hack Sikim ", "Robbery"), title_colors=None):
        from PIL import ImageTk
        self.W, self.H, self.c = W, H, c
        self.root = tk.Tk()
        self.root.title(title[0] + title[1])
        x = (self.root.winfo_screenwidth() - W) // 2
        y = (self.root.winfo_screenheight() - H) // 2
        self.root.geometry(f"{W}x{H}+{x}+{y}")
        self.root.overrideredirect(True)
        self.root.configure(bg=c["bg"])

        self.canvas = tk.Canvas(self.root, width=W, height=H, bg=c["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._img = ImageTk.PhotoImage(render_frame(W, H, c, palette))
        self.canvas.create_image(0, 0, image=self._img, anchor="nw")

        f1 = tkfont.Font(family="Segoe UI", size=17, weight="bold", slant="italic")
        tx, ty = 82, 32
        self.canvas.create_text(tx, ty, text=title[0], anchor="w", fill=c["text"], font=f1)
        self.canvas.create_text(tx + f1.measure(title[0]), ty, text=title[1], anchor="w",
                                fill=c["accent"], font=f1)

        self._drag = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.canvas.bind("<Motion>", self._motion)
        self.hits = [((W - 80 - 15, 17, W - 80 + 15, 47), self.minimize),
                     ((W - 48 - 15, 17, W - 48 + 15, 47), self.close)]
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self._fix_taskbar)

    # -- events
    def _inside(self, b, x, y):
        return b[0] <= x <= b[2] and b[1] <= y <= b[3]

    def _press(self, e):
        for box, cmd in self.hits:
            if self._inside(box, e.x, e.y):
                cmd()
                return
        if e.y < 58:
            self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _move(self, e):
        if self._drag:
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _motion(self, e):
        hand = any(self._inside(b, e.x, e.y) for b, _ in self.hits)
        self.canvas.configure(cursor="hand2" if hand else "")

    # -- window
    def minimize(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 6)
        except Exception:
            self.root.withdraw()
            self.root.after(300, self.root.deiconify)

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def _apply_region(self):
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            W, H, cut = self.W, self.H, 24
            pts = [(cut, 0), (W - cut, 0), (W, cut), (W, H - cut),
                   (W - cut, H), (cut, H), (0, H - cut), (0, cut)]
            arr = (POINT * len(pts))(*[POINT(x, y) for x, y in pts])
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            rgn = ctypes.windll.gdi32.CreatePolygonRgn(arr, len(pts), 1)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def _fix_taskbar(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)
            style = (style & ~0x00000080) | 0x00040000
            user32.SetWindowLongW(hwnd, -20, style)
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
        except Exception:
            pass
        self.root.after(80, self._apply_region)

    # -- helpers
    def text(self, x, y, text, size=10, bold=False, color=None, anchor="center", width=None, justify="center"):
        kw = {}
        if width:
            kw["width"] = width
        return self.canvas.create_text(x, y, text=text, anchor=anchor, fill=color or self.c["text"],
                                       font=("Segoe UI", size, "bold" if bold else "normal"),
                                       justify=justify, **kw)

    def divider(self, y, x1=60, x2=None, color=None):
        x2 = x2 or self.W - 60
        col = color or self.c["accent"]
        self.canvas.create_line(x1, y, x2, y, fill=mixh(col, self.c["panel"], 0.5), width=2)
        self.canvas.create_oval((x1 + x2) / 2 - 3, y - 3, (x1 + x2) / 2 + 3, y + 3,
                                fill=self.c["accent2"], outline="")

    def copy_to_clipboard(self, s):
        self.root.clipboard_clear()
        self.root.clipboard_append(s)
        self.root.update()

    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------------
#  پنجره فعال‌سازی (برنامه اصلی)
# ----------------------------------------------------------------------
def activation_window(theme, notice=""):
    """True اگر کاربر لایسنس معتبر فعال کرد."""
    c = theme
    W, H = 640, 500
    win = NeonWindow(W, H, c, [c["accent"]])
    root, px = win.root, 46
    pw = W - 2 * px
    result = {"ok": False}
    hwid = lc.get_hwid()
    ERR, OK = "#ff5d6c", "#20e58a"

    win.text(W / 2, 92, "فعال‌سازی لایسنس", 15, True)
    win.divider(112)

    win.text(W - px, 138, "شناسه دستگاه (HWID) شما", 10, True, c["accent2"], "e")
    ent = make_entry(root, c, justify="center")
    ent.insert(0, hwid)
    ent.configure(state="readonly")
    ent.place(x=px, y=152, width=pw - 104, height=38)

    def copy_hwid():
        win.copy_to_clipboard(hwid)
        btn_copy.configure(text="کپی شد ✓")
        root.after(1500, lambda: btn_copy.configure(text="کپی کردن"))

    btn_copy = make_button(root, "کپی کردن", copy_hwid, c["accent"])
    btn_copy.place(x=px + pw - 96, y=152, width=96, height=38)

    win.text(W - px, 218, "این شناسه را کپی کنید و برای فروشنده بفرستید تا کلید لایسنس مخصوص دستگاه شما صادر شود.",
             9, False, c["muted"], "e", width=pw, justify="right")

    win.text(W - px, 262, "کلید لایسنس", 10, True, c["accent2"], "e")
    key_box = make_text(root, c, height=3)
    key_box.place(x=px, y=278, width=pw, height=84)

    def paste():
        try:
            key_box.delete("1.0", "end")
            key_box.insert("1.0", root.clipboard_get().strip())
        except Exception:
            pass

    make_button(root, "چسباندن", paste, c["card2"], c["text"], 9, 10, 3).place(x=px, y=246, width=84, height=24)
    key_box.bind("<Button-3>", lambda e: paste())

    status = win.text(W / 2, 436, notice, 10, True, ERR if notice else c["muted"], width=pw)

    def set_status(msg, color):
        win.canvas.itemconfigure(status, text=msg, fill=color)

    def do_activate():
        try:
            info = lc.activate(key_box.get("1.0", "end"))
        except lc.LicenseError as e:
            set_status(str(e), ERR)
            return
        set_status(f"فعال شد ✓   کاربر: {info['user'] or '-'}   |   اعتبار: {lc.fmt_left(info)}", OK)
        result["ok"] = True
        root.after(1100, win.close)

    make_button(root, "فعال‌سازی", do_activate, c["accent"], size=12, pady=8).place(x=px, y=376, width=pw, height=44)

    win.canvas.create_text(36 + 8, H - 44, text="Created by Atila", anchor="w", fill=c["accent2"],
                           font=("Segoe UI", 12, "bold"))
    win.run()
    return result["ok"]


def ensure_license(theme):
    """
    اگر لایسنس معتبر ذخیره شده باشد مستقیم وارد می‌شود (بدون پرسیدن کلید).
    در غیر این صورت پنجره فعال‌سازی نشان داده می‌شود.
    خروجی: info یا None (کاربر منصرف شد).
    """
    ok, info, msg = lc.check_saved()
    if ok:
        return info
    if activation_window(theme, msg):
        ok, info, _ = lc.check_saved()
        return info if ok else None
    return None

import sys as _sys
lc = license_core = license_ui = _sys.modules[__name__]


def main():
    # اول لایسنس: اگر قبلاً فعال شده مستقیم وارد می‌شود، وگرنه پنجره فعال‌سازی
    _theme = load_config().get("theme", "blue")
    _theme = FastOCR.THEMES.get(_theme, FastOCR.THEMES["blue"])
    _info = license_ui.ensure_license(_theme)
    if _info is None:
        return
    app = FastOCR(_info)
    app.run()


if __name__ == "__main__":
    main()
