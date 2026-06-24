import os
import re
import sys
import subprocess
import glob
import json
import time
import uuid
import shutil
import random
import socket
import base64
import hashlib
import struct
import io
import threading
import urllib.request
import urllib.error
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

# Drag'n'Drop support (native, stable file-drop from Explorer/Finder).
# The whole app must still run if the package is missing — DnD is then
# simply unavailable and the placeholder falls back to click-to-browse only.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

# Pillow: image conversion / resizing / preview rendering.
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False

# Image files we accept for upload / drag'n'drop.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
# Optimized storage format/extension for converted library images.
IMAGE_STORE_EXT = ".jpg"
# Library images are scaled so their longest side equals this many pixels.
IMAGE_MAX_SIDE = 1024
# Sidecar JSON file (named after the entry, like the image file) that holds
# per-entry metadata not suited to the plain-text tags file: Source URL
# (Task 6) and LoRA binding (Task 7.1).
LIBRARY_META_EXT = ".meta.json"

# ===================== ComfyUI integration constants =====================
# Contract between Prompt Forge and the companion custom node
# (promptforgeconnection.py). The node's class_type in any workflow graph
# MUST match this string — that's the only thing the two sides agree on.
COMFY_NODE_CLASS_TYPE = "PromptForgeConnection"
COMFY_DEFAULT_HOST = "127.0.0.1"
COMFY_DEFAULT_PORT = 8188
COMFY_HTTP_TIMEOUT = 6          # seconds, for quick calls (health check, /prompt submit)
COMFY_POLL_INTERVAL = 1.0       # seconds between /history polls while a job runs
COMFY_POLL_TIMEOUT = 300        # seconds — give up waiting on a single generation after this
COMFY_GRAPH_PATH = "/promptforge/graph"  # served by the node's Python bridge
COMFY_LORAS_PATH = "/promptforge/loras"  # returns available LoRA file list

# Maximum LoRA slots the app UI exposes — must be ≤ LORA_SLOTS in nodes.py.
MAX_LORA_SLOTS = 30
# Sentinel value meaning "slot empty / skip" — must match LORA_NONE in nodes.py.
LORA_NONE_VALUE = "None"
# Allowed strength range — must match LORA_STRENGTH_MIN/MAX in nodes.py.
LORA_STRENGTH_MIN = -16.0
LORA_STRENGTH_MAX = 16.0
# Common resolutions offered in the Builder's ComfyUI panel (width, height).
COMFY_RESOLUTION_PRESETS = [
    ("Square (1024x1024)", 1024, 1024),
    ("Portrait (832x1216)", 832, 1216),
    ("Landscape (1216x832)", 1216, 832),
    ("Portrait (896x1152)", 896, 1152),
    ("Landscape (1152x896)", 1152, 896),
    ("Custom…", None, None),
]

# ===================== Gallery (Task 3) constants =====================
# Square thumbnail budget for each Gallery cell — actual images are fit
# inside this box via Pillow's thumbnail() (aspect ratio preserved, no
# cropping/distortion).
GALLERY_THUMB_SIZE = 256
# Outer footprint of one cell (thumbnail + its own padding) used to work
# out how many columns fit in the current canvas width when the Gallery
# tab is resized.
GALLERY_CELL_OUTER_WIDTH = GALLERY_THUMB_SIZE + 36

# Enable High DPI support on Windows before initializing the interface
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass  # If the OS is not Windows or the library is unavailable


def app_dir():
    """Folder that contains the running script, or — when packaged with
    PyInstaller — the folder that contains the .exe. Used to find files that
    must sit next to the program (the icon, the data folder, etc.) no matter
    whether the app is run as a .py file or as a compiled executable."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# ==========================================================
#                        COLOR THEMES
# ==========================================================
THEMES = {
    "dark": {
        "bg":            "#1e1f26",
        "bg_alt":        "#262830",
        "bg_card":       "#2b2d37",
        "bg_input":      "#1a1b21",
        "fg":            "#e8e9ed",
        "fg_dim":        "#9a9cab",
        "accent":        "#7c8cff",
        "accent_hover":  "#919fff",
        "accent_text":   "#ffffff",
        "border":        "#3a3c48",
        "success":       "#4caf7d",
        "danger":        "#e5645f",
        "danger_hover":  "#f07b76",
        "warn":          "#e0a84e",
        "select_bg":     "#3a3d52",
        "tree_bg":       "#21222a",
        "tree_alt":      "#262832",
    },
    "light": {
        "bg":            "#f4f5f8",
        "bg_alt":        "#ffffff",
        "bg_card":       "#ffffff",
        "bg_input":      "#ffffff",
        "fg":            "#21222b",
        "fg_dim":        "#6b6d7a",
        "accent":        "#5566e8",
        "accent_hover":  "#4453d4",
        "accent_text":   "#ffffff",
        "border":        "#d8dae2",
        "success":       "#2f9d63",
        "danger":        "#d6453f",
        "danger_hover":  "#c43631",
        "warn":          "#c5860f",
        "select_bg":     "#e2e5fb",
        "tree_bg":       "#ffffff",
        "tree_alt":      "#f3f4fa",
    },
}

CATEGORY_LABELS = {
    "styles": "Style",
    "scenarios": "Scenario",
    "characters": "Character",
    "outfits": "Outfit",
}

CATEGORY_ICONS = {
    "styles": "🎨",
    "scenarios": "🎬",
    "characters": "🧑",
    "outfits": "👕",
}

PREFIXES = ["First:", "Second:", "Third:", "Fourth:", "Fifth:", "Sixth:", "Seventh:", "Eighth:"]

INVALID_FS_CHARS = r'[\\/:*?"<>|]'

# Custom template variables are written directly in the template text as
# "[Name 1]", "[Description 2]", "[Outfit 1]", "[Style]", "[Scenario]".
# The number after "Name"/"Description"/"Outfit" ties the variable to a
# specific "template character" (slot) — the same one for all three variable types.
CUSTOM_VAR_PATTERN = re.compile(r"\[(Name|Description|Outfit)\s+(\d+)\]|\[(Style)\]|\[(Scenario)\]")


def sanitize_filename(name: str) -> str:
    """Strips characters that are invalid in file names."""
    return re.sub(INVALID_FS_CHARS, "_", name).strip()


class Tooltip:
    """A simple tooltip for a widget."""
    def __init__(self, widget, text, app):
        self.widget = widget
        self.text = text
        self.app = app
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        c = self.app.colors
        lbl = tk.Label(self.tip, text=self.text, justify="left",
                        background=c["bg_card"], foreground=c["fg"],
                        relief="solid", borderwidth=1,
                        font=("Segoe UI", 9), padx=8, pady=4)
        lbl.pack()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class _ImageCanvasBase(tk.Canvas):
    """Shared rounded-rect / placeholder / proportional-fit drawing logic
    for both the interactive Library drop zone and the read-only ComfyUI
    result viewer. Not used directly."""

    MIN_PERCENT = 12
    MAX_PERCENT = 65
    DEFAULT_PERCENT = 38
    MIN_PX = 130
    MAX_PX = 1400

    def __init__(self, master, colors, percent=None, **kwargs):
        self.colors = colors
        self.percent = percent if percent else self.DEFAULT_PERCENT
        bg = colors["bg_card"]
        super().__init__(master, bg=bg, highlightthickness=0, bd=0,
                          height=self.MIN_PX, **kwargs)

        self._pil_image = None
        self._tk_image = None
        self._has_image = False
        self._last_panel_height = 0

        self.bind("<Configure>", lambda e: self._redraw())
        self._redraw()

    # ---------------------------------------------------------- public --
    def set_colors(self, colors):
        self.colors = colors
        self.configure(bg=colors["bg_card"])
        self._redraw()

    def set_percent(self, percent):
        self.percent = max(self.MIN_PERCENT, min(self.MAX_PERCENT, percent))
        if self._last_panel_height:
            self.apply_panel_height(self._last_panel_height)

    def apply_panel_height(self, panel_height):
        """Sets the canvas's pixel height to `percent` of `panel_height`,
        clamped to [MIN_PX, MAX_PX] for normal usability — but never
        exceeding `panel_height` itself.

        That last clamp matters: `panel_height` is the caller's actual
        available budget (e.g. _resize_comfy_result_zone passes in
        "what's left after the slider row / status row / Open folder
        button"). If that budget is itself smaller than MIN_PX — a very
        short window — flooring at MIN_PX regardless would claim more
        space than exists and push those other rows out of view again,
        which is the exact bug this whole panel_height/chrome scheme
        exists to prevent. So the hard ceiling is whichever is smaller:
        MAX_PX, or the budget we were actually given.
        """
        self._last_panel_height = panel_height
        target = int(panel_height * (self.percent / 100.0))
        ceiling = min(self.MAX_PX, max(panel_height, 1))
        target = max(min(self.MIN_PX, ceiling), min(target, ceiling))
        if abs(target - self.winfo_height()) > 1:
            self.configure(height=target)
            self._redraw()

    def show_placeholder(self):
        self._pil_image = None
        self._tk_image = None
        self._has_image = False
        self._redraw()

    def show_image_path(self, path):
        if not PIL_AVAILABLE or not path or not os.path.exists(path):
            self.show_placeholder()
            return
        try:
            img = Image.open(path)
            img.load()
            self._pil_image = img.convert("RGB")
            self._has_image = True
            self._redraw()
        except Exception:
            self.show_placeholder()

    def show_image_bytes(self, img_bytes):
        """Like show_image_path, but for an in-memory encoded image (JPEG/
        PNG) rather than a file on disk — used for live TAESD/latent
        preview frames streamed over ComfyUI's websocket during sampling,
        which never touch the filesystem.

        Deliberately does NOT fall back to show_placeholder() on failure:
        these frames arrive in a rapid stream mid-generation, so a single
        truncated/corrupt one should just be skipped, leaving whatever
        was already on screen, rather than flashing the placeholder.
        """
        if not PIL_AVAILABLE or not img_bytes:
            return
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img.load()
            self._pil_image = img.convert("RGB")
            self._has_image = True
            self._redraw()
        except Exception:
            pass

    # ------------------------------------------------------------ draw --
    def _redraw(self):
        self.delete("all")
        w = max(self.winfo_width(), 10)
        h = max(self.winfo_height(), 10)
        c = self.colors

        if self._has_image and self._pil_image is not None:
            self._draw_image(w, h)
        else:
            self._draw_placeholder(w, h, c)

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _draw_placeholder(self, w, h, c):
        """Overridden by subclasses for their specific placeholder text."""
        raise NotImplementedError

    def _draw_image(self, w, h, max_area_ratio=0.92):
        # max_area_ratio used to be 0.60, which capped the *picture* at
        # 60% of the canvas's area no matter how tall the canvas itself
        # grew. Combined with width also being a limiting factor for
        # portrait-ish images, that made the "Size" slider feel broken
        # near its upper end — moving it kept growing the (invisible)
        # canvas but the visible picture barely changed. 0.92 leaves a
        # thin border around the image while letting it actually fill
        # the space the slider asked for.
        c = self.colors
        margin = 6
        self._round_rect(margin, margin, w - margin, h - margin, radius=18,
                          fill=c["bg_card"], outline="")

        avail_w = max(w - margin * 2, 10)
        avail_h = max(h - margin * 2, 10)

        img_w, img_h = self._pil_image.size
        fit_scale = min(avail_w / img_w, avail_h / img_h)
        fitted_w, fitted_h = img_w * fit_scale, img_h * fit_scale

        budget_area = avail_w * avail_h * max_area_ratio
        fitted_area = fitted_w * fitted_h
        if fitted_area > budget_area and fitted_area > 0:
            area_scale = (budget_area / fitted_area) ** 0.5
            fitted_w *= area_scale
            fitted_h *= area_scale

        fitted_w = max(int(fitted_w), 1)
        fitted_h = max(int(fitted_h), 1)

        try:
            resized = self._pil_image.resize((fitted_w, fitted_h), Image.LANCZOS)
            self._tk_image = ImageTk.PhotoImage(resized)
        except Exception:
            self.show_placeholder()
            return

        self.create_image(w / 2, h / 2, image=self._tk_image, anchor="center")


class ImageDropZone(_ImageCanvasBase):
    """A rounded, dashed-border preview/drop zone for a library entry's image.

    Two visual states:
      * empty   -> centered "UPLOAD IMAGE / DRAG'N DROP" placeholder text
                   inside a soft dashed rounded rectangle.
      * filled  -> the loaded image, proportionally scaled to fit within
                   the zone (capped at ~60% of the editor panel's area) and
                   centered both horizontally and vertically.

    Interactions:
      * Click anywhere in the zone -> filedialog.askopenfilename(...)
      * Drag'n'drop a file onto the zone (if tkinterdnd2 is available) ->
        same handling path as a manual file pick.

    The zone itself never touches disk — it only reports the picked path
    via the `on_file_chosen` callback; the owner (PromptForgeApp) decides
    what to do with it (convert, resize, save, attach to the right entry).
    """

    def __init__(self, master, colors, on_file_chosen, percent=None, **kwargs):
        self.on_file_chosen = on_file_chosen
        super().__init__(master, colors, percent=percent, **kwargs)

        self.bind("<Button-1>", self._on_click)
        self.configure(cursor="hand2")

        if DND_AVAILABLE:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    # --------------------------------------------------------- internal --
    def _on_click(self, _event=None):
        filetypes = [
            ("Image files", " ".join(f"*{ext}" for ext in IMAGE_EXTENSIONS)),
            ("All files", "*.*"),
        ]
        path = filedialog.askopenfilename(title="Choose an image", filetypes=filetypes)
        if path:
            self.on_file_chosen(path)

    def _on_drop(self, event):
        raw = event.data
        path = self._first_path_from_dnd_data(raw)
        if path and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
            self.on_file_chosen(path)
        elif path:
            messagebox.showwarning("Unsupported file",
                                    "Please drop an image file (jpg, png, webp, bmp, gif).")

    @staticmethod
    def _first_path_from_dnd_data(data):
        """tkinterdnd2 wraps paths with braces if they contain spaces, and
        can deliver several paths separated by spaces. We only care about
        the first one."""
        data = data.strip()
        if data.startswith("{"):
            end = data.find("}")
            if end != -1:
                return data[1:end]
        return data.split()[0] if data else ""

    # ------------------------------------------------------------ draw --
    def _draw_placeholder(self, w, h, c):
        margin = 6
        self._round_rect(margin, margin, w - margin, h - margin, radius=18,
                          fill=c["bg_card"], outline="")

        # Dashed rounded border, drawn as an inset rectangle with a dash
        # pattern (Tkinter's create_polygon doesn't support dash directly
        # with smooth corners reliably across platforms, so a rectangle
        # with dash is used for the border itself for crisp dashes).
        inset = 14
        self.create_rectangle(
            margin + inset, margin + inset, w - margin - inset, h - margin - inset,
            outline=c["border"], width=2, dash=(6, 4)
        )

        cx, cy = w / 2, h / 2
        icon_r = 16
        self.create_oval(cx - icon_r, cy - icon_r - 28, cx + icon_r, cy + icon_r - 28,
                          outline=c["fg_dim"], width=2)
        self.create_line(cx, cy - 28 - 7, cx, cy - 28 + 7, fill=c["fg_dim"], width=2)
        self.create_line(cx - 7, cy - 28, cx + 7, cy - 28, fill=c["fg_dim"], width=2)

        font_main = ("Segoe UI", 13, "bold")
        font_sub = ("Segoe UI", 9)
        self.create_text(cx, cy + 6, text="UPLOAD IMAGE", fill=c["fg_dim"], font=font_main)
        self.create_text(cx, cy + 28, text="drag \u2019n drop or click to browse",
                          fill=c["fg_dim"], font=font_sub)


class ResultImageViewer(_ImageCanvasBase):
    """Read-only counterpart to ImageDropZone — no click-to-browse, no
    drag'n'drop. Used in the Builder tab to show the latest image that
    came back from a ComfyUI generation. The same proportional-fit /
    rounded-card drawing as the Library preview, just a different (and
    much plainer) empty-state placeholder.

    Overrides the inherited percent range: this viewer sits in its own
    full-height pane (the whole right-hand column of the Builder tab),
    not squeezed alongside a tags box and a handful of form fields like
    the Library zone is, so it can comfortably grow much larger.
    """

    MIN_PERCENT = 15
    MAX_PERCENT = 68
    DEFAULT_PERCENT = 45

    def _draw_placeholder(self, w, h, c):
        margin = 6
        self._round_rect(margin, margin, w - margin, h - margin, radius=18,
                          fill=c["bg_card"], outline="")
        cx, cy = w / 2, h / 2
        self.create_text(cx, cy, text="No image generated yet",
                          fill=c["fg_dim"], font=("Segoe UI", 10))


class AutocompleteCombobox(ttk.Combobox):
    """Drop-in replacement for ttk.Combobox with inline, case-insensitive
    substring search. As the user types, a small popup list appears right
    below the field, live-filtered to items whose name contains the typed
    text anywhere (not just at the start). Arrow keys move the highlighted
    row; clicking a row or pressing <Return> on a highlighted row commits
    it instantly. The typed value is otherwise locked in on <Return> or
    when the widget loses focus:
      * an exact match (case-insensitive) is normalized to the value's
        canonical stored case and committed;
      * an empty field resolves to "None";
      * unrecognized text falls back to the last validly committed value.

    Why this version exists: the previous implementation tried to reuse
    ttk's native "ttk::combobox::Post" popdown for live filtering. That
    popdown installs a *global grab* on its own internal listbox, which
    silently steals keyboard focus away from this Entry after the very
    first keystroke. So every keystroke after the first never reached
    `_on_keyrelease`, and the widget behaved like a perfectly ordinary,
    unfiltered Combobox (exactly the "no search, just a dropdown" symptom).
    This version never touches the native popdown for typing; instead it
    manages its own borderless Toplevel + Listbox popup that is engineered
    to never take keyboard focus, so the Entry keeps receiving every key
    the user presses.

    Stays API-compatible with ttk.Combobox (combo["values"] = [...],
    .current(), <<ComboboxSelected>>), so existing code that manipulates
    the combobox elsewhere in the app keeps working unchanged.
    """

    def __init__(self, master=None, **kwargs):
        kwargs["state"] = "normal"  # typing requires an editable entry
        super().__init__(master, **kwargs)
        self._all_values = list(kwargs.get("values", ()))
        self._last_committed = self.get()
        self._popup = None
        self._listbox = None
        self._popup_values = []

        self.bind("<Button-1>", self._on_click, add="+")
        self.bind("<KeyRelease>", self._on_keyrelease, add="+")
        self.bind("<KeyPress-Down>", self._on_arrow, add="+")
        self.bind("<KeyPress-Up>", self._on_arrow, add="+")
        self.bind("<Return>", self._on_return, add="+")
        self.bind("<Escape>", self._close_popup, add="+")
        self.bind("<FocusOut>", self._on_focus_out, add="+")
        self.bind("<Destroy>", self._close_popup, add="+")
        self.bind("<<ComboboxSelected>>", self._on_picked, add="+")

    # Keep our master copy of the unfiltered list in sync whenever calling
    # code does combo["values"] = [...] (used throughout the app).
    def __setitem__(self, key, value):
        if key == "values":
            self._all_values = list(value)
        super().__setitem__(key, value)

    def configure(self, cnf=None, **kwargs):
        merged = dict(cnf) if cnf else {}
        merged.update(kwargs)
        if "values" in merged:
            self._all_values = list(merged["values"])
        return super().configure(cnf, **kwargs)

    config = configure

    # ------------------------------------------------------------- popup --
    def _style_colors(self):
        # Pull live colors from styles the app already configures (see
        # PromptForgeApp's theme setup), so the popup matches dark/light
        # theme without this generic widget needing to know about the app.
        style = ttk.Style(self)
        bg = (style.lookup("Card.TFrame", "background")
              or style.lookup("TCombobox", "fieldbackground") or "#1a1b21")
        fg = style.lookup("TCombobox", "foreground") or style.lookup("TEntry", "foreground") or "#e6e6e6"
        accent = style.lookup("Accent.TButton", "background") or "#6c5ce7"
        accent_fg = style.lookup("Accent.TButton", "foreground") or "#ffffff"
        return bg, fg, accent, accent_fg

    def _open_popup(self, matches):
        self._close_popup()
        if not matches:
            return
        self._popup_values = matches
        bg, fg, accent, accent_fg = self._style_colors()

        popup = tk.Toplevel(self)
        popup.withdraw()
        popup.overrideredirect(True)   # no titlebar/borders, no WM focus
        try:
            popup.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        # The border lives on the popup itself, and the popup's own
        # background matches the listbox's exactly. That way, if rounding
        # (e.g. on HiDPI/fractional display scaling) leaves a stray sliver
        # between the listbox and the popup edge, it's the same color as
        # the listbox and invisible -- rather than a mismatched strip.
        popup.configure(bg=bg, highlightthickness=1,
                         highlightbackground=accent, highlightcolor=accent)

        # Cap how many rows show at once before the (native, mouse-wheel
        # scrollable) Listbox needs to scroll -- generous enough to show a
        # full small library without needing to scroll for it.
        visible_rows = max(1, min(len(matches), 10))
        listbox = tk.Listbox(popup, exportselection=False, activestyle="none",
                              height=visible_rows, highlightthickness=0,
                              bg=bg, fg=fg, selectbackground=accent,
                              selectforeground=accent_fg, relief="flat",
                              borderwidth=0, takefocus=0)
        listbox.pack(fill="both", expand=True, padx=1, pady=1)
        for v in matches:
            listbox.insert(tk.END, v)
        listbox.selection_set(0)
        listbox.activate(0)

        # Intercept the click at the widget level (binds run before the
        # default "Listbox" class bindings) and return "break" so the
        # built-in click binding -- which would call focus(%W) and steal
        # keyboard focus from the Entry -- never runs.
        listbox.bind("<ButtonPress-1>", self._on_listbox_press)
        listbox.bind("<ButtonRelease-1>", lambda e: "break")

        self.winfo_toplevel().update_idletasks()
        popup.update_idletasks()
        # Ask Tk how tall `visible_rows` actually render -- this already
        # accounts for the active font size and the display's DPI/scaling
        # factor, instead of guessing a fixed pixel-per-row value that only
        # holds at 100% scaling (which was cutting the popup off after ~2
        # rows on HiDPI screens, even though more matches existed).
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        width = max(self.winfo_width(), 120)
        height = listbox.winfo_reqheight() + 2
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.deiconify()

        self._popup = popup
        self._listbox = listbox

    def _close_popup(self, _event=None):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
        self._popup = None
        self._listbox = None
        self._popup_values = []

    def _on_listbox_press(self, event):
        if self._listbox is not None:
            index = self._listbox.nearest(event.y)
            if 0 <= index < len(self._popup_values):
                self._pick(self._popup_values[index])
        return "break"  # swallow the event: never let the listbox take focus

    def _on_arrow(self, event):
        if self._listbox is None:
            # Dropdown not open yet (e.g. pressed Down with nothing typed) --
            # open it with whatever is currently typed, same as a keystroke.
            self._on_keyrelease(event)
            return "break"
        size = len(self._popup_values)
        if size == 0:
            return "break"
        current = self._listbox.curselection()
        idx = current[0] if current else -1
        idx = (idx + (1 if event.keysym == "Down" else -1)) % size
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(idx)
        self._listbox.activate(idx)
        self._listbox.see(idx)
        return "break"  # don't let the Entry move its own cursor on Up/Down

    def _pick(self, value):
        self.set(value)
        self.icursor(tk.END)
        self._last_committed = value
        self._close_popup()
        self.focus_set()
        self.event_generate("<<ComboboxSelected>>")

    def _on_picked(self, _event=None):
        # Fired both by our own _pick() and by any external code that
        # still does combo.current(i) / combo.set(...) directly.
        self._last_committed = self.get()

    # -------------------------------------------------------------- click --
    def _on_click(self, _event=None):
        # A single click anywhere on the widget -- the text area *or* the
        # little dropdown arrow on the right -- should immediately show
        # the FULL list (exactly like clicking a normal Combobox), with
        # substring search available simply by typing while it's open.
        # Returning "break" stops ttk's own class-level click handling,
        # which is what used to post the native, unsearchable popdown
        # whenever the arrow specifically was clicked.
        self.focus_set()
        self.selection_range(0, tk.END)
        self.icursor(tk.END)
        self._open_popup(list(self._all_values))
        return "break"

    # --------------------------------------------------------- filtering --
    def _on_keyrelease(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "ISO_Left_Tab"):
            return
        typed = self.get()
        if typed:
            needle = typed.lower()
            matches = [v for v in self._all_values if needle in v.lower()]
        else:
            matches = list(self._all_values)
        self._open_popup(matches)

    # ------------------------------------------------------------ commit --
    def _on_return(self, _event=None):
        # If a row is highlighted in an open popup, <Return> commits THAT
        # row. Otherwise fall back to plain exact-text matching.
        if self._popup is not None and self._listbox is not None:
            sel = self._listbox.curselection()
            if sel:
                self._pick(self._popup_values[sel[0]])
                return "break"
        self._close_popup()
        self._finalize()
        return "break"

    def _on_focus_out(self, _event=None):
        # Losing focus never auto-picks a merely-highlighted popup row --
        # only an explicit click or <Return> does that (see _on_return /
        # _on_listbox_press). Blur just closes the popup and falls back
        # to exact-text matching / "None", same as before.
        #
        # BUT: clicking a row in the popup means clicking a *different*
        # top-level window. On some platforms that yanks OS input focus
        # away from this Entry the instant the mouse goes down -- before
        # the click is actually delivered to the listbox as a selection.
        # If we closed the popup synchronously right here, that race made
        # clicking look completely unresponsive (only <Return> ever
        # seemed to work). Deferring by one idle tick lets an in-flight
        # click on the popup run _on_listbox_press first; only if focus
        # genuinely landed somewhere outside our own popup do we close it.
        self.after(1, self._resolve_focus_out)

    def _resolve_focus_out(self):
        if self._popup is not None:
            try:
                focused = self.tk.call("focus")
            except tk.TclError:
                focused = ""
            if focused and str(focused).startswith(str(self._popup)):
                return  # focus is inside our own popup -- let the click finish
        self._close_popup()
        self._finalize()

    def _finalize(self):
        typed = self.get().strip()
        previous = self._last_committed

        if not typed:
            final_value = "None"
        else:
            final_value = previous
            for value in self._all_values:
                if value.lower() == typed.lower():
                    final_value = value
                    break

        if self.get() != final_value:
            self.set(final_value)
        self._last_committed = final_value

        if final_value != previous:
            self.event_generate("<<ComboboxSelected>>")


class ComfyUIError(Exception):
    """Raised for any ComfyUI-related failure — connection, missing node,
    bad workflow JSON, generation failure, or timeout. The message is
    meant to be shown to the user as-is."""
    pass


class ComfyUIClient:
    """Thin HTTP client around ComfyUI's REST API. No third-party
    dependencies — uses urllib from the standard library only.

    This class knows nothing about Tkinter; all of its methods are
    blocking and are meant to be called from a background thread. The
    owner (PromptForgeApp) is responsible for threading and for marshaling
    results back to the main thread via root.after(...).

    Protocol contract with the companion custom node
    (promptforgeconnection.py): the live graph is fetched at generation
    time from GET /promptforge/graph (served by the node's Python bridge).
    That graph must contain exactly one node whose "class_type" equals
    COMFY_NODE_CLASS_TYPE. That node's "inputs" dict is patched with
    prompt/seed/width/height before every submission.
    """

    def __init__(self, host=COMFY_DEFAULT_HOST, port=COMFY_DEFAULT_PORT):
        self.host = host
        self.port = port
        # Reused for both the /prompt submission and the /ws progress
        # listener below — ComfyUI ties "progress" events to the
        # client_id a job was submitted under, so both sides must match.
        self.client_id = uuid.uuid4().hex

    @property
    def base_url(self):
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------ HTTP --
    def _get(self, path, timeout=COMFY_HTTP_TIMEOUT):
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ComfyUIError(f"ComfyUI returned an unexpected (non-JSON) response from {path}")

    def _post(self, path, payload, timeout=COMFY_HTTP_TIMEOUT):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            # ComfyUI's /prompt validation errors come back as JSON with a
            # human-readable "error"/"node_errors" structure — surface it.
            detail = body
            try:
                parsed = json.loads(body)
                detail = parsed.get("error", {}).get("message", body) if isinstance(parsed, dict) else body
            except Exception:
                pass
            raise ComfyUIError(f"ComfyUI rejected the request ({e.code}): {detail}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not reach ComfyUI at {self.base_url}: {e.reason}")
        except json.JSONDecodeError:
            raise ComfyUIError(f"ComfyUI returned an unexpected (non-JSON) response from {path}")

    # --------------------------------------------------------- queries --
    def check_connection(self):
        """Health check. Returns the system_stats dict on success, raises
        ComfyUIError otherwise."""
        return self._get("/system_stats")

    def get_output_dir(self):
        """Discovers ComfyUI's real output/ folder via the PromptForgeConnection
        bridge's GET /promptforge/output_dir route (backed server-side by
        folder_paths.get_output_directory()). Standard ComfyUI doesn't expose
        filesystem paths through /system_stats, so this requires the bridge
        node to be installed. Returns None gracefully if it's unavailable —
        the /view HTTP download is the primary image retrieval method and
        doesn't require this path at all."""
        try:
            data = self._get("/promptforge/output_dir")
            out_dir = data.get("output_dir")
            if out_dir:
                return out_dir
        except Exception:
            pass
        return None

    def download_image(self, filename, subfolder="", img_type="output"):
        """Downloads image bytes from ComfyUI's GET /view endpoint.
        Returns raw bytes on success, raises ComfyUIError on failure.
        This works even when we don't know the local output directory path
        (Windows paths, network ComfyUI, subfolders like Anima/, etc.)."""
        import urllib.parse
        params = urllib.parse.urlencode({
            "filename": filename,
            "type": img_type,
            "subfolder": subfolder,
        })
        url = f"{self.base_url}/view?{params}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise ComfyUIError(f"ComfyUI /view returned HTTP {e.code} for {filename}")
        except urllib.error.URLError as e:
            raise ComfyUIError(f"Could not download image from ComfyUI: {e.reason}")

    @staticmethod
    def extract_image_info(history_entry):
        """Extracts (filename, subfolder, type) from the first image in a
        completed /history entry. Returns (None, None, None) if not found."""
        outputs = history_entry.get("outputs", {})
        for node_output in outputs.values():
            images = node_output.get("images")
            if not images:
                continue
            img = images[0]
            filename = img.get("filename")
            if not filename:
                continue
            return filename, img.get("subfolder", ""), img.get("type", "output")
        return None, None, None

    def submit_prompt(self, workflow_graph, preview_method="auto"):
        """Submits a full API-format workflow graph. Returns the
        prompt_id string.

        preview_method is forwarded as extra_data.preview_method. This is
        NOT cosmetic: ComfyUI's PromptExecutor.execute_async() calls
        set_preview_method(extra_data.get("preview_method")) on EVERY
        single /prompt submission, which overwrites the server's global
        live-preview state for this run. If we omit it (as before), the
        server resets preview to whatever --preview-method it was *launched*
        with (default: none) — completely ignoring the Settings > Comfy >
        Execution > "Live preview method" dropdown, because that dropdown's
        value only reaches the server via extra_data when the official
        browser frontend queues a prompt, not when we POST /prompt ourselves.
        "auto" mirrors ComfyUI's own Auto behaviour (taesd-class decoder if
        vae_approx weights are present for this model, else latent2rgb).
        Pass preview_method=None to skip sending it (server falls back to
        its launch default — equivalent to the old, broken behaviour)."""
        payload = {"prompt": workflow_graph, "client_id": self.client_id}
        if preview_method:
            payload["extra_data"] = {"preview_method": preview_method}
        result = self._post("/prompt", payload)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            node_errors = result.get("node_errors")
            if node_errors:
                raise ComfyUIError(f"ComfyUI reported node errors: {node_errors}")
            raise ComfyUIError("ComfyUI accepted the request but returned no prompt_id.")
        return prompt_id

    def get_history(self, prompt_id):
        """Returns the /history entry for prompt_id, or None if it hasn't
        completed (or even started) yet."""
        result = self._get(f"/history/{prompt_id}")
        return result.get(prompt_id)

    def interrupt(self):
        """Tells ComfyUI to abort whatever is *currently executing*
        (POST /interrupt — no body). This only affects the job that's
        actively running on the GPU right now; it does NOT touch other
        jobs still sitting in the queue behind it.

        Note this is unconditional on ComfyUI's side: /interrupt always
        stops whatever the server is currently running, regardless of
        which client/prompt_id submitted it. That's fine for our use
        case (a single local user with one generation in flight), but
        it's the reason we don't bother passing prompt_id here — the
        endpoint doesn't take one."""
        self._post("/interrupt", {})

    def delete_queue_item(self, prompt_id):
        """Removes a not-yet-started job from ComfyUI's queue (POST
        /queue with {"delete": [prompt_id]}). Used as a best-effort
        companion to interrupt(): if our job hadn't started executing
        yet (still waiting behind other queued jobs), /interrupt alone
        wouldn't touch it since it only aborts the currently-running
        job. Failures here are non-fatal — the job may simply have
        already started (in which case interrupt() above is what
        actually stops it) or already finished."""
        self._post("/queue", {"delete": [prompt_id]})

    def wait_for_completion(self, prompt_id, poll_interval=COMFY_POLL_INTERVAL,
                             timeout=COMFY_POLL_TIMEOUT, should_cancel=None,
                             progress_callback=None, preview_callback=None):
        """Blocks (in the caller's thread) polling /history until the job
        finishes. `should_cancel` is an optional zero-arg callable the
        owner can use to abort early (e.g. user closed the app).
        `progress_callback(current_step, total_steps)` is called whenever
        the progress estimate changes. `preview_callback(image_bytes)` is
        called with raw JPEG/PNG bytes whenever ComfyUI streams a live
        preview frame over the WebSocket (TAESD/latent2rgb preview during
        KSampler) — see _listen_progress_ws for the wire format. This is
        purely a function of what ComfyUI itself decides to send: if the
        user has "Live preview method" set to "none" in ComfyUI's own
        Settings, no such frames are ever sent and preview_callback simply
        never fires — there is nothing to toggle on this side.

        Real step-by-step progress (the "20/30" KSampler counter visible
        in ComfyUI's own console) is only ever published over its
        WebSocket as {"type": "progress", "data": {"value", "max"}}
        events — the /queue REST endpoint's queue_running entries carry
        no per-node completion status at all (its 5th element is the list
        of node ids still left to execute, not a list of "done" messages),
        which is why a /queue-only counter gets permanently stuck at
        "0/N". So a background thread keeps a small stdlib-only WebSocket
        connection (see _listen_progress_ws) open for real progress, and
        /queue is kept only as a coarse "N total nodes" fallback for the
        brief window before the first WebSocket progress event arrives
        (e.g. while a checkpoint is still loading)."""
        start = time.time()
        last_progress = (-1, -1)

        ws_progress = {"value": None, "max": None}
        ws_stop = threading.Event()
        ws_thread = threading.Thread(
            target=self._listen_progress_ws,
            args=(prompt_id, ws_progress, ws_stop, preview_callback),
            daemon=True)
        if progress_callback or preview_callback:
            ws_thread.start()

        try:
            while True:
                if should_cancel and should_cancel():
                    raise ComfyUIError("Generation cancelled.")
                if time.time() - start > timeout:
                    raise ComfyUIError(
                        f"Timed out after {timeout}s waiting for ComfyUI to finish. "
                        f"The job may still be running — check ComfyUI directly."
                    )
                entry = self.get_history(prompt_id)
                if entry is not None:
                    status = entry.get("status", {})
                    if status.get("completed"):
                        if progress_callback and last_progress != (-1, -1):
                            progress_callback(last_progress[1], last_progress[1])
                        return entry
                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        raise ComfyUIError(f"ComfyUI reported a generation error: {messages}")

                if progress_callback:
                    value, mx = ws_progress["value"], ws_progress["max"]
                    if value is not None and mx:
                        prog = (value, mx)
                        if prog != last_progress:
                            last_progress = prog
                            progress_callback(value, mx)
                    else:
                        # No WebSocket progress event yet (still loading the
                        # checkpoint, or the socket/handshake failed) — show
                        # at least the total node count from /queue so the
                        # bar isn't completely blank.
                        try:
                            queue_data = self._get("/queue", timeout=2)
                            running = queue_data.get("queue_running", [])
                            for item in running:
                                # item structure: [number, prompt_id, prompt_graph, extra, outputs_to_execute]
                                if len(item) > 1 and item[1] == prompt_id:
                                    graph_dict = item[2] if len(item) > 2 else {}
                                    total_nodes = len(graph_dict) if isinstance(graph_dict, dict) else 0
                                    if total_nodes > 0:
                                        prog = (0, total_nodes)
                                        if prog != last_progress:
                                            last_progress = prog
                                            progress_callback(0, total_nodes)
                                    break
                        except Exception:
                            pass  # progress is best-effort, never fail the main loop

                time.sleep(poll_interval)
        finally:
            ws_stop.set()

    def _listen_progress_ws(self, prompt_id, progress_state, stop_event, preview_callback=None):
        """Background-thread helper for wait_for_completion(): opens a raw
        WebSocket connection to ComfyUI's /ws endpoint (over a plain
        `socket` + a hand-rolled RFC 6455 handshake — no third-party
        dependency such as `websocket-client`) and updates `progress_state`
        in place whenever a {"type": "progress"} message arrives. This is
        the only source of real per-step KSampler progress.

        It also recognizes binary frames (opcode 0x2): ComfyUI streams
        live TAESD/latent2rgb preview frames during sampling as a binary
        WebSocket message with an 8-byte header — 4 bytes big-endian
        "event type" (1 = PREVIEW_IMAGE, already-encoded JPEG/PNG bytes;
        2 = UNENCODED_PREVIEW_IMAGE, raw tensor data we can't decode as an
        image and skip) followed by 4 bytes "image format" (1=JPEG,
        2=PNG), then the image bytes themselves. When event type is 1 and
        a preview_callback was given, it's called with just the image
        bytes (header stripped). Whether these frames ever arrive at all
        is entirely up to ComfyUI's own "Live preview method" setting
        (Settings -> Comfy > Execution) — if the user has it set to
        "none" there, ComfyUI never sends them and preview_callback is
        simply never invoked. There is no separate flag to check here.

        Best-effort by design: any failure here (connection refused, bad
        handshake, ComfyUI version without this message shape, etc.) just
        leaves progress_state untouched, and the caller silently falls
        back to its own coarser estimate — this must never raise into the
        polling thread or crash the generation."""
        sock = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=COMFY_HTTP_TIMEOUT)

            ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (
                f"GET /ws?clientId={self.client_id} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {ws_key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            sock.sendall(request.encode("ascii"))

            sock.settimeout(0.5)  # short, so we keep checking stop_event/deadline
            buf = bytearray()
            header_deadline = time.time() + COMFY_HTTP_TIMEOUT
            while b"\r\n\r\n" not in buf:
                if time.time() > header_deadline or stop_event.is_set():
                    return
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    return
                buf.extend(chunk)

            header_end = buf.index(b"\r\n\r\n") + 4
            status_line = bytes(buf[:buf.index(b"\r\n")]).decode("ascii", "replace")
            if " 101 " not in status_line:
                return  # handshake rejected (e.g. /ws not served here) — give up quietly
            buf = buf[header_end:]  # any bytes after the headers are already frame data

            sock.settimeout(0.5)  # short, so we keep checking stop_event
            while not stop_event.is_set():
                parsed = self._ws_try_parse_frame(buf)
                if parsed is None:
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf.extend(chunk)
                    continue

                opcode, payload, consumed = parsed
                del buf[:consumed]

                if opcode == 0x8:   # close frame
                    return

                if opcode == 0x2:  # binary frame — possibly a preview image
                    if preview_callback is not None and len(payload) >= 8:
                        try:
                            event_type = struct.unpack(">I", payload[:4])[0]
                            if event_type == 1:  # PREVIEW_IMAGE — bytes after
                                                 # the 8-byte header are a
                                                 # ready-to-decode JPEG/PNG.
                                preview_callback(payload[8:])
                        except Exception:
                            pass  # malformed/partial frame — drop it, never crash
                    continue

                if opcode != 0x1:   # only text frames carry JSON messages
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8", "replace"))
                except Exception:
                    continue

                if msg.get("type") == "progress":
                    data = msg.get("data", {})
                    # Older ComfyUI versions don't echo prompt_id in this
                    # message; since this connection's client_id was only
                    # ever used for this one job, accept it either way.
                    if data.get("prompt_id") in (None, prompt_id):
                        value, mx = data.get("value"), data.get("max")
                        if isinstance(value, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
                            progress_state["value"] = int(value)
                            progress_state["max"] = int(mx)
        except Exception:
            pass  # best-effort: never let WS trouble affect the actual generation
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    @staticmethod
    def _ws_try_parse_frame(buf):
        """Tries to parse one complete WebSocket frame (RFC 6455) from the
        front of `buf`. Returns (opcode, payload_bytes, total_frame_len)
        if a full frame is already in the buffer, or None if the caller
        needs to read more bytes first. Handles masked frames (in case any
        proxy in front of ComfyUI masks server frames, even though plain
        ComfyUI itself doesn't) and the 16/64-bit extended length forms."""
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        plen = b1 & 0x7F
        offset = 2
        if plen == 126:
            if len(buf) < offset + 2:
                return None
            plen = struct.unpack(">H", bytes(buf[offset:offset + 2]))[0]
            offset += 2
        elif plen == 127:
            if len(buf) < offset + 8:
                return None
            plen = struct.unpack(">Q", bytes(buf[offset:offset + 8]))[0]
            offset += 8
        mask_key = None
        if masked:
            if len(buf) < offset + 4:
                return None
            mask_key = buf[offset:offset + 4]
            offset += 4
        if len(buf) < offset + plen:
            return None
        payload = bytearray(buf[offset:offset + plen])
        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask_key[i % 4]
        return opcode, bytes(payload), offset + plen


    @staticmethod
    def find_node_by_class_type(workflow_graph, class_type):
        """Finds the (single) node dict whose class_type matches. Returns
        (node_id, node_dict) or (None, None) if not found."""
        for node_id, node in workflow_graph.items():
            if isinstance(node, dict) and node.get("class_type") == class_type:
                return node_id, node
        return None, None


class PromptForgeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PromptForge v2.0")
        self._apply_app_icon()

        # --- Startup window size ---
        # A fixed "1280x860" looked fine on the dev machine but clips
        # controls (the ComfyUI section, the Generate button) on setups
        # with high-DPI scaling (e.g. 4K @ 150% on Windows), since Tk
        # widgets there need more *logical* pixels for the same content.
        # Scale the default to the actual screen instead of guessing a
        # single fixed size, and cap it so it still behaves sanely on a
        # small/1080p screen.
        #
        # The actual minimum (how far the user is allowed to shrink the
        # window) is set separately, AFTER the real UI tree exists — see
        # _apply_computed_minsize(), called at the end of __init__. A
        # hardcoded guess here ("1040x680") didn't track the real content:
        # it let the window shrink small enough to clip the left column's
        # ComfyUI block / Generate button on some font/DPI combinations.
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        good_w = max(1040, min(1480, int(screen_w * 0.85)))
        good_h = max(680, min(980, int(screen_h * 0.85)))
        self._default_window_size = (good_w, good_h)
        pos_x = max(0, (screen_w - good_w) // 2)
        pos_y = max(0, (screen_h - good_h) // 2)
        self.root.geometry(f"{good_w}x{good_h}+{pos_x}+{pos_y}")
        # Provisional floor, replaced with a real content-derived value by
        # _apply_computed_minsize() once the widget tree actually exists.
        self.root.minsize(1040, 680)

        # Snap back to that same comfortable size whenever the window is
        # un-maximized/exits fullscreen (double-click title bar, restore
        # button, etc.), instead of leaving it at whatever size it
        # happened to be before it was maximized.
        self._last_window_state = self.root.state()
        self.root.bind("<Configure>", self._on_root_configure, add="+")

        # Base data folder
        self.DATA_DIR = "prompt_forge_data"
        self.CATEGORIES = ["styles", "scenarios", "characters", "outfits"]
        self.TEMPLATES_FILE = os.path.join(self.DATA_DIR, "_templates.json")
        self.HISTORY_FILE = os.path.join(self.DATA_DIR, "_history.json")
        self.SETTINGS_FILE = os.path.join(self.DATA_DIR, "_settings.json")
        self.init_folders()

        # Settings (theme, etc.)
        self.settings = self.load_json(self.SETTINGS_FILE, {"theme": "dark"})
        self.theme_name = self.settings.get("theme", "dark")
        self.colors = THEMES[self.theme_name]
        # Height (px) of the Library image preview/drop zone. Persisted and
        # shared across all four categories (styles/scenarios/characters/
        # outfits) — one slider controls them all.
        self.lib_image_zone_percent = float(self.settings.get("lib_image_zone_percent", ImageDropZone.DEFAULT_PERCENT))
        self._image_zone_save_after_id = None
        # Height (%) of the ComfyUI "Latest image" result viewer in the
        # Forge/Builder tab. Persisted the same way as the Library zone.
        self.comfy_result_zone_percent = float(self.settings.get("comfy_result_zone_percent", 55))
        self._comfy_result_zone_save_after_id = None

        # ---- Negative prompt state ----
        # _default: used in the Standard template tab (persisted globally)
        # _custom:  per-template, stored inside the custom_templates structure
        self._neg_prompt_default_save_after_id = None
        self._neg_prompt_custom_save_after_id  = None

        # ---- ComfyUI integration state ----
        self.comfy_enabled = tk.BooleanVar(value=False)
        self.comfy_host = self.settings.get("comfy_host", COMFY_DEFAULT_HOST)
        self.comfy_port = int(self.settings.get("comfy_port", COMFY_DEFAULT_PORT))
        self.comfy_client = ComfyUIClient(self.comfy_host, self.comfy_port)
        self.comfy_connected = False           # last known health-check result
        self.comfy_output_dir = None           # discovered lazily via /system_stats
        self.comfy_seed_mode = tk.StringVar(value="random")   # "random" or "fixed"
        self.comfy_seed_value = tk.StringVar(value="0")
        self.comfy_width_var = tk.StringVar(value="1024")
        self.comfy_height_var = tk.StringVar(value="1024")
        self.comfy_resolution_choice = tk.StringVar(value=COMFY_RESOLUTION_PRESETS[0][0])
        self.comfy_busy = False                # True while a generation is in flight
        self._comfy_cancel_flag = False
        self._comfy_current_prompt_id = None   # prompt_id of the in-flight job, for Stop
        self._comfy_stopping = False           # True once Stop has been clicked, until the job actually ends
        self._comfy_last_seen_files = set()    # snapshot of output_dir before a job, for the mtime fallback
        self.comfy_last_image_path = None      # most recent successfully displayed result
        # The exact filename/subfolder ComfyUI itself reported for that result
        # (set only when the image came from the /view download path — see
        # _on_comfy_image_bytes). Lets "Open folder" point at ComfyUI's real
        # output/ folder instead of the local throwaway preview copy.
        self.comfy_last_remote_filename = None
        self.comfy_last_remote_subfolder = None

        # ---- TAESD live preview state (Task 8) ----
        # Throttle for incoming preview_image WS frames — KSampler can emit
        # one per step (e.g. 20-50 per generation); without this, every one
        # of them would schedule a root.after() callback that decodes a
        # JPEG and redraws the canvas, which is excessive. Whether frames
        # arrive at all is entirely gated by ComfyUI's own "Live preview
        # method" setting (Settings -> Comfy > Execution) — if the user
        # has it set to "none", ComfyUI never sends them, so there is
        # nothing for Prompt Forge to enable/disable on its own side.
        self._comfy_last_preview_ts = 0.0
        self.COMFY_PREVIEW_MIN_INTERVAL = 0.12  # seconds between redraws

        # ---- Gallery state (Task 3) ----
        # In-session history of every successfully generated image, newest
        # last. Each entry: {"local_path", "remote_filename",
        # "remote_subfolder", "display_name"}. Cleared implicitly on every
        # app restart (the backing _comfy_previews/ files are wiped in
        # init_folders(), and this list simply starts empty again).
        self.gallery_entries = []
        # Counter used to name each saved preview file result_NNN.<ext> —
        # incremented once per successful /view download, never reset
        # within a run (see _on_comfy_image_bytes).
        self._comfy_session_image_counter = 0

        # ---- LoRA state (Task 4) ----
        # List of available LoRA file names fetched from /promptforge/loras after
        # successful ComfyUI connection. Each entry is a relative path string,
        # e.g. "my_lora.safetensors" or "subfolder/another.safetensors".
        self._available_loras: list = []
        # Persisted slot data: list of {"name": str, "strength": float, "auto": bool}.
        # "auto" (Task 7.2) marks a slot as owned by the library-driven
        # autofill — such slots get recomputed/dropped on the next autofill
        # pass. Manually touched slots (auto missing/False) are never
        # touched by autofill. Loaded from settings.json at startup; synced
        # back on every edit.
        self._lora_slots_data: list = self.settings.get("lora_slots", [])
        # UI slot list: each entry is a dict with tkinter widget references.
        # Populated by _build_lora_slots() inside build_forge_tab().
        self.lora_slots: list = []
        # Debounce id for persisting lora_slots to settings.json
        self._lora_slots_save_after_id = None

        # Fonts
        self.default_font = ("Segoe UI", 10)
        self.bold_font = ("Segoe UI", 10, "bold")
        self.title_font = ("Segoe UI", 13, "bold")
        self.mono_font = ("Consolas", 10)
        self.small_font = ("Segoe UI", 9)

        # Constructor variables
        self.selected_style = tk.StringVar()
        self.selected_scenario = tk.StringVar()
        self.active_characters = []  # list of dicts: {frame, char_var, outfit_var, outfit_combo, char_combo}

        # Order of prompt assembly blocks: list of block keys
        # available blocks: "style", "characters", "scenario"
        self.block_order = ["style", "characters", "scenario"]
        self.templates = self.load_json(self.TEMPLATES_FILE, {})
        self.history = self.load_json(self.HISTORY_FILE, [])

        # Custom templates: free-form text with variables [Name N], [Description N],
        # [Outfit N], [Style], [Scenario]. A separate category from the standard
        # template (block_order), which remains the "default".
        self.CUSTOM_TEMPLATES_FILE = os.path.join(self.DATA_DIR, "_custom_templates.json")
        self.custom_templates = self.load_json(self.CUSTOM_TEMPLATES_FILE, {})
        self.custom_active_slots = []      # list of character slots for the current custom template
        self.custom_style_var = tk.StringVar()
        self.custom_scenario_var = tk.StringVar()
        self.custom_style_combo = None
        self.custom_scenario_combo = None
        self.current_custom_template_name = None
        self.current_custom_parsed = None

        # Library state
        self.lib_current_category = "styles"
        self.lib_search_var = tk.StringVar()
        self.lib_selected_file = None  # name of the file (without extension) currently being edited
        self.lib_editing_canon_owner = None  # if editing a canon outfit, holds (char_name, idx)
        # Task 6: source URL for the entry currently open in the editor.
        # None = no link saved. Edit-mode toggle is separate (lib_source_editing).
        self.lib_source_url = None
        self.lib_source_editing = False
        # Task 7.1: LoRA filename bound to the entry currently open in the
        # editor (full path/basename as returned by /promptforge/loras), or
        # None if no LoRA is bound.
        self.lib_entry_lora = None

        self.style = ttk.Style()
        self.apply_theme()

        self.create_ui()
        self.reload_all_lists()
        self.refresh_library_list()
        self.refresh_history_list()
        self._apply_computed_minsize()

    def _apply_computed_minsize(self):
        """Sets the window's real floor size from what the UI actually
        needs, instead of a hardcoded guess.

        The previous fixed `minsize(1040, 680)` was tuned on one dev
        machine. On other font/DPI setups the left column (Style block,
        Characters block, Scenario, the ComfyUI panel and the Generate
        button underneath it all) needed more than 680px of height to
        show every control — shrinking the window clipped the bottom of
        that column with nothing onscreen to indicate more existed.

        Tk's `winfo_reqheight/reqwidth` on the notebook (after a forced
        geometry update) reports exactly how much space the widget tree
        wants at its natural size — independent of how big the window
        currently happens to be — so it's the right basis for a floor.
        A small margin is added for window-manager chrome (title bar,
        borders) and so the layout isn't perfectly knife-edge tight.
        """
        try:
            self.root.update_idletasks()
            req_w = self.notebook.winfo_reqwidth()
            req_h = self.notebook.winfo_reqheight()
        except Exception:
            return
        if req_w <= 1 or req_h <= 1:
            return  # widgets not realized yet; keep the provisional floor

        margin_w, margin_h = 36, 80
        min_w = max(1040, req_w + margin_w)
        min_h = max(680, req_h + margin_h)

        # Never demand a floor bigger than the actual screen — a 4K-coded
        # requirement run on a 1080p laptop should still be shrinkable,
        # just down to "as small as the screen allows" rather than an
        # unreachable number.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        min_w = min(min_w, max(1040, screen_w - 40))
        min_h = min(min_h, max(680, screen_h - 80))

        self.root.minsize(min_w, min_h)

        # If the window is currently sitting smaller than its own new
        # floor (e.g. a saved/restored geometry from a previous, more
        # cramped run), grow it up to the floor right away rather than
        # leaving controls clipped until the user manually resizes.
        cur_w = self.root.winfo_width()
        cur_h = self.root.winfo_height()
        if cur_w < min_w or cur_h < min_h:
            new_w = max(cur_w, min_w)
            new_h = max(cur_h, min_h)
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(f"{new_w}x{new_h}+{x}+{y}")

    def _apply_app_icon(self):
        """Sets the window/taskbar icon if an icon file is present next to the
        program. Looks for icon.ico first (best on Windows), then icon.png
        (works on Windows/macOS/Linux). Silently does nothing if neither is
        found, so the app still runs fine without an icon."""
        ico_path = os.path.join(app_dir(), "icon.ico")
        png_path = os.path.join(app_dir(), "icon.png")
        try:
            if os.path.exists(ico_path):
                self.root.iconbitmap(ico_path)
                return
        except Exception:
            pass
        try:
            if os.path.exists(png_path):
                self._icon_image = tk.PhotoImage(file=png_path)  # keep a reference alive
                self.root.iconphoto(True, self._icon_image)
        except Exception:
            pass

    # ==========================================================
    #                    PERSISTENCE (JSON)
    # ==========================================================
    def load_json(self, path, default):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default
        return default

    def save_json(self, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save data: {e}")

    def init_folders(self):
        """Creates the folder structure if it doesn't exist"""
        if not os.path.exists(self.DATA_DIR):
            os.makedirs(self.DATA_DIR)
        for cat in self.CATEGORIES:
            path = os.path.join(self.DATA_DIR, cat)
            if not os.path.exists(path):
                os.makedirs(path)

        # ComfyUI preview cache (Task 3 — Gallery): wiped on every startup.
        # During a run, every successful generation adds its own
        # result_NNN.<ext> file here (see _on_comfy_image_bytes) so the
        # Gallery can show the whole session's history, not just the
        # latest image — that only works if old sessions' leftovers don't
        # pile up indefinitely or bleed into a fresh session's Gallery.
        previews_dir = os.path.join(self.DATA_DIR, "_comfy_previews")
        if os.path.exists(previews_dir):
            try:
                shutil.rmtree(previews_dir)
            except OSError:
                pass
        try:
            os.makedirs(previews_dir, exist_ok=True)
        except OSError:
            pass

    # ==========================================================
    #                LIBRARY ENTRY IMAGES (Pillow)
    # ==========================================================
    def library_image_path(self, category, name):
        """Path where the entry's image is expected to live, regardless of
        whether the file currently exists."""
        return os.path.join(self.DATA_DIR, category, f"{name}{IMAGE_STORE_EXT}")

    def find_library_image(self, category, name):
        """Returns the on-disk image path for this entry, or None if it
        has no saved image."""
        if not name:
            return None
        path = self.library_image_path(category, name)
        return path if os.path.exists(path) else None

    def process_and_store_image(self, source_path, category, name):
        """Converts/resizes the picked image and saves it next to the
        category's text entries, named after the entry itself.

        - Converts to an optimized .jpg (flattened onto white, since JPEG
          has no alpha channel).
        - Proportionally scales so the longest side is IMAGE_MAX_SIDE px;
          never upscales beyond the source resolution.
        - Returns the saved path, or None (with a message box) on failure.
        """
        if not PIL_AVAILABLE:
            messagebox.showerror("Missing dependency",
                                  "Pillow is required to process images.\nInstall it with: pip install Pillow")
            return None
        if not name:
            messagebox.showwarning("No name", "Set a name for this entry before attaching an image.")
            return None

        try:
            img = Image.open(source_path)
            img.load()
        except Exception as e:
            messagebox.showerror("Error", f"Could not open image:\n{e}")
            return None

        try:
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            else:
                img = img.convert("RGB")

            w, h = img.size
            longest = max(w, h)
            if longest > IMAGE_MAX_SIDE:
                scale = IMAGE_MAX_SIDE / float(longest)
                new_w = max(int(round(w * scale)), 1)
                new_h = max(int(round(h * scale)), 1)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            cat_dir = os.path.join(self.DATA_DIR, category)
            if not os.path.exists(cat_dir):
                os.makedirs(cat_dir)

            dest_path = self.library_image_path(category, name)
            img.save(dest_path, "JPEG", quality=90, optimize=True)
            return dest_path
        except Exception as e:
            messagebox.showerror("Error", f"Could not save image:\n{e}")
            return None

    def delete_library_image(self, category, name):
        """Removes the on-disk image for this entry, if any. Silent no-op
        if there isn't one."""
        if not name:
            return
        path = self.library_image_path(category, name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def rename_library_image(self, category, old_name, new_name):
        """Keeps the image file in sync when an entry is renamed on save."""
        if not old_name or old_name == new_name:
            return
        old_path = self.library_image_path(category, old_name)
        if os.path.exists(old_path):
            new_path = self.library_image_path(category, new_name)
            try:
                if os.path.exists(new_path):
                    os.remove(new_path)
                shutil.move(old_path, new_path)
            except Exception:
                pass

    # ==========================================================
    #         LIBRARY ENTRY METADATA (Task 6 source_url / Task 7.1 lora)
    # ==========================================================
    # Stored as a small sidecar JSON file named after the entry, exactly
    # like the image sidecar above ({name}{IMAGE_STORE_EXT}), so it follows
    # the same rename/duplicate/delete lifecycle without needing a separate
    # top-level JSON file to keep in sync with the on-disk .txt files.
    def library_meta_path(self, category, name):
        return os.path.join(self.DATA_DIR, category, f"{name}{LIBRARY_META_EXT}")

    def load_library_meta(self, category, name):
        """Returns {"source_url": str|None, "lora": str|None} for this
        entry. Missing/corrupt sidecar -> both None (no link, no binding)."""
        empty = {"source_url": None, "lora": None}
        if not name:
            return empty
        path = self.library_meta_path(category, name)
        if not os.path.exists(path):
            return empty
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return empty
            return {
                "source_url": data.get("source_url") or None,
                "lora": data.get("lora") or None,
            }
        except Exception:
            return empty

    def save_library_meta(self, category, name, source_url=None, lora=None):
        """Writes the sidecar JSON, or removes it if both fields end up
        empty (so entries with nothing special don't grow a stray file)."""
        if not name:
            return
        if not source_url and not lora:
            self.delete_library_meta(category, name)
            return
        path = self.library_meta_path(category, name)
        try:
            cat_dir = os.path.join(self.DATA_DIR, category)
            if not os.path.exists(cat_dir):
                os.makedirs(cat_dir)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"source_url": source_url or None, "lora": lora or None}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def delete_library_meta(self, category, name):
        if not name:
            return
        path = self.library_meta_path(category, name)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def rename_library_meta(self, category, old_name, new_name):
        """Keeps the metadata sidecar in sync when an entry is renamed,
        mirroring rename_library_image above."""
        if not old_name or old_name == new_name:
            return
        old_path = self.library_meta_path(category, old_name)
        if os.path.exists(old_path):
            new_path = self.library_meta_path(category, new_name)
            try:
                if os.path.exists(new_path):
                    os.remove(new_path)
                shutil.move(old_path, new_path)
            except Exception:
                pass

    def handle_image_drop(self, source_path):
        """Callback wired to the ImageDropZone: a file was picked or
        dropped for the entry currently open in the editor. Uses the name
        field's current text when available (covers both new, unsaved
        entries and renames-in-progress); falls back to the already
        selected/loaded entry's name."""
        cat = self.lib_current_category
        if cat == "outfits" and self.is_canon_var.get():
            if self.lib_editing_canon_owner:
                char_name, num = self.lib_editing_canon_owner
                name = f"{char_name}_Canon_{num}"
            else:
                messagebox.showinfo("Save first",
                                     "Save this canon outfit once before attaching an image.")
                return
        else:
            name = self.ent_lib_name.get().strip()
            if not name:
                name = self.lib_selected_file
            if not name:
                messagebox.showinfo("Name required",
                                     "Enter a name for this entry before attaching an image.")
                return
            name = sanitize_filename(name)

        saved_path = self.process_and_store_image(source_path, cat, name)
        if saved_path:
            self.image_drop_zone.show_image_path(saved_path)
            self.lbl_lib_status.configure(text=f"✓ Image attached to {name}")

    # ==========================================================
    #                         THEME / STYLE
    # ==========================================================
    def apply_theme(self):
        c = self.colors
        self.root.configure(bg=c["bg"])
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        s = self.style
        s.configure(".", font=self.default_font, background=c["bg"], foreground=c["fg"])
        s.configure("TFrame", background=c["bg"])
        s.configure("Card.TFrame", background=c["bg_card"])
        s.configure("TLabel", background=c["bg"], foreground=c["fg"])
        s.configure("Card.TLabel", background=c["bg_card"], foreground=c["fg"])
        s.configure("Dim.TLabel", background=c["bg"], foreground=c["fg_dim"], font=self.small_font)
        s.configure("CardDim.TLabel", background=c["bg_card"], foreground=c["fg_dim"], font=self.small_font)
        s.configure("Title.TLabel", background=c["bg"], foreground=c["fg"], font=self.title_font)
        s.configure("CardTitle.TLabel", background=c["bg_card"], foreground=c["fg"], font=self.bold_font)
        # Task 7.2: [A]/[M] tag to the left of each LoRA Manager slot —
        # accent color for auto-filled slots (owned by library autofill),
        # dim color for manually-edited ones (never touched by autofill).
        s.configure("LoraTagAuto.TLabel", background=c["bg"], foreground=c["accent"], font=self.small_font)
        s.configure("LoraTagManual.TLabel", background=c["bg"], foreground=c["fg_dim"], font=self.small_font)

        s.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], relief="solid")
        s.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"], font=self.bold_font)

        s.configure("TNotebook", background=c["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=c["bg_alt"], foreground=c["fg_dim"],
                    padding=(16, 9), font=self.bold_font, borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", c["bg_card"])],
              foreground=[("selected", c["accent"])])

        # Buttons
        s.configure("TButton", font=self.bold_font, padding=(10, 7),
                    background=c["bg_alt"], foreground=c["fg"], borderwidth=0)
        s.map("TButton",
              background=[("active", c["border"])])

        s.configure("Accent.TButton", font=self.bold_font, padding=(12, 9),
                    background=c["accent"], foreground=c["accent_text"], borderwidth=0)
        s.map("Accent.TButton",
              background=[("active", c["accent_hover"])])

        s.configure("Danger.TButton", font=self.bold_font, padding=(8, 6),
                    background=c["danger"], foreground="#ffffff", borderwidth=0)
        s.map("Danger.TButton",
              background=[("active", c["danger_hover"])])

        s.configure("Ghost.TButton", font=self.default_font, padding=(8, 5),
                    background=c["bg"], foreground=c["fg_dim"], borderwidth=0)
        s.map("Ghost.TButton", background=[("active", c["bg_alt"])], foreground=[("active", c["fg"])])

        s.configure("Icon.TButton", font=self.bold_font, padding=(6, 4),
                    background=c["bg_card"], foreground=c["fg"], borderwidth=0)
        s.map("Icon.TButton", background=[("active", c["border"])])

        # Combobox / Entry
        s.configure("TCombobox", fieldbackground=c["bg_input"], background=c["bg_input"],
                    foreground=c["fg"], arrowcolor=c["fg_dim"], borderwidth=0,
                    selectbackground=c["bg_input"], selectforeground=c["fg"], padding=6)
        s.map("TCombobox",
              fieldbackground=[("readonly", c["bg_input"])],
              foreground=[("readonly", c["fg"])])
        self.root.option_add("*TCombobox*Listbox.background", c["bg_card"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["accent_text"])
        self.root.option_add("*TCombobox*Listbox.font", self.default_font)

        s.configure("TEntry", fieldbackground=c["bg_input"], foreground=c["fg"],
                    insertcolor=c["fg"], borderwidth=0, padding=6)

        s.configure("TCheckbutton", background=c["bg_card"], foreground=c["fg"])
        s.map("TCheckbutton", background=[("active", c["bg_card"])])

        s.configure("Vertical.TScrollbar", background=c["bg_alt"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["fg_dim"])
        s.configure("Horizontal.TScrollbar", background=c["bg_alt"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["fg_dim"])

        s.configure("Horizontal.TScale", background=c["bg"], troughcolor=c["bg_alt"])

        s.configure("Treeview", background=c["tree_bg"], fieldbackground=c["tree_bg"],
                    foreground=c["fg"], borderwidth=0, rowheight=26, font=self.default_font)
        s.configure("Treeview.Heading", background=c["bg_alt"], foreground=c["fg_dim"],
                    font=self.bold_font, borderwidth=0, relief="flat")
        s.map("Treeview",
              background=[("selected", c["accent"])],
              foreground=[("selected", c["accent_text"])])
        s.map("Treeview.Heading", background=[("active", c["bg_alt"])])

        s.configure("TPanedwindow", background=c["bg"])
        s.configure("TSeparator", background=c["border"])

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.colors = THEMES[self.theme_name]
        self.settings["theme"] = self.theme_name
        self.save_json(self.SETTINGS_FILE, self.settings)
        self.apply_theme()
        self.refresh_themed_widgets()

    def _on_image_zone_resize(self, value):
        """Live-resizes the Library image preview zone as the slider moves.
        The setting is a PERCENTAGE of the Entry Editor panel's height,
        shared across all four categories and persisted to disk, debounced
        so we don't hit the filesystem on every pixel of drag — only
        ~150ms after the user stops moving the slider."""
        percent = float(value)
        self.lib_image_zone_percent = percent
        if hasattr(self, "image_drop_zone"):
            self.image_drop_zone.set_percent(percent)
        if hasattr(self, "_image_zone_save_after_id") and self._image_zone_save_after_id:
            self.root.after_cancel(self._image_zone_save_after_id)
        self._image_zone_save_after_id = self.root.after(150, self._persist_image_zone_height)

    def _on_root_configure(self, event):
        """Detects the transition out of maximized/fullscreen (zoomed ->
        normal) and snaps the window back to the same comfortable default
        size it started at, centered on screen — instead of leaving it at
        whatever cramped size it happened to have right before it was
        maximized."""
        if event.widget is not self.root:
            return
        try:
            state = self.root.state()
        except Exception:
            return
        previous = self._last_window_state
        self._last_window_state = state
        if previous == "zoomed" and state == "normal":
            w, h = self._default_window_size
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            x = max(0, (screen_w - w) // 2)
            y = max(0, (screen_h - h) // 2)
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _on_library_panel_resize(self, event):
        """Keeps the image zone's pixel height in sync with the Entry
        Editor panel's height whenever the panel resizes (window resize,
        maximize, monitor change, etc.)."""
        if hasattr(self, "image_drop_zone"):
            self.image_drop_zone.apply_panel_height(event.height)

    def _persist_image_zone_height(self):
        self._image_zone_save_after_id = None
        self.settings["lib_image_zone_percent"] = self.lib_image_zone_percent
        self.save_json(self.SETTINGS_FILE, self.settings)

    def _on_comfy_panel_resize(self, event):
        """Keeps the ComfyUI result preview's pixel height in sync with
        the whole right-hand column's height whenever that column resizes
        (window resize, maximize, sash drag, monitor change, etc.). Mirrors
        _on_library_panel_resize."""
        self._resize_comfy_result_zone(event.height)

    def _resize_comfy_result_zone(self, right_panel_height=None):
        """Sizes the ComfyUI preview canvas so the *whole* 'Latest ComfyUI
        image' card — size slider, canvas, progress bar, status line and
        Open folder button — always fits inside the right-hand column.

        Previously the canvas height was a straight percentage of the
        column's total height, with no regard for the slider row / status
        row / Open folder button also living in that same column below
        it. At larger percentages the card's total required height ended
        up taller than the column itself, and since the column doesn't
        scroll, the status row and Open folder button simply got pushed
        past the bottom edge of the window — invisible, not just hidden.

        The fix has two parts:

        1. Measure "chrome" (everything in the card except the canvas)
           EXACTLY, via frame_comfy_result's own winfo_reqheight() minus
           the canvas's current configured height — rather than summing
           each sibling's reqheight() plus a guessed constant. The old
           guess (a flat +50px) didn't track the LabelFrame's real
           border/title/padding overhead and silently drifted out of sync
           whenever a row's content changed (e.g. the progress bar
           appearing during generation adds real height that a constant
           can't anticipate).
        2. Never let the canvas claim more than the column actually has
           left over. The old code floored `available` at MIN_PX (130)
           unconditionally — so on a short column it could still ask the
           canvas for 130px it didn't have, which is exactly what pushed
           the status row / Open folder button off the bottom. Now, if
           the column is too short even for the smallest canvas, the
           canvas is allowed to shrink below MIN_PX (down to a hard
           pixel floor of 40, just enough to stay visible as a strip)
           rather than overflowing its siblings out of view.
        """
        if not hasattr(self, "comfy_result_zone") or not hasattr(self, "frame_comfy_result"):
            return
        if right_panel_height is None:
            if not hasattr(self, "forge_right_panel"):
                return
            right_panel_height = self.forge_right_panel.winfo_height()
        if right_panel_height <= 1:
            return

        # Re-entrancy guard: this method measures real widget geometry via
        # update_idletasks(), which can synchronously dispatch any other
        # pending Tk events (including another <Configure> bound to
        # _on_comfy_panel_resize) before returning. Without this guard, an
        # unexpected event chain could re-enter this same method while the
        # first call is still mid-measurement; the guard makes any such
        # re-entry a harmless no-op instead of a runaway recursive resize.
        if getattr(self, "_resizing_comfy_zone", False):
            return
        self._resizing_comfy_zone = True
        try:
            self.root.update_idletasks()
            canvas_h = max(self.comfy_result_zone.winfo_height(), 1)
            card_req_h = self.frame_comfy_result.winfo_reqheight()
            # Everything in the card other than the canvas: header/slider row,
            # progress bar (when shown), status row + Open folder button,
            # plus the LabelFrame's own border and title strip.
            chrome = max(card_req_h - canvas_h, 0)

            HARD_FLOOR_PX = 40
            available = right_panel_height - chrome
            available = max(HARD_FLOOR_PX, min(available, ResultImageViewer.MAX_PX))
            self.comfy_result_zone.apply_panel_height(available)
        finally:
            self._resizing_comfy_zone = False

    def _on_comfy_result_zone_resize(self, value):
        """Live-resizes the ComfyUI 'Latest image' preview zone as the
        slider moves. Mirrors _on_image_zone_resize: percentage of the
        frame's height, persisted to disk, debounced ~150ms."""
        percent = float(value)
        self.comfy_result_zone_percent = percent
        if hasattr(self, "comfy_result_zone"):
            self.comfy_result_zone.set_percent(percent)
        if hasattr(self, "_comfy_result_zone_save_after_id") and self._comfy_result_zone_save_after_id:
            self.root.after_cancel(self._comfy_result_zone_save_after_id)
        self._comfy_result_zone_save_after_id = self.root.after(150, self._persist_comfy_result_zone_height)

    def _persist_comfy_result_zone_height(self):
        self._comfy_result_zone_save_after_id = None
        self.settings["comfy_result_zone_percent"] = self.comfy_result_zone_percent
        self.save_json(self.SETTINGS_FILE, self.settings)

    # ---- negative prompt persistence (debounced ~500ms) ----

    def _on_neg_prompt_default_changed(self):
        """Called on <<Modified>> for txt_neg_prompt (Standard tab).
        Resets the modified flag so the event fires again next time,
        then debounces the save."""
        try:
            self.txt_neg_prompt.edit_modified(False)
        except tk.TclError:
            pass
        if self._neg_prompt_default_save_after_id:
            self.root.after_cancel(self._neg_prompt_default_save_after_id)
        self._neg_prompt_default_save_after_id = self.root.after(
            500, self._persist_neg_prompt_default)

    def _persist_neg_prompt_default(self):
        self._neg_prompt_default_save_after_id = None
        text = self.txt_neg_prompt.get("1.0", tk.END).strip()
        self.settings["negative_prompt_default"] = text
        self.save_json(self.SETTINGS_FILE, self.settings)

    def _on_neg_prompt_custom_changed(self):
        """Called on <<Modified>> for txt_neg_prompt_custom (Custom Templates tab).
        Saves the value into the current template's JSON entry."""
        try:
            self.txt_neg_prompt_custom.edit_modified(False)
        except tk.TclError:
            pass
        if self._neg_prompt_custom_save_after_id:
            self.root.after_cancel(self._neg_prompt_custom_save_after_id)
        self._neg_prompt_custom_save_after_id = self.root.after(
            500, self._persist_neg_prompt_custom)

    def _persist_neg_prompt_custom(self):
        self._neg_prompt_custom_save_after_id = None
        name = self.current_custom_template_name
        if not name or name not in self.custom_templates:
            return
        text = self.txt_neg_prompt_custom.get("1.0", tk.END).strip()
        self.custom_templates[name]["negative_prompt"] = text
        self.save_json(self.CUSTOM_TEMPLATES_FILE, self.custom_templates)

    def refresh_themed_widgets(self):
        """Recolors widgets that tk (not ttk) doesn't pick up via ttk.Style."""
        c = self.colors
        widgets = [
            getattr(self, "txt_output", None),
            getattr(self, "txt_lib_tags", None),
            getattr(self, "txt_lib_preview", None),
            getattr(self, "txt_neg_prompt", None),
            getattr(self, "txt_neg_prompt_custom", None),
        ]
        for w in widgets:
            if w is not None:
                w.configure(bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                            selectbackground=c["accent"], selectforeground=c["accent_text"])
        if hasattr(self, "lbl_theme_icon"):
            self.lbl_theme_icon.configure(text="🌙" if self.theme_name == "dark" else "☀️")
        if hasattr(self, "lst_history"):
            self.lst_history.configure(bg=c["bg_card"], fg=c["fg"],
                                        selectbackground=c["accent"], selectforeground=c["accent_text"])
        if hasattr(self, "image_drop_zone"):
            self.image_drop_zone.set_colors(c)
        if hasattr(self, "comfy_result_zone"):
            self.comfy_result_zone.set_colors(c)
        if hasattr(self, "gallery_canvas"):
            self.gallery_canvas.configure(bg=c["bg"])
        if hasattr(self, "gallery_cells"):
            for cell in self.gallery_cells:
                for w in getattr(cell, "gallery_tk_widgets", []):
                    try:
                        w.configure(bg=c["bg_card"])
                    except Exception:
                        pass
        # LoRA manager (Task 4)
        if hasattr(self, "lora_slots"):
            self._lora_apply_theme()
        # Library Source URL / LoRA binding rows (Task 6/7.1) use plain
        # tk.Label for the link/error text (for color+underline+cursor
        # control ttk doesn't expose), so re-render them on theme change
        # instead of trying to recolor in place.
        if hasattr(self, "frame_lib_source"):
            self._render_lib_source_row()
        if hasattr(self, "frame_lib_lora"):
            self._render_lib_lora_row()

    # ==========================================================
    #                          UI: ROOT
    # ==========================================================
    def create_ui(self):
        c = self.colors
        # Top bar: title + theme toggle
        topbar = tk.Frame(self.root, bg=c["bg"])
        topbar.pack(fill="x", padx=18, pady=(14, 0))

        tk.Label(topbar, text="⚡ PromptForge", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(topbar, text="prompt builder & generation workspace", bg=c["bg"], fg=c["fg_dim"],
                 font=self.small_font).pack(side="left", padx=(10, 0), pady=(6, 0))

        theme_btn = tk.Frame(topbar, bg=c["bg"])
        theme_btn.pack(side="right")
        self.lbl_theme_icon = tk.Label(theme_btn, text="🌙" if self.theme_name == "dark" else "☀️",
                                        bg=c["bg"], fg=c["fg"], font=("Segoe UI", 13),
                                        cursor="hand2")
        self.lbl_theme_icon.pack(side="right", padx=4)
        self.lbl_theme_icon.bind("<Button-1>", lambda e: self.toggle_theme())
        Tooltip(self.lbl_theme_icon, "Toggle the color theme", self)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=14)

        self.tab_forge = ttk.Frame(self.notebook)
        self.tab_library = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_gallery = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_forge, text="🛠  Builder")
        self.notebook.add(self.tab_library, text="📚  Library")
        self.notebook.add(self.tab_history, text="🕘  History")
        self.notebook.add(self.tab_gallery, text="🖼  Gallery")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        self.build_forge_tab()
        self.build_library_tab()
        self.build_history_tab()
        self.build_gallery_tab()

    def _on_notebook_tab_changed(self, _event=None):
        """A Notebook tab that has never been shown reports a stale/zero
        width from winfo_width() until it's actually mapped — if an image
        arrived (and the Gallery tried to lay out its grid) before the
        user ever opened that tab, it could get stuck showing a single
        forced column. Recompute once the tab is actually selected and
        has real geometry."""
        try:
            current = self.notebook.nametowidget(self.notebook.select())
        except Exception:
            return
        if hasattr(self, "tab_gallery") and current is self.tab_gallery:
            self.root.after(50, self._gallery_relayout)

    # ==========================================================
    #             TAB 1: PROMPT BUILDER (FORGE)
    # ==========================================================
    def build_forge_tab(self):
        c = self.colors
        outer = ttk.Frame(self.tab_forge)
        outer.pack(fill="both", expand=True)

        # Left column — block configuration, right — result
        paned = ttk.PanedWindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        self.forge_right_panel = right
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # --- Prompt template panel (Standard / Custom) ---
        order_frame = ttk.LabelFrame(left, text=" Prompt Template ", padding=10)
        order_frame.pack(fill="x", padx=(0, 10), pady=(0, 8))

        cat_row = ttk.Frame(order_frame)
        cat_row.pack(fill="x", pady=(0, 8))
        ttk.Label(cat_row, text="Template type:", style="TLabel").pack(side="left", padx=(0, 8))
        self.combo_template_category = ttk.Combobox(cat_row, state="readonly", width=14,
                                                      values=["Standard", "Custom"])
        self.combo_template_category.current(0)
        self.combo_template_category.pack(side="left")
        self.combo_template_category.bind(
            "<<ComboboxSelected>>", lambda e: self.on_template_category_changed())
        Tooltip(self.combo_template_category,
                "\"Standard\" — our flexible builder with any number of characters.\n"
                "\"Custom\" — templates with free-form text and variables.", self)

        # -- Standard: block order + saved order templates --
        self.tpl_controls_standard = ttk.Frame(order_frame)
        self.tpl_controls_standard.pack(fill="x")

        self.order_display = ttk.Label(self.tpl_controls_standard, text=self._order_to_text(), style="TLabel")
        self.order_display.pack(side="left", fill="x", expand=True)

        btn_reorder = ttk.Button(self.tpl_controls_standard, text="Block order…", command=self.open_order_dialog)
        btn_reorder.pack(side="right", padx=(8, 0))

        tpl_frame = ttk.Frame(self.tpl_controls_standard)
        tpl_frame.pack(side="right")
        self.combo_template = ttk.Combobox(tpl_frame, state="readonly", width=16)
        self.combo_template.pack(side="left")
        self.combo_template.bind("<<ComboboxSelected>>", self.on_template_selected)
        btn_save_tpl = ttk.Button(tpl_frame, text="💾", width=3, command=self.save_current_as_template)
        btn_save_tpl.pack(side="left", padx=(4, 0))
        Tooltip(btn_save_tpl, "Save the current block set as a template", self)
        self.refresh_template_combo()

        # -- Custom: select/create/delete custom template --
        self.tpl_controls_custom = ttk.Frame(order_frame)
        # not packed immediately — only shown when the "Custom" category is selected

        ttk.Label(self.tpl_controls_custom, text="Template:", style="TLabel").pack(side="left", padx=(0, 6))
        self.combo_custom_template = ttk.Combobox(self.tpl_controls_custom, state="readonly", width=18)
        self.combo_custom_template.pack(side="left")
        self.combo_custom_template.bind("<<ComboboxSelected>>", self.on_custom_template_selected)

        btn_new_custom = ttk.Button(self.tpl_controls_custom, text="✏ Create template",
                                     command=lambda: self.open_custom_template_editor(None))
        btn_new_custom.pack(side="left", padx=(8, 0))

        btn_del_custom = ttk.Button(self.tpl_controls_custom, text="🗑", width=3,
                                     command=self.delete_selected_custom_template)
        btn_del_custom.pack(side="left", padx=(4, 0))
        Tooltip(btn_del_custom, "Delete the selected custom template", self)

        self.refresh_custom_template_combo()

        # --- Area toggled between "Standard" and "Custom" ---
        self.dynamic_content_frame = ttk.Frame(left)
        self.dynamic_content_frame.pack(fill="both", expand=True, padx=(0, 10))

        self.standard_section = ttk.Frame(self.dynamic_content_frame)
        self.standard_section.pack(fill="both", expand=True)

        self.custom_section = ttk.Frame(self.dynamic_content_frame)
        # not packed immediately — appears when switching to "Custom"

        # --- Style ---
        frame_style = ttk.LabelFrame(self.standard_section, text=" 1. Style ", padding=12)
        frame_style.pack(fill="x", pady=6)

        row_style = ttk.Frame(frame_style)
        row_style.pack(fill="x")
        self.combo_style = AutocompleteCombobox(row_style, textvariable=self.selected_style)
        self.combo_style.pack(side="left", fill="x", expand=True)
        self.combo_style.bind("<<ComboboxSelected>>", lambda e: self.update_live_preview(), add="+")
        btn_style_preview = ttk.Button(row_style, text="👁", width=3,
                                        command=lambda: self.quick_preview("styles", self.selected_style))
        btn_style_preview.pack(side="left", padx=(6, 0))
        Tooltip(btn_style_preview, "Show the content of the selected style", self)

        # --- Characters (dynamic container) ---
        self.frame_chars_container = ttk.LabelFrame(self.standard_section, text=" 2. Characters and Outfits ", padding=12)
        self.frame_chars_container.pack(fill="both", expand=True, pady=6)

        header_chars = ttk.Frame(self.frame_chars_container)
        header_chars.pack(fill="x", pady=(0, 6))
        btn_add_char = ttk.Button(header_chars, text="＋ Add character", style="Accent.TButton",
                                   command=self.add_character_slot)
        btn_add_char.pack(side="left")
        self.lbl_chars_count = ttk.Label(header_chars, text="0 characters", style="Dim.TLabel")
        self.lbl_chars_count.pack(side="left", padx=12)

        chars_canvas_holder = ttk.Frame(self.frame_chars_container)
        chars_canvas_holder.pack(fill="both", expand=True)

        c_bg = self.colors["bg"]
        self.chars_canvas = tk.Canvas(chars_canvas_holder, bg=c_bg, highlightthickness=0)
        chars_scroll = ttk.Scrollbar(chars_canvas_holder, orient="vertical", command=self.chars_canvas.yview)
        self.scroll_chars = ttk.Frame(self.chars_canvas)
        self.scroll_chars.bind("<Configure>",
                                lambda e: self.chars_canvas.configure(scrollregion=self.chars_canvas.bbox("all")))
        self.chars_canvas.create_window((0, 0), window=self.scroll_chars, anchor="nw")
        self.chars_canvas.configure(yscrollcommand=chars_scroll.set)
        self.chars_canvas.pack(side="left", fill="both", expand=True)
        chars_scroll.pack(side="right", fill="y")

        self.placeholder_chars = ttk.Label(self.scroll_chars,
                                            text="No characters added. Click \"＋ Add character\".",
                                            style="Dim.TLabel")
        self.placeholder_chars.pack(anchor="w", pady=10, padx=4)

        # --- Scenario ---
        frame_scenario = ttk.LabelFrame(self.standard_section, text=" 3. Scenario ", padding=12)
        frame_scenario.pack(fill="x", pady=6)

        row_scen = ttk.Frame(frame_scenario)
        row_scen.pack(fill="x")
        self.combo_scenario = AutocompleteCombobox(row_scen, textvariable=self.selected_scenario)
        self.combo_scenario.pack(side="left", fill="x", expand=True)
        self.combo_scenario.bind("<<ComboboxSelected>>", lambda e: self.update_live_preview(), add="+")
        btn_scen_preview = ttk.Button(row_scen, text="👁", width=3,
                                       command=lambda: self.quick_preview("scenarios", self.selected_scenario))
        btn_scen_preview.pack(side="left", padx=(6, 0))
        Tooltip(btn_scen_preview, "Show the content of the selected scenario", self)

        # --- Negative prompt (Standard tab) ---
        # Parented to `left` (not `standard_section`) so it stays visible
        # when the user switches to Custom Templates — same reasoning as
        # the ComfyUI panel below.
        self.frame_neg_prompt = ttk.LabelFrame(left, text=" Negative prompt ", padding=12)
        self.frame_neg_prompt.pack(fill="x", padx=(0, 10), pady=6)
        self.txt_neg_prompt = scrolledtext.ScrolledText(
            self.frame_neg_prompt, font=self.mono_font, wrap=tk.WORD,
            relief="flat", borderwidth=0, height=3)
        self.txt_neg_prompt.pack(fill="x")
        neg_default = self.settings.get("negative_prompt_default", "")
        if neg_default:
            self.txt_neg_prompt.insert("1.0", neg_default)
        self.txt_neg_prompt.configure(
            bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
            selectbackground=c["accent"], selectforeground=c["accent_text"])
        self.txt_neg_prompt.bind(
            "<<Modified>>",
            lambda e: self._on_neg_prompt_default_changed())

        # --- ComfyUI integration panel ---
        # NOTE: parented to `left` (not `standard_section`) on purpose — this
        # panel (and the "ComfyUI connected?" toggle inside it) must stay
        # visible no matter which Template type is selected. It used to live
        # inside `standard_section`, which on_template_category_changed()
        # pack_forget()s when the user switches to "Custom" — silently
        # hiding the only way to enable ComfyUI mode, which made it look
        # like generation from Custom Templates was broken/impossible.
        self.frame_comfy = ttk.LabelFrame(left, text=" 4. ComfyUI ", padding=12)
        self.frame_comfy.pack(fill="x", padx=(0, 10), pady=6)

        comfy_toggle_row = ttk.Frame(self.frame_comfy)
        comfy_toggle_row.pack(fill="x")
        self.chk_comfy_enabled = ttk.Checkbutton(
            comfy_toggle_row, text="ComfyUI connected?", variable=self.comfy_enabled,
            command=self.on_comfy_toggle)
        self.chk_comfy_enabled.pack(side="left")
        self.lbl_comfy_status = ttk.Label(comfy_toggle_row, text="", style="Dim.TLabel")
        self.lbl_comfy_status.pack(side="left", padx=(10, 0))

        # Connection settings (host:port) — collapsed into a small row, only
        # really needed when ComfyUI isn't on the default localhost:8188.
        comfy_conn_row = ttk.Frame(self.frame_comfy)
        comfy_conn_row.pack(fill="x", pady=(6, 0))
        ttk.Label(comfy_conn_row, text="Host:", style="Dim.TLabel").pack(side="left")
        self.ent_comfy_host = ttk.Entry(comfy_conn_row, width=12)
        self.ent_comfy_host.insert(0, self.comfy_host)
        self.ent_comfy_host.pack(side="left", padx=(4, 10))
        ttk.Label(comfy_conn_row, text="Port:", style="Dim.TLabel").pack(side="left")
        self.ent_comfy_port = ttk.Entry(comfy_conn_row, width=6)
        self.ent_comfy_port.insert(0, str(self.comfy_port))
        self.ent_comfy_port.pack(side="left", padx=(4, 0))

        # Generation options — only meaningful once connected; built but
        # only packed/shown by on_comfy_toggle().
        self.frame_comfy_options = ttk.Frame(self.frame_comfy)

        seed_row = ttk.Frame(self.frame_comfy_options)
        seed_row.pack(fill="x", pady=(8, 4))
        ttk.Label(seed_row, text="Seed:", style="TLabel").pack(side="left", padx=(0, 8))
        self.radio_seed_random = ttk.Radiobutton(seed_row, text="Random", value="random",
                                                   variable=self.comfy_seed_mode,
                                                   command=self._on_comfy_seed_mode_changed)
        self.radio_seed_random.pack(side="left")
        self.radio_seed_fixed = ttk.Radiobutton(seed_row, text="Fixed:", value="fixed",
                                                  variable=self.comfy_seed_mode,
                                                  command=self._on_comfy_seed_mode_changed)
        self.radio_seed_fixed.pack(side="left", padx=(10, 4))
        self.ent_comfy_seed = ttk.Entry(seed_row, width=12, textvariable=self.comfy_seed_value, state="disabled")
        self.ent_comfy_seed.pack(side="left")

        res_row = ttk.Frame(self.frame_comfy_options)
        res_row.pack(fill="x", pady=(0, 4))
        ttk.Label(res_row, text="Resolution:", style="TLabel").pack(side="left", padx=(0, 8))
        self.combo_comfy_resolution = ttk.Combobox(
            res_row, state="readonly", width=20, textvariable=self.comfy_resolution_choice,
            values=[label for label, w, h in COMFY_RESOLUTION_PRESETS])
        self.combo_comfy_resolution.pack(side="left")
        self.combo_comfy_resolution.bind("<<ComboboxSelected>>", self._on_comfy_resolution_changed)
        ttk.Label(res_row, text="W:", style="Dim.TLabel").pack(side="left", padx=(10, 2))
        self.ent_comfy_width = ttk.Entry(res_row, width=6, textvariable=self.comfy_width_var, state="disabled")
        self.ent_comfy_width.pack(side="left")
        ttk.Label(res_row, text="H:", style="Dim.TLabel").pack(side="left", padx=(6, 2))
        self.ent_comfy_height = ttk.Entry(res_row, width=6, textvariable=self.comfy_height_var, state="disabled")
        self.ent_comfy_height.pack(side="left")

        # --- LoRA Settings (Task 4) ---
        # Built but not packed yet — shown only when ComfyUI is enabled+connected.
        self.frame_lora = ttk.LabelFrame(left, text=" ⚙️ LoRA ", padding=10)

        # Inner scrollable area: Canvas + Scrollbar + inner frame.
        # Same pattern as Gallery tab (Task 3).
        lora_canvas_frame = ttk.Frame(self.frame_lora)
        lora_canvas_frame.pack(fill="both", expand=True)

        lora_vscroll = ttk.Scrollbar(lora_canvas_frame, orient="vertical")
        lora_vscroll.pack(side="right", fill="y")

        self.lora_canvas = tk.Canvas(lora_canvas_frame, highlightthickness=0,
                                      yscrollcommand=lora_vscroll.set, height=130)
        self.lora_canvas.pack(side="left", fill="both", expand=True)
        lora_vscroll.configure(command=self.lora_canvas.yview)

        self.lora_inner_frame = ttk.Frame(self.lora_canvas)
        self._lora_canvas_window = self.lora_canvas.create_window(
            (0, 0), window=self.lora_inner_frame, anchor="nw")

        def _on_lora_inner_configure(e):
            self.lora_canvas.configure(scrollregion=self.lora_canvas.bbox("all"))
        def _on_lora_canvas_configure(e):
            self.lora_canvas.itemconfigure(self._lora_canvas_window, width=e.width)
        self.lora_inner_frame.bind("<Configure>", _on_lora_inner_configure)
        self.lora_canvas.bind("<Configure>", _on_lora_canvas_configure)

        # Bottom button row: Add LoRA
        lora_btn_row = ttk.Frame(self.frame_lora)
        lora_btn_row.pack(fill="x", pady=(6, 0))
        self.btn_lora_add = ttk.Button(lora_btn_row, text="+ Add LoRA",
                                        command=self._lora_add_slot)
        self.btn_lora_add.pack(side="left")

        self.btn_lora_clear_all = ttk.Button(lora_btn_row, text="🗑 Clear all",
                                              command=self._lora_clear_all)
        self.btn_lora_clear_all.pack(side="left", padx=(6, 0))

        # Build slots from persisted data (or start with 1 empty slot)
        self._build_lora_slots()

        # --- Actions ---
        self.actions_frame = ttk.Frame(left)
        self.actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))
        # Two independent buttons (Task 2): "Generate and copy" always builds
        # the prompt from the blocks/template and copies it — it never talks
        # to ComfyUI. "Generate in ComfyUI" is only shown once ComfyUI is
        # enabled+connected, and it submits whatever text currently sits in
        # txt_output (so manual edits to the result box are respected).
        self.btn_generate_copy = ttk.Button(self.actions_frame, text="⚡ Generate prompt and copy",
                                             style="Accent.TButton", command=self.on_generate_clicked)
        self.btn_generate_copy.pack(side="left", fill="x", expand=True)
        self.btn_generate_comfy = ttk.Button(self.actions_frame, text="🎨 Generate in ComfyUI",
                                              style="Accent.TButton", command=self.on_generate_in_comfy_clicked)
        # Not packed yet — on_comfy_toggle()/_on_comfy_check_done() pack it
        # in once comfy_enabled=True AND comfy_connected=True.
        btn_clear = ttk.Button(self.actions_frame, text="Clear all", style="Ghost.TButton", command=self.clear_forge)
        btn_clear.pack(side="left", padx=(8, 0))

        # --- Right column: result output ---
        result_frame = ttk.LabelFrame(right, text=" Result ", padding=12)
        result_frame.pack(fill="both", expand=True)

        self.txt_output = scrolledtext.ScrolledText(result_frame, font=self.mono_font, wrap=tk.WORD,
                                                      relief="flat", borderwidth=0)
        self.txt_output.pack(fill="both", expand=True)

        btn_row = ttk.Frame(result_frame)
        btn_row.pack(fill="x", pady=(8, 0))
        btn_copy_again = ttk.Button(btn_row, text="📋 Copy", command=self.copy_output_only)
        btn_copy_again.pack(side="left", fill="x", expand=True, padx=(0, 4))
        btn_fav = ttk.Button(btn_row, text="⭐ Add to favorites", command=self.favorite_last)
        btn_fav.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.lbl_copy_status = ttk.Label(result_frame, text="", style="Dim.TLabel")
        self.lbl_copy_status.pack(anchor="w", pady=(6, 0))

        # --- Last ComfyUI result preview (hidden until ComfyUI mode is on) ---
        self.frame_comfy_result = ttk.LabelFrame(right, text=" Latest ComfyUI image ", padding=12)
        # not packed immediately — only shown once ComfyUI mode is enabled

        comfy_result_header = ttk.Frame(self.frame_comfy_result)
        comfy_result_header.pack(fill="x", pady=(0, 4))
        ttk.Label(comfy_result_header, text="Size", style="Dim.TLabel").pack(side="left", padx=(0, 4))
        self.scale_comfy_result_zone = ttk.Scale(
            comfy_result_header, from_=ResultImageViewer.MIN_PERCENT, to=ResultImageViewer.MAX_PERCENT,
            orient="horizontal", command=self._on_comfy_result_zone_resize
        )
        self.scale_comfy_result_zone.set(self.comfy_result_zone_percent)
        self.scale_comfy_result_zone.pack(side="left", fill="x", expand=True)
        Tooltip(self.scale_comfy_result_zone, "Resize the latest-image preview — remembered between sessions.", self)

        self.comfy_result_zone = ResultImageViewer(self.frame_comfy_result, self.colors,
                                                     percent=self.comfy_result_zone_percent)
        self.comfy_result_zone.pack(fill="x")
        # NOTE: deliberately bound to the outer 'right' column, not to
        # frame_comfy_result itself. Binding to frame_comfy_result is
        # self-referential — that frame's own height depends on how tall
        # the canvas inside it is, so growing the canvas grows the frame,
        # which then reports a "bigger" height back in, but the whole
        # thing converges on a small stable point almost immediately and
        # the slider stops doing anything useful past a tiny size. 'right'
        # is the whole column (sized by the PanedWindow/window itself),
        # so it gives a stable, much larger basis — same pattern as
        # _on_library_panel_resize / image_drop_zone in the Library tab.
        right.bind("<Configure>", self._on_comfy_panel_resize, add="+")

        # Progress bar (shown while generating, hidden otherwise)
        self.frame_comfy_progress = ttk.Frame(self.frame_comfy_result)
        self.comfy_progress_var = tk.DoubleVar(value=0.0)
        self.comfy_progress_bar = ttk.Progressbar(
            self.frame_comfy_progress, variable=self.comfy_progress_var,
            maximum=100.0, mode="determinate", length=300)
        self.comfy_progress_bar.pack(side="left", fill="x", expand=True)
        self.lbl_comfy_progress = ttk.Label(
            self.frame_comfy_progress, text="", style="Dim.TLabel", width=12)
        self.lbl_comfy_progress.pack(side="left", padx=(8, 0))

        # Status + Open folder button row
        comfy_status_row = ttk.Frame(self.frame_comfy_result)
        comfy_status_row.pack(fill="x", pady=(6, 0))
        self.lbl_comfy_result_status = ttk.Label(comfy_status_row, text="", style="Dim.TLabel")
        self.lbl_comfy_result_status.pack(side="left", fill="x", expand=True)
        self.btn_comfy_open_folder = ttk.Button(
            comfy_status_row, text="📁 Open folder",
            command=self.comfy_open_output_folder, width=14)
        self.btn_comfy_open_folder.pack(side="right")
        self.btn_comfy_open_folder.pack_forget()  # hidden until first image

        self._last_generated = ""
        self.refresh_themed_widgets()

        # Force one sizing pass once the window has real geometry, instead
        # of waiting on the first <Configure> the user happens to trigger.
        self.root.update_idletasks()
        self._resize_comfy_result_zone(right.winfo_height())

    def _order_to_text(self):
        names = {"style": "Style", "characters": "Characters", "scenario": "Scenario"}
        return " → ".join(names[k] for k in self.block_order)

    def clear_forge(self):
        if not messagebox.askyesno("Clear", "Reset all selected builder blocks?"):
            return
        self.selected_style.set("None")
        self.selected_scenario.set("None")
        for slot in list(self.active_characters):
            slot["frame"].destroy()
        self.active_characters.clear()
        self.update_chars_placeholder()
        self.txt_output.delete("1.0", tk.END)
        self.lbl_copy_status.configure(text="")
        if hasattr(self, "comfy_result_zone"):
            self.comfy_result_zone.show_placeholder()
            self.lbl_comfy_result_status.configure(text="")
            self.comfy_last_image_path = None
            self.comfy_last_remote_filename = None
            self.comfy_last_remote_subfolder = None

    def update_chars_placeholder(self):
        if self.active_characters:
            self.placeholder_chars.pack_forget()
        else:
            self.placeholder_chars.pack(anchor="w", pady=10, padx=4)
        self.lbl_chars_count.configure(text=f"{len(self.active_characters)} character(s)")

    def update_live_preview(self):
        """Stub hook for possible live updates (reserved for future use)."""
        pass

    # ==========================================================
    #                      DIALOG HELPERS
    # ==========================================================
    def _finalize_dialog(self, dlg, min_w=360, min_h=200):
        """Sizes a Toplevel to actually fit everything that's packed inside it,
        then centers it over the main window. Must be called AFTER all the
        dialog's widgets have been created/packed, so Tk has a real layout to
        measure — this is what prevents a dialog from opening smaller than its
        own content (e.g. with buttons cut off) on systems where a hardcoded
        geometry string set before packing doesn't end up matching the final
        layout (DPI scaling, fonts, etc. all affect this)."""
        dlg.update_idletasks()
        req_w = max(min_w, dlg.winfo_reqwidth())
        req_h = max(min_h, dlg.winfo_reqheight())

        screen_w = dlg.winfo_screenwidth()
        screen_h = dlg.winfo_screenheight()
        width = min(req_w, int(screen_w * 0.92))
        height = min(req_h, int(screen_h * 0.92))

        try:
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width()
            root_h = self.root.winfo_height()
            x = root_x + (root_w - width) // 2
            y = root_y + (root_h - height) // 2
        except Exception:
            x = (screen_w - width) // 2
            y = (screen_h - height) // 2

        x = max(0, min(x, max(0, screen_w - width)))
        y = max(0, min(y, max(0, screen_h - height)))

        dlg.geometry(f"{width}x{height}+{x}+{y}")
        dlg.minsize(min(width, min_w), min(height, min_h))

    # ---- Block order dialog ----
    def open_order_dialog(self):
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("Prompt block order")
        dlg.configure(bg=c["bg"])
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Choose the block order from top to bottom:", style="TLabel").pack(anchor="w", padx=14, pady=(14, 6))

        names = {"style": "Style", "characters": "Characters", "scenario": "Scenario"}
        listbox = tk.Listbox(dlg, bg=c["bg_card"], fg=c["fg"], selectbackground=c["accent"],
                              selectforeground=c["accent_text"], font=self.default_font,
                              relief="flat", highlightthickness=0, activestyle="none", height=6)
        for key in self.block_order:
            listbox.insert(tk.END, names[key])
        listbox.pack(fill="both", expand=True, padx=14, pady=6)

        def move(delta):
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            new_idx = idx + delta
            if 0 <= new_idx < listbox.size():
                self.block_order[idx], self.block_order[new_idx] = self.block_order[new_idx], self.block_order[idx]
                val = listbox.get(idx)
                listbox.delete(idx)
                listbox.insert(new_idx, val)
                listbox.selection_set(new_idx)

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Button(btn_row, text="▲ Up", command=lambda: move(-1)).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="▼ Down", command=lambda: move(1)).pack(side="left", fill="x", expand=True, padx=(4, 0))

        def apply_and_close():
            self.order_display.configure(text=self._order_to_text())
            dlg.destroy()

        ttk.Button(dlg, text="Done", style="Accent.TButton", command=apply_and_close).pack(
            fill="x", padx=14, pady=(6, 14))

        self._finalize_dialog(dlg, min_w=380, min_h=320)

    # ---- Block order templates ----
    def refresh_template_combo(self):
        names = list(self.templates.keys())
        self.combo_template["values"] = ["— template —"] + names
        self.combo_template.set("— template —")

    def on_template_selected(self, _event=None):
        name = self.combo_template.get()
        if name in self.templates:
            self.block_order = list(self.templates[name])
            self.order_display.configure(text=self._order_to_text())

    def save_current_as_template(self):
        dlg = tk.Toplevel(self.root)
        c = self.colors
        dlg.title("Save template")
        dlg.configure(bg=c["bg"])
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Template name:", style="TLabel").pack(anchor="w", padx=14, pady=(14, 4))
        entry = ttk.Entry(dlg)
        entry.pack(fill="x", padx=14)
        entry.focus_set()

        def do_save():
            name = entry.get().strip()
            if not name:
                messagebox.showwarning("Error", "Enter a template name.")
                return
            self.templates[name] = list(self.block_order)
            self.save_json(self.TEMPLATES_FILE, self.templates)
            self.refresh_template_combo()
            self.combo_template.set(name)
            dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=14, pady=14)
        ttk.Button(btn_row, text="Cancel", style="Ghost.TButton", command=dlg.destroy).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(btn_row, text="💾 Save", style="Accent.TButton", command=do_save).pack(
            side="left", expand=True, fill="x", padx=(4, 0))

        self._finalize_dialog(dlg, min_w=360, min_h=170)

    # ==========================================================
    #          CUSTOM TEMPLATES (free-form text + variables)
    # ==========================================================
    def on_template_category_changed(self):
        """Toggles between "Standard" and "Custom" builder mode."""
        cat = self.combo_template_category.get()
        if cat == "Custom":
            self.tpl_controls_standard.pack_forget()
            self.tpl_controls_custom.pack(fill="x")
            self.standard_section.pack_forget()
            self.custom_section.pack(fill="both", expand=True)
            # Global negative-prompt field is hidden in Custom mode —
            # each custom template has its own field inside custom_section.
            self.frame_neg_prompt.pack_forget()
            # Task 5G: LoRA section stays visible in Custom mode too (when
            # ComfyUI is connected) — users may want LoRAs applied regardless
            # of which template category is active. Its pack position/values
            # are left untouched here, so current slot values are preserved.
            self.refresh_custom_template_combo()
            name = self.combo_custom_template.get()
            if name and name in self.custom_templates:
                self.build_custom_template_form(name)
            else:
                self.show_custom_placeholder()
        else:
            self.tpl_controls_custom.pack_forget()
            self.tpl_controls_standard.pack(fill="x")
            self.custom_section.pack_forget()
            self.standard_section.pack(fill="both", expand=True)
            # Restore global negative-prompt field in the correct position
            # (between standard_section and frame_comfy). Since pack(before=)
            # is not reliably supported, we re-pack the trailing frames
            # in the right order.
            # Task 5G: frame_lora is NOT forgotten/re-packed here — when
            # ComfyUI is connected it was already visible and unchanged
            # while in Custom mode, so touching it would only risk losing
            # its position or flashing the widget for no reason.
            self.frame_neg_prompt.pack_forget()
            self.frame_comfy.pack_forget()
            self.actions_frame.pack_forget()
            self.frame_neg_prompt.pack(fill="x", padx=(0, 10), pady=6)
            self.frame_comfy.pack(fill="x", padx=(0, 10), pady=6)
            # If frame_lora isn't visible yet (e.g. ComfyUI just connected
            # while we were in Custom mode), pack it now in the right slot.
            if self.comfy_connected and self.comfy_enabled.get():
                if not self.frame_lora.winfo_ismapped():
                    self.frame_lora.pack(fill="x", padx=(0, 10), pady=6)
            self.actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))

    def refresh_custom_template_combo(self):
        names = list(self.custom_templates.keys())
        self.combo_custom_template["values"] = names
        if not names:
            self.combo_custom_template.set("")
        elif self.combo_custom_template.get() not in names:
            self.combo_custom_template.set(names[0])

    def on_custom_template_selected(self, _event=None):
        name = self.combo_custom_template.get()
        if name in self.custom_templates:
            self.build_custom_template_form(name)

    def parse_custom_template(self, text):
        """Finds [Name N]/[Description N]/[Outfit N]/[Style]/[Scenario] variables in the template text."""
        name_idx, desc_idx, outfit_idx = set(), set(), set()
        use_style = use_scenario = False
        for m in CUSTOM_VAR_PATTERN.finditer(text or ""):
            kind, idx, style_kw, scen_kw = m.groups()
            if kind == "Name":
                name_idx.add(int(idx))
            elif kind == "Description":
                desc_idx.add(int(idx))
            elif kind == "Outfit":
                outfit_idx.add(int(idx))
            elif style_kw:
                use_style = True
            elif scen_kw:
                use_scenario = True
        return {
            "name_idx": name_idx, "desc_idx": desc_idx, "outfit_idx": outfit_idx,
            "use_style": use_style, "use_scenario": use_scenario,
        }

    def show_custom_placeholder(self):
        for child in self.custom_section.winfo_children():
            child.destroy()
        self.custom_active_slots = []
        self.custom_style_combo = None
        self.custom_scenario_combo = None
        self.current_custom_template_name = None
        self.current_custom_parsed = None
        ttk.Label(self.custom_section,
                  text="No custom templates have been created yet.\n"
                       "Click \"✏ Create template\" to write your first one — with your own text\n"
                       "and variables (character name/description/outfit, style, scenario).",
                  style="Dim.TLabel", justify="left").pack(anchor="w", pady=20, padx=4)

    def build_custom_template_form(self, name):
        """Builds the dynamic builder form for a specific custom template."""
        for child in self.custom_section.winfo_children():
            child.destroy()
        self.custom_active_slots = []
        self.custom_style_combo = None
        self.custom_scenario_combo = None
        self.current_custom_template_name = name

        text = self.custom_templates.get(name, {}).get("text", "")
        parsed = self.parse_custom_template(text)
        self.current_custom_parsed = parsed

        header = ttk.Frame(self.custom_section)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text=f"📄 {name}", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="✏ Edit",
                   command=lambda: self.open_custom_template_editor(name)).pack(side="right")

        slot_indices = sorted(set(parsed["name_idx"]) | set(parsed["desc_idx"]) | set(parsed["outfit_idx"]))

        if slot_indices:
            chars_frame = ttk.LabelFrame(self.custom_section, text=" Template Characters ", padding=12)
            chars_frame.pack(fill="x", pady=6)
            for idx in slot_indices:
                row = ttk.Frame(chars_frame, style="Card.TFrame", padding=10)
                row.pack(fill="x", pady=4)
                ttk.Label(row, text=f"Character {idx}:", style="CardTitle.TLabel").pack(anchor="w")

                who_row = ttk.Frame(row, style="Card.TFrame")
                who_row.pack(fill="x", pady=(6, 0))
                ttk.Label(who_row, text="Who:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
                char_var = tk.StringVar()
                combo_char = AutocompleteCombobox(who_row, textvariable=char_var)
                combo_char["values"] = ["None"] + self.get_file_list("characters")
                combo_char.current(0)
                combo_char.pack(side="left", fill="x", expand=True)

                outfit_var = tk.StringVar()
                outfit_combo = None
                if idx in parsed["outfit_idx"]:
                    outfit_row = ttk.Frame(row, style="Card.TFrame")
                    outfit_row.pack(fill="x", pady=(6, 0))
                    ttk.Label(outfit_row, text="Outfit:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
                    outfit_combo = AutocompleteCombobox(outfit_row, textvariable=outfit_var)
                    outfit_combo["values"] = ["None"]
                    outfit_combo.current(0)
                    outfit_combo.pack(side="left", fill="x", expand=True)
                    # add="+" so this doesn't clobber AutocompleteCombobox's
                    # own internal <<ComboboxSelected>> binding.
                    combo_char.bind("<<ComboboxSelected>>",
                                     lambda e, cv=char_var, co=outfit_combo: self.update_outfit_list(cv, co),
                                     add="+")

                self.custom_active_slots.append({
                    "index": idx, "char_var": char_var, "char_combo": combo_char,
                    "outfit_var": outfit_var, "outfit_combo": outfit_combo,
                })
        else:
            ttk.Label(self.custom_section, text="This template doesn't use any characters.",
                      style="Dim.TLabel").pack(anchor="w", pady=6)

        if parsed["use_style"]:
            style_frame = ttk.LabelFrame(self.custom_section, text=" Style ", padding=12)
            style_frame.pack(fill="x", pady=6)
            self.custom_style_var.set("None")
            self.custom_style_combo = AutocompleteCombobox(style_frame, textvariable=self.custom_style_var)
            self.custom_style_combo["values"] = ["None"] + self.get_file_list("styles")
            self.custom_style_combo.current(0)
            self.custom_style_combo.pack(fill="x")

        if parsed["use_scenario"]:
            scen_frame = ttk.LabelFrame(self.custom_section, text=" Scenario ", padding=12)
            scen_frame.pack(fill="x", pady=6)
            self.custom_scenario_var.set("None")
            self.custom_scenario_combo = AutocompleteCombobox(scen_frame, textvariable=self.custom_scenario_var)
            self.custom_scenario_combo["values"] = ["None"] + self.get_file_list("scenarios")
            self.custom_scenario_combo.current(0)
            self.custom_scenario_combo.pack(fill="x")

        if not slot_indices and not parsed["use_style"] and not parsed["use_scenario"]:
            ttk.Label(self.custom_section, text="This template consists only of fixed text.",
                      style="Dim.TLabel").pack(anchor="w", pady=6)

        # Negative prompt field — stored per-template in the JSON structure
        neg_frame = ttk.LabelFrame(self.custom_section, text=" Negative prompt ", padding=12)
        neg_frame.pack(fill="x", pady=6)
        self.txt_neg_prompt_custom = scrolledtext.ScrolledText(
            neg_frame, font=self.mono_font, wrap=tk.WORD,
            relief="flat", borderwidth=0, height=3)
        self.txt_neg_prompt_custom.pack(fill="x")
        neg_saved = self.custom_templates.get(name, {}).get("negative_prompt", "")
        if neg_saved:
            self.txt_neg_prompt_custom.insert("1.0", neg_saved)
        # Apply current theme colors immediately (the widget is tk, not ttk)
        c = self.colors
        self.txt_neg_prompt_custom.configure(
            bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
            selectbackground=c["accent"], selectforeground=c["accent_text"])
        self.txt_neg_prompt_custom.bind(
            "<<Modified>>",
            lambda e: self._on_neg_prompt_custom_changed())

    def delete_selected_custom_template(self):
        name = self.combo_custom_template.get()
        if not name or name not in self.custom_templates:
            messagebox.showinfo("Delete template", "First select a custom template from the list.")
            return
        if not messagebox.askyesno("Delete template", f"Delete the custom template \"{name}\"?"):
            return
        del self.custom_templates[name]
        self.save_json(self.CUSTOM_TEMPLATES_FILE, self.custom_templates)
        self.refresh_custom_template_combo()
        new_name = self.combo_custom_template.get()
        if new_name:
            self.build_custom_template_form(new_name)
        else:
            self.show_custom_placeholder()

    def open_custom_template_editor(self, edit_name=None):
        """Text editor for a custom template with buttons to insert variables."""
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("Edit custom template" if edit_name else "New custom template")
        dlg.configure(bg=c["bg"])
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Template name:", style="TLabel").pack(anchor="w", padx=14, pady=(14, 4))
        entry_name = ttk.Entry(dlg)
        entry_name.pack(fill="x", padx=14)

        ttk.Label(dlg, text="Template text — write it like a normal prompt, and insert variables using the buttons below:",
                  style="TLabel", wraplength=600, justify="left").pack(anchor="w", padx=14, pady=(12, 4))

        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, font=self.default_font,
                                         bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                                         selectbackground=c["accent"], selectforeground=c["accent_text"],
                                         relief="flat", borderwidth=0, height=12)
        txt.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        if edit_name and edit_name in self.custom_templates:
            entry_name.insert(0, edit_name)
            txt.insert("1.0", self.custom_templates[edit_name].get("text", ""))
        entry_name.focus_set()

        def insert_var(kind):
            if kind in ("Name", "Description", "Outfit"):
                current = txt.get("1.0", tk.END)
                existing = [int(m.group(2)) for m in CUSTOM_VAR_PATTERN.finditer(current) if m.group(1) == kind]
                next_idx = (max(existing) + 1) if existing else 1
                token = f"[{kind} {next_idx}]"
            else:
                token = f"[{kind}]"
            txt.insert(tk.INSERT, token)
            txt.focus_set()

        toolbar = ttk.LabelFrame(dlg, text=" Insert variable ", padding=8)
        toolbar.pack(fill="x", padx=14, pady=(0, 10))

        btns_row1 = ttk.Frame(toolbar)
        btns_row1.pack(fill="x", pady=(0, 4))
        ttk.Button(btns_row1, text="＋ Character Name",
                   command=lambda: insert_var("Name")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns_row1, text="＋ Character Description",
                   command=lambda: insert_var("Description")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns_row1, text="＋ Character Outfit",
                   command=lambda: insert_var("Outfit")).pack(side="left", expand=True, fill="x", padx=2)

        btns_row2 = ttk.Frame(toolbar)
        btns_row2.pack(fill="x")
        ttk.Button(btns_row2, text="＋ Style",
                   command=lambda: insert_var("Style")).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(btns_row2, text="＋ Scenario",
                   command=lambda: insert_var("Scenario")).pack(side="left", expand=True, fill="x", padx=2)

        ttk.Label(dlg,
                  text="Each click on \"Name/Description/Outfit\" adds a variable for the next "
                       "template character in sequence (1, 2, 3…). Only the fields you actually "
                       "used here will appear in the builder — if you don't need a style or outfit, just don't add them.",
                  style="Dim.TLabel", wraplength=600, justify="left").pack(anchor="w", padx=14, pady=(0, 8))

        def do_save():
            name = entry_name.get().strip()
            body = txt.get("1.0", tk.END).strip()
            if not name:
                messagebox.showwarning("Error", "Enter a template name.")
                return
            if not body:
                messagebox.showwarning("Error", "Template text cannot be empty.")
                return
            if edit_name and edit_name != name and edit_name in self.custom_templates:
                del self.custom_templates[edit_name]
            self.custom_templates[name] = {"text": body}
            self.save_json(self.CUSTOM_TEMPLATES_FILE, self.custom_templates)
            self.refresh_custom_template_combo()
            self.combo_custom_template.set(name)
            self.build_custom_template_form(name)
            dlg.destroy()

        def do_delete():
            if edit_name and edit_name in self.custom_templates:
                if messagebox.askyesno("Delete template", f"Delete the template \"{edit_name}\"?"):
                    del self.custom_templates[edit_name]
                    self.save_json(self.CUSTOM_TEMPLATES_FILE, self.custom_templates)
                    self.refresh_custom_template_combo()
                    new_name = self.combo_custom_template.get()
                    if new_name:
                        self.build_custom_template_form(new_name)
                    else:
                        self.show_custom_placeholder()
                    dlg.destroy()

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        if edit_name:
            ttk.Button(btn_row, text="🗑 Delete", style="Danger.TButton", command=do_delete).pack(
                side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", style="Ghost.TButton", command=dlg.destroy).pack(
            side="left", expand=True, fill="x", padx=4)
        ttk.Button(btn_row, text="💾 Save", style="Accent.TButton", command=do_save).pack(
            side="left", expand=True, fill="x", padx=4)

        self._finalize_dialog(dlg, min_w=680, min_h=600)

    def generate_custom_prompt(self):
        """Assembles the final prompt from the custom template text and selected variables."""
        name = self.current_custom_template_name
        if not name or name not in self.custom_templates:
            messagebox.showinfo("Custom template", "First select or create a custom template.")
            return

        text = self.custom_templates[name].get("text", "")
        parsed = self.current_custom_parsed or self.parse_custom_template(text)

        name_vals, desc_vals, outfit_vals = {}, {}, {}
        for slot in self.custom_active_slots:
            idx = slot["index"]
            char_name = slot["char_var"].get()
            if char_name and char_name != "None":
                name_vals[idx] = char_name
                desc_vals[idx] = self.read_file_content("characters", char_name)
            else:
                name_vals[idx] = ""
                desc_vals[idx] = ""

            o_selection = slot["outfit_var"].get()
            if o_selection and o_selection != "None":
                if o_selection.startswith("Canon "):
                    c_num = o_selection.split(" ")[1]
                    outfit_vals[idx] = self.read_file_content("outfits", f"{char_name}_Canon_{c_num}")
                else:
                    outfit_vals[idx] = self.read_file_content("outfits", o_selection)
            else:
                outfit_vals[idx] = ""

        style_val = ""
        if parsed["use_style"] and self.custom_style_combo is not None:
            sv = self.custom_style_var.get()
            if sv and sv != "None":
                style_val = self.read_file_content("styles", sv)

        scenario_val = ""
        if parsed["use_scenario"] and self.custom_scenario_combo is not None:
            scv = self.custom_scenario_var.get()
            if scv and scv != "None":
                scenario_val = self.read_file_content("scenarios", scv)

        def repl(m):
            kind, idx, style_kw, scen_kw = m.groups()
            if kind == "Name":
                return name_vals.get(int(idx), "")
            if kind == "Description":
                return desc_vals.get(int(idx), "")
            if kind == "Outfit":
                return outfit_vals.get(int(idx), "")
            if style_kw:
                return style_val
            if scen_kw:
                return scenario_val
            return ""

        final_prompt = CUSTOM_VAR_PATTERN.sub(repl, text)
        # light cleanup of extra spaces/empty lines left behind by empty variables
        final_prompt = re.sub(r"[ \t]{2,}", " ", final_prompt)
        final_prompt = "\n".join(line.strip() for line in final_prompt.split("\n"))
        final_prompt = re.sub(r"\n{3,}", "\n\n", final_prompt).strip()

        if not final_prompt:
            messagebox.showinfo("Empty prompt", "Fill in at least one template variable.")
            return

        self._finalize_generated_prompt(final_prompt)

    # ---- Characters ----
    def add_character_slot(self):
        """Adds a row for selecting a character and their outfit"""
        c = self.colors
        slot_frame = ttk.Frame(self.scroll_chars, style="Card.TFrame", padding=10)
        slot_frame.pack(fill="x", pady=5, padx=2)

        char_var = tk.StringVar()
        outfit_var = tk.StringVar()

        top_row = ttk.Frame(slot_frame, style="Card.TFrame")
        top_row.pack(fill="x")

        idx_label = ttk.Label(top_row, text=f"Character {len(self.active_characters) + 1}",
                               style="CardTitle.TLabel")
        idx_label.pack(side="left")

        btn_remove = ttk.Button(top_row, text="✕", width=3, style="Ghost.TButton")
        btn_remove.pack(side="right")
        Tooltip(btn_remove, "Remove character", self)

        who_row = ttk.Frame(slot_frame, style="Card.TFrame")
        who_row.pack(fill="x", pady=(8, 0))

        ttk.Label(who_row, text="Who:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        combo_char = AutocompleteCombobox(who_row, textvariable=char_var)
        combo_char["values"] = ["None"] + self.get_file_list("characters")
        combo_char.current(0)
        combo_char.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_char_preview = ttk.Button(who_row, text="👁", width=3,
                                       command=lambda cv=char_var: self.quick_preview("characters", cv))
        btn_char_preview.pack(side="left")
        Tooltip(btn_char_preview, "Show character description", self)

        outfit_row = ttk.Frame(slot_frame, style="Card.TFrame")
        outfit_row.pack(fill="x", pady=(6, 0))

        ttk.Label(outfit_row, text="Outfit:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        combo_outfit = AutocompleteCombobox(outfit_row, textvariable=outfit_var)
        combo_outfit["values"] = ["None"]
        combo_outfit.current(0)
        combo_outfit.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_outfit_preview = ttk.Button(outfit_row, text="👁", width=3,
                                         command=lambda ov=outfit_var, cv=char_var: self.quick_preview_outfit(cv, ov))
        btn_outfit_preview.pack(side="left")
        Tooltip(btn_outfit_preview, "Show outfit description", self)

        # add="+" so this doesn't clobber AutocompleteCombobox's own
        # internal <<ComboboxSelected>> binding (commit/restore-list logic).
        combo_char.bind("<<ComboboxSelected>>",
                         lambda event, cv=char_var, co=combo_outfit: self.update_outfit_list(cv, co),
                         add="+")

        slot_info = {
            "frame": slot_frame,
            "char_var": char_var,
            "outfit_var": outfit_var,
            "outfit_combo": combo_outfit,
            "char_combo": combo_char,
            "idx_label": idx_label,
        }
        btn_remove.configure(command=lambda info=slot_info: self.remove_character_slot(info))

        self.active_characters.append(slot_info)
        self.update_chars_placeholder()

    def remove_character_slot(self, info):
        info["frame"].destroy()
        self.active_characters.remove(info)
        # renumber the remaining ones
        for i, slot in enumerate(self.active_characters, start=1):
            slot["idx_label"].configure(text=f"Character {i}")
        self.update_chars_placeholder()

    def update_outfit_list(self, char_var, outfit_combo):
        """Looks up canon outfits for a specific character + shared outfits"""
        char_name = char_var.get()
        if not char_name or char_name == "None":
            outfit_combo["values"] = ["None"]
            outfit_combo.current(0)
            return

        outfits = ["None"]
        outfit_path = os.path.join(self.DATA_DIR, "outfits")
        canon_pattern = os.path.join(outfit_path, f"{char_name}_Canon_*.txt")
        canon_files = glob.glob(canon_pattern)

        for f in sorted(canon_files):
            base = os.path.basename(f).replace(".txt", "")
            parts = base.split("_Canon_")
            if len(parts) > 1:
                outfits.append(f"Canon {parts[1]}")

        all_outfits = self.get_file_list("outfits")
        for o in all_outfits:
            if "_Canon_" not in o:
                outfits.append(o)

        outfit_combo["values"] = outfits
        outfit_combo.current(0)

    def quick_preview(self, category, string_var):
        name = string_var.get()
        if not name or name == "None":
            messagebox.showinfo("Preview", "Nothing is selected.")
            return
        content = self.read_file_content(category, name)
        self._show_preview_dialog(f"{CATEGORY_LABELS.get(category, category)}: {name}", content or "(empty)")

    def quick_preview_outfit(self, char_var, outfit_var):
        o_selection = outfit_var.get()
        c_name = char_var.get()
        if not o_selection or o_selection == "None":
            messagebox.showinfo("Preview", "Nothing is selected.")
            return
        if o_selection.startswith("Canon "):
            c_num = o_selection.split(" ")[1]
            content = self.read_file_content("outfits", f"{c_name}_Canon_{c_num}")
            title = f"Outfit: {c_name} — Canon {c_num}"
        else:
            content = self.read_file_content("outfits", o_selection)
            title = f"Outfit: {o_selection}"
        self._show_preview_dialog(title, content or "(empty)")

    def _show_preview_dialog(self, title, content):
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=c["bg"])
        ttk.Label(dlg, text=title, style="Title.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, font=self.default_font,
                                         bg=c["bg_input"], fg=c["fg"], relief="flat", borderwidth=0)
        txt.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        txt.insert("1.0", content)
        txt.configure(state="disabled")

        ttk.Button(dlg, text="Close", style="Ghost.TButton", command=dlg.destroy).pack(
            fill="x", padx=14, pady=(0, 14))

        self._finalize_dialog(dlg, min_w=480, min_h=320)

    # ==========================================================
    #          TAB 2: LIBRARY (PRESET MANAGER)
    # ==========================================================
    def build_library_tab(self):
        c = self.colors
        paned = ttk.PanedWindow(self.tab_library, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # ---------- LEFT: library entry list ----------
        left = ttk.Frame(paned, padding=(0, 0, 10, 0))
        paned.add(left, weight=2)

        cats_row = ttk.Frame(left)
        cats_row.pack(fill="x", pady=(0, 8))
        self.lib_cat_buttons = {}
        for cat in self.CATEGORIES:
            btn = ttk.Button(cats_row, text=f"{CATEGORY_ICONS[cat]} {CATEGORY_LABELS[cat]}",
                              command=lambda cc=cat: self.switch_library_category(cc))
            btn.pack(side="left", fill="x", expand=True, padx=2)
            self.lib_cat_buttons[cat] = btn

        search_row = ttk.Frame(left)
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="🔎", style="TLabel").pack(side="left", padx=(0, 6))
        self.ent_search = ttk.Entry(search_row, textvariable=self.lib_search_var)
        self.ent_search.pack(side="left", fill="x", expand=True)
        self.lib_search_var.trace_add("write", lambda *a: self.refresh_library_list())
        btn_search_clear = ttk.Button(search_row, text="✕", width=3,
                                       command=lambda: self.lib_search_var.set(""))
        btn_search_clear.pack(side="left", padx=(6, 0))

        list_holder = ttk.Frame(left)
        list_holder.pack(fill="both", expand=True)

        columns = ("name", "tags")
        self.tree_library = ttk.Treeview(list_holder, columns=columns, show="headings", selectmode="browse")
        self.tree_library.heading("name", text="Name")
        self.tree_library.heading("tags", text="Tags preview")
        self.tree_library.column("name", width=180, anchor="w")
        self.tree_library.column("tags", width=260, anchor="w")
        self.tree_library.pack(side="left", fill="both", expand=True)
        self.tree_library.bind("<<TreeviewSelect>>", self.on_library_select)

        tree_scroll = ttk.Scrollbar(list_holder, orient="vertical", command=self.tree_library.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree_library.configure(yscrollcommand=tree_scroll.set)

        count_row = ttk.Frame(left)
        count_row.pack(fill="x", pady=(6, 0))
        self.lbl_lib_count = ttk.Label(count_row, text="0 entries", style="Dim.TLabel")
        self.lbl_lib_count.pack(side="left")

        # ---------- RIGHT: entry editor ----------
        right = ttk.LabelFrame(paned, text=" Entry Editor ", padding=14)
        paned.add(right, weight=3)

        # The entry category is determined by the tab buttons on the left (lib_cat_buttons).
        # combo_lib_cat is kept as a hidden state source for the logic written
        # around it (toggle_library_outfit_options, etc.), but it is NOT shown
        # in the interface — the category is displayed by the label below instead.
        self.combo_lib_cat = ttk.Combobox(right, values=self.CATEGORIES, state="readonly")
        self.combo_lib_cat.current(0)
        self.combo_lib_cat.bind("<<ComboboxSelected>>", self.toggle_library_outfit_options)

        self.lbl_lib_editing_cat = ttk.Label(right, text="", style="CardDim.TLabel")
        self.lbl_lib_editing_cat.pack(anchor="w", pady=(0, 8))

        # "Canon outfit" block — shown ONLY for the "outfits" category.
        self.frame_canon_binding = ttk.Frame(right)

        self.is_canon_var = tk.BooleanVar()
        self.chk_canon = ttk.Checkbutton(self.frame_canon_binding, text="Is this a character's canon outfit?",
                                          variable=self.is_canon_var, command=self.toggle_canon_char_selector)
        self.chk_canon.pack(anchor="w", pady=4)

        self.combo_canon_char = ttk.Combobox(self.frame_canon_binding, state="disabled")
        self.combo_canon_char.pack(fill="x", pady=4)

        self.ent_lib_name_label = ttk.Label(right, text="Name:", style="TLabel")
        self.ent_lib_name_label.pack(anchor="w", pady=(6, 2))
        self.ent_lib_name = ttk.Entry(right)
        self.ent_lib_name.pack(fill="x", pady=(0, 10))

        tags_label_row = ttk.Frame(right)
        tags_label_row.pack(fill="x")
        ttk.Label(tags_label_row, text="Tags / content:", style="TLabel").pack(side="left")

        self.txt_lib_tags = scrolledtext.ScrolledText(right, height=6, font=self.default_font, wrap=tk.WORD,
                                                         relief="flat", borderwidth=0,
                                                         bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                                                         selectbackground=c["accent"], selectforeground=c["accent_text"])
        self.txt_lib_tags.pack(fill="both", expand=True, pady=8)

        # ---- Image preview / drag'n'drop zone ----
        zone_header = ttk.Frame(right)
        zone_header.pack(fill="x", pady=(0, 4))
        ttk.Label(zone_header, text="Image:", style="TLabel").pack(side="left")
        ttk.Label(zone_header, text="Size", style="Dim.TLabel").pack(side="left", padx=(14, 4))
        self.scale_image_zone = ttk.Scale(
            zone_header, from_=ImageDropZone.MIN_PERCENT, to=ImageDropZone.MAX_PERCENT,
            orient="horizontal", command=self._on_image_zone_resize
        )
        self.scale_image_zone.set(self.lib_image_zone_percent)
        self.scale_image_zone.pack(side="left", fill="x", expand=True, padx=(0, 4))
        Tooltip(self.scale_image_zone, "Resize the image preview — applies to every category and is remembered.", self)

        self.image_drop_zone = ImageDropZone(right, self.colors, on_file_chosen=self.handle_image_drop,
                                              percent=self.lib_image_zone_percent)
        self.image_drop_zone.pack(fill="x", pady=(0, 8))
        # The zone's height tracks a percentage of the whole Entry Editor
        # panel's height, so it scales sensibly from 1080p to 4K instead of
        # staying pinned at a fixed pixel size.
        right.bind("<Configure>", self._on_library_panel_resize, add="+")

        # ---- Source URL (Task 6) ----
        self.frame_lib_source = ttk.Frame(right)
        self.frame_lib_source.pack(fill="x", pady=(0, 6))
        self._build_lib_source_row()

        # ---- LoRA binding (Task 7.1) — only shown when ComfyUI is connected ----
        self.frame_lib_lora = ttk.Frame(right)
        # Packed/unpacked by _refresh_lib_lora_visibility(), not here —
        # visibility depends on self.comfy_connected which can change
        # after this tab is already built.
        self._build_lib_lora_row()
        self._refresh_lib_lora_visibility()

        btn_row = ttk.Frame(right)
        btn_row.pack(fill="x", pady=(4, 0))
        self.btn_lib_save = ttk.Button(btn_row, text="💾 Save", style="Accent.TButton",
                                        command=self.save_to_library)
        self.btn_lib_save.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_lib_new = ttk.Button(btn_row, text="＋ New entry", command=self.start_new_library_entry)
        self.btn_lib_new.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_lib_duplicate = ttk.Button(btn_row, text="⧉ Duplicate", command=self.duplicate_library_entry)
        self.btn_lib_duplicate.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_lib_delete = ttk.Button(btn_row, text="🗑 Delete", style="Danger.TButton",
                                          command=self.delete_library_entry)
        self.btn_lib_delete.pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.lbl_lib_status = ttk.Label(right, text="", style="Dim.TLabel")
        self.lbl_lib_status.pack(anchor="w", pady=(8, 0))

        self._apply_library_category("styles")

        # Force one sizing pass once the window has real geometry, instead
        # of waiting on the first <Configure> the user happens to trigger.
        self.root.update_idletasks()
        self.image_drop_zone.apply_panel_height(right.winfo_height())

    def _highlight_category_button(self, active_cat):
        for cat, btn in self.lib_cat_buttons.items():
            btn.configure(style="Accent.TButton" if cat == active_cat else "TButton")

    def switch_library_category(self, cat):
        """Switches the category using the tab buttons on the left."""
        self.combo_lib_cat.set(cat)
        self._apply_library_category(cat)
        self.start_new_library_entry(keep_category=True)

    def toggle_library_outfit_options(self, event=None):
        """Switches the category using the combobox itself."""
        cat = self.combo_lib_cat.get()
        self._apply_library_category(cat)

    def _apply_library_category(self, cat):
        self.lib_current_category = cat
        self.lbl_lib_editing_cat.configure(
            text=f"{CATEGORY_ICONS.get(cat, '')} Editing: {CATEGORY_LABELS.get(cat, cat)}")
        if cat == "outfits":
            self.frame_canon_binding.pack(fill="x", pady=(0, 10), before=self.ent_lib_name_label)
            self.chk_canon.configure(state="normal")
            self.combo_canon_char["values"] = self.get_file_list("characters")
        else:
            self.is_canon_var.set(False)
            self.frame_canon_binding.pack_forget()
            self.chk_canon.configure(state="disabled")
            self.combo_canon_char.configure(state="disabled")
        self._highlight_category_button(cat)
        self.refresh_library_list()

    def toggle_canon_char_selector(self):
        if self.is_canon_var.get():
            self.combo_canon_char.configure(state="readonly")
            self.ent_lib_name.configure(state="disabled")
        else:
            self.combo_canon_char.configure(state="disabled")
            self.ent_lib_name.configure(state="normal")

    # ==========================================================
    #         TASK 6 — SOURCE URL (Civitai etc.)
    # ==========================================================
    def _build_lib_source_row(self):
        """Builds the (initially view-mode, empty) Source URL row inside
        self.frame_lib_source. Rebuilt from scratch on every render via
        _render_lib_source_row() rather than juggling widget visibility,
        since the row alternates between three quite different shapes
        (no link / view link / edit link)."""
        self._render_lib_source_row()

    def _clear_frame(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def _render_lib_source_row(self):
        c = self.colors
        self._clear_frame(self.frame_lib_source)

        if self.lib_source_editing:
            row = ttk.Frame(self.frame_lib_source)
            row.pack(fill="x")
            ttk.Label(row, text="🔗", style="TLabel").pack(side="left", padx=(0, 4))
            self.ent_lib_source_url = ttk.Entry(row)
            self.ent_lib_source_url.pack(side="left", fill="x", expand=True)
            if self.lib_source_url:
                self.ent_lib_source_url.insert(0, self.lib_source_url)
            self.ent_lib_source_url.bind("<Return>", lambda e: self._save_lib_source_url())
            btn_save = ttk.Button(row, text="Save", command=self._save_lib_source_url)
            btn_save.pack(side="left", padx=(6, 0))
            btn_cancel = ttk.Button(row, text="Cancel", command=self._cancel_lib_source_edit)
            btn_cancel.pack(side="left", padx=(4, 0))
            self.lbl_lib_source_error = tk.Label(self.frame_lib_source, text="", fg=c["danger"], bg=c["bg_card"],
                                                  font=self.small_font)
            self.lbl_lib_source_error.pack(anchor="w", pady=(2, 0))
            self.ent_lib_source_url.focus_set()
        elif self.lib_source_url:
            row = ttk.Frame(self.frame_lib_source)
            row.pack(fill="x")
            ttk.Label(row, text="🔗 Source:", style="TLabel").pack(side="left", padx=(0, 6))
            link = tk.Label(row, text=self.lib_source_url, fg=c["accent"], bg=c["bg_card"],
                             font=self.default_font, cursor="hand2")
            # underline via font tuple keeps it consistent across themes/platforms
            link.configure(font=(self.default_font[0], self.default_font[1], "underline"))
            link.pack(side="left", fill="x", expand=True)
            link.bind("<Button-1>", lambda e: webbrowser.open(self.lib_source_url))
            btn_edit = ttk.Button(row, text="Edit", command=self._start_lib_source_edit)
            btn_edit.pack(side="left", padx=(6, 0))
        else:
            row = ttk.Frame(self.frame_lib_source)
            row.pack(fill="x")
            btn_add = ttk.Button(row, text="+ Add source link", command=self._start_lib_source_edit)
            btn_add.pack(side="left")

    def _start_lib_source_edit(self):
        self.lib_source_editing = True
        self._render_lib_source_row()

    def _cancel_lib_source_edit(self):
        self.lib_source_editing = False
        self._render_lib_source_row()

    def _save_lib_source_url(self):
        url = self.ent_lib_source_url.get().strip()
        if url and not (url.startswith("http://") or url.startswith("https://")):
            self.lbl_lib_source_error.configure(text="URL must start with http:// or https://")
            return
        self.lib_source_url = url or None
        self.lib_source_editing = False
        self._render_lib_source_row()
        # Persisted immediately (not only on the main Save button) so the
        # link survives even if the user never touches the tags/name field
        # again this session — matches how the image drop zone behaves.
        self._persist_current_lib_meta()

    # ==========================================================
    #         TASK 7.1 — LoRA BINDING for library entries
    # ==========================================================
    def _refresh_lib_lora_visibility(self):
        """LoRA binding row is only meaningful when ComfyUI is connected —
        self._available_loras (the Assign source) is otherwise empty/stale."""
        if not hasattr(self, "frame_lib_lora"):
            return
        if self.comfy_connected:
            if not self.frame_lib_lora.winfo_ismapped():
                self.frame_lib_lora.pack(fill="x", pady=(0, 6), after=self.frame_lib_source)
        else:
            self.frame_lib_lora.pack_forget()

    def _build_lib_lora_row(self):
        self._render_lib_lora_row()

    def _render_lib_lora_row(self):
        self._clear_frame(self.frame_lib_lora)
        row = ttk.Frame(self.frame_lib_lora)
        row.pack(fill="x")
        display = os.path.basename(self.lib_entry_lora) if self.lib_entry_lora else "None"
        ttk.Label(row, text=f"⚙️ LoRA: {display}", style="TLabel").pack(side="left", padx=(0, 6))
        btn_assign = ttk.Button(row, text="Assign", command=self._assign_lib_lora)
        btn_assign.pack(side="left", padx=(0, 4))
        btn_clear = ttk.Button(row, text="Clear", command=self._clear_lib_lora)
        btn_clear.pack(side="left")

    def _assign_lib_lora(self):
        """Shows a small popup list of self._available_loras (same source
        as the LoRA Manager) and binds the chosen one to the entry."""
        if not self._available_loras:
            messagebox.showinfo("LoRA", "No LoRAs available yet — make sure ComfyUI is connected "
                                          "and the LoRA list has finished loading.")
            return
        c = self.colors
        popup = tk.Toplevel(self.root)
        popup.title("Assign LoRA")
        popup.configure(bg=c["bg_card"])
        popup.transient(self.root)
        popup.geometry("420x360")

        ttk.Label(popup, text="Select a LoRA to bind to this entry:", style="TLabel").pack(
            anchor="w", padx=10, pady=(10, 4))

        search_var = tk.StringVar()
        ent = ttk.Entry(popup, textvariable=search_var)
        ent.pack(fill="x", padx=10, pady=(0, 6))

        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=10)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, exportselection=False, bg=c["bg_input"], fg=c["fg"],
                              selectbackground=c["accent"], selectforeground=c["accent_text"],
                              yscrollcommand=scrollbar.set)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=listbox.yview)

        def _populate(filter_text=""):
            listbox.delete(0, tk.END)
            needle = filter_text.lower()
            for lora in self._available_loras:
                if not needle or needle in lora.lower():
                    listbox.insert(tk.END, lora)

        _populate()
        search_var.trace_add("write", lambda *_: _populate(search_var.get()))

        def _commit(_event=None):
            sel = listbox.curselection()
            if not sel:
                return
            self.lib_entry_lora = listbox.get(sel[0])
            self._render_lib_lora_row()
            self._persist_current_lib_meta()
            popup.destroy()

        listbox.bind("<Double-Button-1>", _commit)
        btn_row = ttk.Frame(popup)
        btn_row.pack(fill="x", padx=10, pady=10)
        ttk.Button(btn_row, text="Assign", style="Accent.TButton", command=_commit).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", command=popup.destroy).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ent.focus_set()

    def _clear_lib_lora(self):
        self.lib_entry_lora = None
        self._render_lib_lora_row()
        self._persist_current_lib_meta()

    def _persist_current_lib_meta(self):
        """Writes the metadata sidecar for the entry currently open in the
        editor, if it has actually been saved to disk yet (self.lib_selected_file
        is None for a brand-new, not-yet-saved entry — its source_url/lora
        choices are picked up later by save_to_library() instead)."""
        if not self.lib_selected_file:
            return
        cat = self.lib_current_category
        name = (self.lib_editing_canon_owner[0] + "_Canon_" + self.lib_editing_canon_owner[1]
                if (cat == "outfits" and self.lib_editing_canon_owner) else self.lib_selected_file)
        self.save_library_meta(cat, name, source_url=self.lib_source_url, lora=self.lib_entry_lora)

    # ---- List / search ----
    def refresh_library_list(self):
        for item in self.tree_library.get_children():
            self.tree_library.delete(item)

        cat = self.lib_current_category
        query = self.lib_search_var.get().strip().lower()
        path = os.path.join(self.DATA_DIR, cat)
        files = sorted(glob.glob(os.path.join(path, "*.txt")))

        count = 0
        for f in files:
            base = os.path.splitext(os.path.basename(f))[0]
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read().strip()
            except Exception:
                content = ""
            preview = content.replace("\n", " ")
            if query and query not in base.lower() and query not in content.lower():
                continue
            display_name = base
            if cat == "outfits" and "_Canon_" in base:
                char_name, num = base.split("_Canon_")
                display_name = f"{char_name} — Canon {num}"
            preview_short = (preview[:60] + "…") if len(preview) > 60 else preview
            self.tree_library.insert("", "end", iid=base, values=(display_name, preview_short))
            count += 1

        self.lbl_lib_count.configure(text=f"{count} {'entry' if count == 1 else 'entries'}")

    def on_library_select(self, event=None):
        sel = self.tree_library.selection()
        if not sel:
            return
        base = sel[0]
        cat = self.lib_current_category
        content = self.read_file_content(cat, base)

        self.lib_selected_file = base
        self.txt_lib_tags.delete("1.0", tk.END)
        self.txt_lib_tags.insert("1.0", content)

        if cat == "outfits" and "_Canon_" in base:
            char_name, num = base.split("_Canon_")
            self.is_canon_var.set(True)
            self.combo_canon_char.configure(state="readonly")
            self.combo_canon_char["values"] = self.get_file_list("characters")
            self.combo_canon_char.set(char_name)
            self.ent_lib_name.configure(state="normal")
            self.ent_lib_name.delete(0, tk.END)
            self.ent_lib_name.configure(state="disabled")
            self.lib_editing_canon_owner = (char_name, num)
        else:
            self.is_canon_var.set(False)
            if cat == "outfits":
                self.combo_canon_char.configure(state="disabled")
            self.ent_lib_name.configure(state="normal")
            self.ent_lib_name.delete(0, tk.END)
            self.ent_lib_name.insert(0, base)
            self.lib_editing_canon_owner = None

        image_path = self.find_library_image(cat, base)
        if image_path:
            self.image_drop_zone.show_image_path(image_path)
        else:
            self.image_drop_zone.show_placeholder()

        meta = self.load_library_meta(cat, base)
        self.lib_source_url = meta["source_url"]
        self.lib_source_editing = False
        self._render_lib_source_row()
        self.lib_entry_lora = meta["lora"]
        self._render_lib_lora_row()

        self.lbl_lib_status.configure(text=f"Editing existing entry: {base}")

    def start_new_library_entry(self, keep_category=False):
        self.lib_selected_file = None
        self.lib_editing_canon_owner = None
        self.tree_library.selection_remove(self.tree_library.selection())
        self.ent_lib_name.configure(state="normal")
        self.ent_lib_name.delete(0, tk.END)
        self.txt_lib_tags.delete("1.0", tk.END)
        self.image_drop_zone.show_placeholder()
        if not keep_category:
            self.is_canon_var.set(False)
        self.lib_source_url = None
        self.lib_source_editing = False
        if hasattr(self, "frame_lib_source"):
            self._render_lib_source_row()
        self.lib_entry_lora = None
        if hasattr(self, "frame_lib_lora"):
            self._render_lib_lora_row()
        self.lbl_lib_status.configure(text="New entry")

    def duplicate_library_entry(self):
        if not self.lib_selected_file:
            messagebox.showinfo("Duplicate", "First select an entry from the list.")
            return
        cat = self.lib_current_category
        content = self.txt_lib_tags.get("1.0", tk.END).strip()
        if cat == "outfits" and self.lib_editing_canon_owner:
            char_name, _ = self.lib_editing_canon_owner
            existing = glob.glob(os.path.join(self.DATA_DIR, "outfits", f"{char_name}_Canon_*.txt"))
            new_idx = len(existing) + 1
            new_name = f"{char_name}_Canon_{new_idx}"
        else:
            base = self.lib_selected_file
            new_name = self._unique_copy_name(cat, base)

        filepath = os.path.join(self.DATA_DIR, cat, f"{new_name}.txt")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to duplicate: {e}")
            return

        # Carry the image over to the copy, if the original entry had one.
        old_base = self.lib_editing_canon_owner[0] + "_Canon_" + self.lib_editing_canon_owner[1] \
            if (cat == "outfits" and self.lib_editing_canon_owner) else self.lib_selected_file
        src_image = self.find_library_image(cat, old_base)
        if src_image:
            try:
                shutil.copyfile(src_image, self.library_image_path(cat, new_name))
            except Exception:
                pass

        # Carry the source_url/lora metadata over to the copy too (Task 6/7.1).
        old_meta = self.load_library_meta(cat, old_base)
        if old_meta["source_url"] or old_meta["lora"]:
            self.save_library_meta(cat, new_name, source_url=old_meta["source_url"], lora=old_meta["lora"])

        self.refresh_library_list()
        self.reload_all_lists()
        self.tree_library.selection_set(new_name)
        self.tree_library.see(new_name)
        self.on_library_select()
        self.lbl_lib_status.configure(text=f"Copy created: {new_name}")

    def _unique_copy_name(self, cat, base):
        candidate = f"{base}_copy"
        n = 1
        existing = set(self.get_file_list(cat))
        while candidate in existing:
            n += 1
            candidate = f"{base}_copy{n}"
        return candidate

    def delete_library_entry(self):
        if not self.lib_selected_file:
            messagebox.showinfo("Delete", "First select an entry from the list.")
            return
        cat = self.lib_current_category
        base = self.lib_selected_file

        if cat == "characters":
            linked = glob.glob(os.path.join(self.DATA_DIR, "outfits", f"{base}_Canon_*.txt"))
            if linked:
                if not messagebox.askyesno(
                        "Delete character",
                        f"The character \"{base}\" has {len(linked)} canon outfit(s).\n"
                        f"Delete the character and all of their canon outfits?"):
                    return
                for f in linked:
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                    linked_base = os.path.splitext(os.path.basename(f))[0]
                    self.delete_library_image("outfits", linked_base)
                    self.delete_library_meta("outfits", linked_base)
        else:
            if not messagebox.askyesno("Delete", f"Delete the entry \"{base}\"? This action cannot be undone."):
                return

        filepath = os.path.join(self.DATA_DIR, cat, f"{base}.txt")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete file: {e}")
            return

        self.delete_library_image(cat, base)
        self.delete_library_meta(cat, base)

        self.start_new_library_entry(keep_category=True)
        self.refresh_library_list()
        self.reload_all_lists()
        self.lbl_lib_status.configure(text=f"Deleted: {base}")

    # ---- Saving ----
    def save_to_library(self):
        cat = self.combo_lib_cat.get()
        tags = self.txt_lib_tags.get("1.0", tk.END).strip()

        if not tags:
            messagebox.showwarning("Error", "The tags/content field cannot be empty!")
            return

        is_editing_canon = cat == "outfits" and self.lib_editing_canon_owner is not None
        rename_from = None  # set below when an existing non-canon entry's name changes

        if cat == "outfits" and self.is_canon_var.get():
            if is_editing_canon:
                char_name, num = self.lib_editing_canon_owner
                filename = f"{char_name}_Canon_{num}.txt"
            else:
                char_name = self.combo_canon_char.get()
                if not char_name or char_name == "None":
                    messagebox.showwarning("Error", "Select a character for the canon outfit!")
                    return
                outfit_path = os.path.join(self.DATA_DIR, "outfits")
                existing_canons = glob.glob(os.path.join(outfit_path, f"{char_name}_Canon_*.txt"))
                next_idx = len(existing_canons) + 1
                filename = f"{char_name}_Canon_{next_idx}.txt"
        else:
            name = self.ent_lib_name.get().strip()
            if not name or name == "None":
                messagebox.showwarning("Error", "The \"Name\" field cannot be empty or 'None'!")
                return
            safe_name = sanitize_filename(name)
            if safe_name != name:
                if not messagebox.askyesno(
                        "Invalid characters",
                        f"The name contains characters that are not allowed in file names.\n"
                        f"\"{safe_name}\" will be used instead. Continue?"):
                    return
            name = safe_name
            old_name = self.lib_selected_file
            filename = f"{name}.txt"

            # renaming: if editing an existing entry under a different name
            if old_name and old_name != name:
                old_path = os.path.join(self.DATA_DIR, cat, f"{old_name}.txt")
                new_path = os.path.join(self.DATA_DIR, cat, filename)
                if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
                    messagebox.showwarning("Error", f"An entry named \"{name}\" already exists.")
                    return
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
                rename_from = old_name

        filepath = os.path.join(self.DATA_DIR, cat, filename)

        # protection against overwriting a new entry with the same name
        if not is_editing_canon and self.lib_selected_file is None and os.path.exists(filepath):
            if not messagebox.askyesno("Entry exists",
                                        f"An entry named \"{os.path.splitext(filename)[0]}\" already exists. Overwrite?"):
                return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(tags)
            # Image follows the entry on rename — done only after the text
            # file write succeeds, so a failed save can't leave the image
            # renamed while the text stays under the old name.
            if rename_from:
                self.rename_library_image(cat, rename_from, os.path.splitext(filename)[0])
                self.rename_library_meta(cat, rename_from, os.path.splitext(filename)[0])
            self.lbl_lib_status.configure(text=f"✓ Saved as {filename}")
            self.refresh_library_list()
            self.reload_all_lists()
            saved_base = os.path.splitext(filename)[0]
            self.lib_selected_file = saved_base
            if self.tree_library.exists(saved_base):
                self.tree_library.selection_set(saved_base)
                self.tree_library.see(saved_base)
            saved_image = self.find_library_image(cat, saved_base)
            if saved_image:
                self.image_drop_zone.show_image_path(saved_image)
            else:
                self.image_drop_zone.show_placeholder()
            # Task 6/7.1: persist whatever source_url/lora are currently set
            # in the editor under the entry's final (possibly new/renamed)
            # filename. Covers brand-new entries where Source/LoRA were
            # filled in before the first Save, since _persist_current_lib_meta()
            # alone is a no-op until lib_selected_file exists.
            self.save_library_meta(cat, saved_base, source_url=self.lib_source_url, lora=self.lib_entry_lora)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}")

    # ==========================================================
    #                  LIST REFRESH LOGIC
    # ==========================================================
    def get_file_list(self, category):
        path = os.path.join(self.DATA_DIR, category)
        files = os.listdir(path)
        result = []
        for f in files:
            if f.endswith(".txt"):
                base = os.path.splitext(f)[0]
                if category == "outfits" and "_Canon_" in base:
                    continue  # canon outfits are not shown as standalone shared outfits
                result.append(base)
        return sorted(result)

    def reload_all_lists(self):
        """Refreshes the builder's dropdown lists"""
        cur_style = self.selected_style.get()
        self.combo_style["values"] = ["None"] + self.get_file_list("styles")
        if cur_style in self.combo_style["values"]:
            self.selected_style.set(cur_style)
        else:
            self.combo_style.current(0)

        cur_scen = self.selected_scenario.get()
        self.combo_scenario["values"] = ["None"] + self.get_file_list("scenarios")
        if cur_scen in self.combo_scenario["values"]:
            self.selected_scenario.set(cur_scen)
        else:
            self.combo_scenario.current(0)

        for slot in self.active_characters:
            cur_char = slot["char_var"].get()
            char_values = ["None"] + self.get_file_list("characters")
            slot["char_combo"]["values"] = char_values
            if cur_char not in char_values:
                slot["char_var"].set("None")
            cur_outfit = slot["outfit_var"].get()
            self.update_outfit_list(slot["char_var"], slot["outfit_combo"])
            # update_outfit_list always resets the selection to "None" — restore
            # the previous outfit choice if it's still valid in the new list.
            if cur_outfit and cur_outfit in slot["outfit_combo"]["values"]:
                slot["outfit_var"].set(cur_outfit)

        if hasattr(self, "combo_canon_char"):
            self.combo_canon_char["values"] = self.get_file_list("characters")

        # Refresh the fields of the currently open custom template (if any)
        for slot in self.custom_active_slots:
            cur_char = slot["char_var"].get()
            char_values = ["None"] + self.get_file_list("characters")
            slot["char_combo"]["values"] = char_values
            if cur_char not in char_values:
                slot["char_var"].set("None")
            if slot.get("outfit_combo") is not None:
                cur_outfit = slot["outfit_var"].get()
                self.update_outfit_list(slot["char_var"], slot["outfit_combo"])
                if cur_outfit and cur_outfit in slot["outfit_combo"]["values"]:
                    slot["outfit_var"].set(cur_outfit)

        if self.custom_style_combo is not None:
            cur = self.custom_style_var.get()
            self.custom_style_combo["values"] = ["None"] + self.get_file_list("styles")
            self.custom_style_var.set(cur if cur in self.custom_style_combo["values"] else "None")

        if self.custom_scenario_combo is not None:
            cur = self.custom_scenario_var.get()
            self.custom_scenario_combo["values"] = ["None"] + self.get_file_list("scenarios")
            self.custom_scenario_var.set(cur if cur in self.custom_scenario_combo["values"] else "None")

    # ==========================================================
    #                       TAB 3: HISTORY
    # ==========================================================
    def build_history_tab(self):
        c = self.colors
        top = ttk.Frame(self.tab_history)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="History of generated prompts", style="Title.TLabel").pack(side="left")

        self.history_filter_var = tk.StringVar(value="all")
        filter_row = ttk.Frame(top)
        filter_row.pack(side="right")
        ttk.Radiobutton(filter_row, text="All", value="all", variable=self.history_filter_var,
                        command=self.refresh_history_list).pack(side="left", padx=4)
        ttk.Radiobutton(filter_row, text="⭐ Favorites", value="fav", variable=self.history_filter_var,
                        command=self.refresh_history_list).pack(side="left", padx=4)

        body = ttk.Frame(self.tab_history)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.lst_history = tk.Listbox(left, bg=c["bg_card"], fg=c["fg"], selectbackground=c["accent"],
                                       selectforeground=c["accent_text"], font=self.default_font,
                                       relief="flat", highlightthickness=0, activestyle="none")
        self.lst_history.pack(side="left", fill="both", expand=True)
        self.lst_history.bind("<<ListboxSelect>>", self.on_history_select)

        hist_scroll = ttk.Scrollbar(left, orient="vertical", command=self.lst_history.yview)
        hist_scroll.pack(side="right", fill="y")
        self.lst_history.configure(yscrollcommand=hist_scroll.set)

        right = ttk.LabelFrame(body, text=" Preview ", padding=12)
        right.pack(side="left", fill="both", expand=True)

        self.txt_history_preview = scrolledtext.ScrolledText(right, wrap=tk.WORD, font=self.mono_font,
                                                                bg=c["bg_input"], fg=c["fg"],
                                                                relief="flat", borderwidth=0)
        self.txt_history_preview.pack(fill="both", expand=True)
        self.txt_history_preview.configure(state="disabled")

        btn_row = ttk.Frame(right)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="📋 Copy", command=self.copy_selected_history).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="↺ Load into builder", command=self.restore_history_to_forge).pack(
            side="left", fill="x", expand=True, padx=4)
        self.btn_hist_fav = ttk.Button(btn_row, text="⭐ Favorite", command=self.toggle_selected_favorite)
        self.btn_hist_fav.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(btn_row, text="🗑", width=3, style="Danger.TButton",
                   command=self.delete_selected_history).pack(side="left", padx=(4, 0))

        self._history_index_map = []  # order of displayed items -> index in self.history

    def refresh_history_list(self):
        self.lst_history.delete(0, tk.END)
        self._history_index_map = []
        flt = self.history_filter_var.get() if hasattr(self, "history_filter_var") else "all"

        for idx, entry in enumerate(self.history):
            if flt == "fav" and not entry.get("favorite"):
                continue
            star = "⭐ " if entry.get("favorite") else ""
            ts = entry.get("timestamp", "")
            preview = entry.get("text", "").replace("\n", " ")[:50]
            self.lst_history.insert(tk.END, f"{star}{ts} — {preview}")
            self._history_index_map.append(idx)

    def on_history_select(self, event=None):
        sel = self.lst_history.curselection()
        if not sel:
            return
        real_idx = self._history_index_map[sel[0]]
        entry = self.history[real_idx]
        self.txt_history_preview.configure(state="normal")
        self.txt_history_preview.delete("1.0", tk.END)
        self.txt_history_preview.insert("1.0", entry.get("text", ""))
        self.txt_history_preview.configure(state="disabled")
        self.btn_hist_fav.configure(text="⭐ Remove from favorites" if entry.get("favorite") else "⭐ Favorite")

    def _get_selected_history_entry(self):
        sel = self.lst_history.curselection()
        if not sel:
            return None
        real_idx = self._history_index_map[sel[0]]
        return real_idx, self.history[real_idx]

    def copy_selected_history(self):
        res = self._get_selected_history_entry()
        if not res:
            messagebox.showinfo("Copy", "First select a history entry.")
            return
        _, entry = res
        self.root.clipboard_clear()
        self.root.clipboard_append(entry.get("text", ""))
        messagebox.showinfo("Copied", "Prompt copied to clipboard.")

    def restore_history_to_forge(self):
        res = self._get_selected_history_entry()
        if not res:
            messagebox.showinfo("Load", "First select a history entry.")
            return
        _, entry = res
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", entry.get("text", ""))
        self.notebook.select(self.tab_forge)

    def toggle_selected_favorite(self):
        res = self._get_selected_history_entry()
        if not res:
            messagebox.showinfo("Favorite", "First select a history entry.")
            return
        real_idx, entry = res
        entry["favorite"] = not entry.get("favorite", False)
        self.save_json(self.HISTORY_FILE, self.history)
        self.refresh_history_list()

    def delete_selected_history(self):
        res = self._get_selected_history_entry()
        if not res:
            messagebox.showinfo("Delete", "First select a history entry.")
            return
        real_idx, entry = res
        if not messagebox.askyesno("Delete entry", "Delete this entry from history?"):
            return
        del self.history[real_idx]
        self.save_json(self.HISTORY_FILE, self.history)
        self.refresh_history_list()
        self.txt_history_preview.configure(state="normal")
        self.txt_history_preview.delete("1.0", tk.END)
        self.txt_history_preview.configure(state="disabled")

    def add_to_history(self, text, favorite=False):
        entry = {
            "id": str(uuid.uuid4()),
            "text": text,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
            "favorite": favorite,
        }
        self.history.insert(0, entry)
        # cap history at a reasonable size
        self.history = self.history[:200]
        self.save_json(self.HISTORY_FILE, self.history)
        self.refresh_history_list()

    def favorite_last(self):
        if not self._last_generated:
            messagebox.showinfo("Favorite", "First generate a prompt.")
            return
        if self.history and self.history[0]["text"] == self._last_generated:
            self.history[0]["favorite"] = True
            self.save_json(self.HISTORY_FILE, self.history)
            self.refresh_history_list()
            self.lbl_copy_status.configure(text="⭐ Added to favorites")
        else:
            self.add_to_history(self._last_generated, favorite=True)
            self.lbl_copy_status.configure(text="⭐ Added to favorites")

    def copy_output_only(self):
        text = self.txt_output.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Copy", "There is no text to copy.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.lbl_copy_status.configure(text="📋 Copied to clipboard")

    # ==========================================================
    #              TAB 4: GALLERY OF GENERATED IMAGES
    # ==========================================================
    # Every successful ComfyUI generation lands here as a thumbnail for
    # the rest of the session (see _gallery_register_result(), called
    # from _on_comfy_generation_done()). The grid re-flows its column
    # count on resize (_gallery_relayout) and each cell offers a
    # hover-only "reveal in explorer" magnifier plus click-to-open-full-
    # size, both using the same output_dir-vs-local-copy path priority as
    # the Builder tab's "Open folder" button (_resolve_output_folder_for).
    def build_gallery_tab(self):
        c = self.colors
        top = ttk.Frame(self.tab_gallery)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Generated images (this session)", style="Title.TLabel").pack(side="left")
        self.lbl_gallery_count = ttk.Label(top, text="", style="Dim.TLabel")
        self.lbl_gallery_count.pack(side="left", padx=(12, 0))

        body = ttk.Frame(self.tab_gallery)
        body.pack(fill="both", expand=True)

        self.gallery_canvas = tk.Canvas(body, bg=c["bg"], highlightthickness=0)
        gallery_scroll = ttk.Scrollbar(body, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_scroll_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_scroll_frame.bind(
            "<Configure>",
            lambda e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.create_window((0, 0), window=self.gallery_scroll_frame, anchor="nw")
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        gallery_scroll.pack(side="right", fill="y")
        # Re-flow columns whenever the tab/canvas changes width (window
        # resize, sash drag, first time the tab is actually mapped — see
        # _on_notebook_tab_changed for that last case).
        self.gallery_canvas.bind("<Configure>", self._gallery_relayout, add="+")

        self.gallery_cells = []  # ttk.Frame widgets, kept 1:1 with self.gallery_entries

        placeholder_text = (
            "No images generated yet this session — results from "
            "\"🎨 Generate in ComfyUI\" will show up here."
            if PIL_AVAILABLE else
            "Pillow (PIL) isn't installed, so thumbnails can't be rendered here."
        )
        self.gallery_placeholder = ttk.Label(
            self.gallery_scroll_frame, text=placeholder_text, style="Dim.TLabel",
            wraplength=420, justify="left")
        self.gallery_placeholder.grid(row=0, column=0, padx=10, pady=20, sticky="w")

        self._gallery_update_count_label()

    def _gallery_update_count_label(self):
        n = len(self.gallery_entries)
        self.lbl_gallery_count.configure(text=f"{n} image{'s' if n != 1 else ''}" if n else "")

    def _gallery_make_thumbnail(self, path):
        """Loads `path` and returns a Tk PhotoImage fit within
        GALLERY_THUMB_SIZE x GALLERY_THUMB_SIZE. Pillow's thumbnail()
        preserves aspect ratio (no cropping/distortion), so portrait and
        landscape results both end up centered in the same square cell.
        Returns None if Pillow is unavailable or the file can't be read —
        callers fall back to a plain placeholder icon in that case."""
        if not PIL_AVAILABLE or not path or not os.path.exists(path):
            return None
        try:
            img = Image.open(path)
            img.load()
            img = img.convert("RGB")
            img.thumbnail((GALLERY_THUMB_SIZE, GALLERY_THUMB_SIZE), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _gallery_build_cell(self, parent, entry):
        """Builds one grid cell: a fixed-size thumbnail (so cells line up
        regardless of each image's native aspect ratio), the filename
        underneath, and a hover-only magnifier button that reveals the
        file in the OS explorer. Clicking the thumbnail itself (not the
        magnifier) opens the image full-size in the system viewer."""
        c = self.colors
        cell = ttk.Frame(parent, style="Card.TFrame")

        thumb_holder = tk.Frame(cell, width=GALLERY_THUMB_SIZE, height=GALLERY_THUMB_SIZE,
                                 bg=c["bg_card"])
        thumb_holder.pack_propagate(False)
        thumb_holder.pack(padx=8, pady=(8, 4))

        photo = self._gallery_make_thumbnail(entry["local_path"])
        if photo is not None:
            lbl_thumb = tk.Label(thumb_holder, image=photo, bg=c["bg_card"], cursor="hand2")
            lbl_thumb.image = photo  # keep a reference alive — Tk drops GC'd PhotoImages
        else:
            lbl_thumb = tk.Label(thumb_holder, text="🖼", font=("Segoe UI", 40),
                                  bg=c["bg_card"], fg=c["fg_dim"], cursor="hand2")
        lbl_thumb.pack(expand=True)
        lbl_thumb.bind("<Button-1>", lambda e, en=entry: self._gallery_open_full_view(en))

        name_text = entry.get("display_name") or os.path.basename(entry["local_path"])
        lbl_name = ttk.Label(cell, text=name_text, style="CardDim.TLabel",
                             wraplength=GALLERY_THUMB_SIZE, justify="center")
        lbl_name.pack(padx=8, pady=(0, 8))

        target_file, _ = self._gallery_resolve_target(entry)
        btn_magnifier = ttk.Button(thumb_holder, text="🔍", width=2, style="Icon.TButton",
                                    command=lambda en=entry: self._gallery_reveal_in_explorer(en))
        Tooltip(btn_magnifier, target_file, self)

        def show_magnifier(_e=None):
            btn_magnifier.place(relx=1.0, rely=0.0, anchor="ne", x=-6, y=6)
            btn_magnifier.lift()

        def hide_magnifier(_e=None):
            btn_magnifier.place_forget()

        # Bound on every widget that visually makes up the cell (not just
        # the outer frame) — Tk fires <Leave> on a widget the instant the
        # pointer crosses onto a child that overlaps it, so binding only
        # the parent causes the button to flicker away while still
        # hovering the cell. Binding the same show/hide pair everywhere
        # the pointer might legitimately be keeps it stable.
        for w in (cell, thumb_holder, lbl_thumb, lbl_name, btn_magnifier):
            w.bind("<Enter>", show_magnifier)
            w.bind("<Leave>", hide_magnifier)

        cell.gallery_tk_widgets = [thumb_holder, lbl_thumb]
        return cell

    def _gallery_add_cell(self, entry):
        if not PIL_AVAILABLE:
            self._gallery_update_count_label()
            return
        if self.gallery_placeholder.winfo_ismapped():
            self.gallery_placeholder.grid_forget()
        cell = self._gallery_build_cell(self.gallery_scroll_frame, entry)
        self.gallery_cells.append(cell)
        self._gallery_relayout()
        self._gallery_update_count_label()

    def _gallery_relayout(self, event=None):
        """Recomputes how many columns fit in the canvas's current width
        and re-grids every existing cell — cells themselves are never
        rebuilt, just moved, so this is cheap enough to call on every
        resize."""
        if not getattr(self, "gallery_cells", None):
            return
        canvas_w = self.gallery_canvas.winfo_width()
        cols = max(1, canvas_w // GALLERY_CELL_OUTER_WIDTH)
        for i, cell in enumerate(self.gallery_cells):
            r, col = divmod(i, cols)
            cell.grid(row=r, column=col, padx=10, pady=10, sticky="n")

    def _gallery_register_result(self, local_path, remote_filename, remote_subfolder, display_name):
        """Adds one freshly generated image to the in-session Gallery.
        Called from _on_comfy_generation_done() for every successful
        generation — both the normal /view-download path (which has
        already saved a numbered result_NNN.* copy by this point, see
        _on_comfy_image_bytes) and the local mtime-scan fallback (where
        local_path is already a real file inside comfy_output_dir, so
        nothing extra needs to be copied)."""
        entry = {
            "local_path": local_path,
            "remote_filename": remote_filename,
            "remote_subfolder": remote_subfolder or "",
            "display_name": display_name,
        }
        self.gallery_entries.append(entry)
        if hasattr(self, "gallery_scroll_frame"):
            self._gallery_add_cell(entry)

    def _gallery_resolve_target(self, entry):
        """Returns (target_file, folder) for a Gallery entry, preferring
        ComfyUI's real output/ folder over the local preview-cache copy —
        the same priority comfy_open_output_folder() uses for the
        Builder's single "last result", generalized here to an arbitrary
        entry via _resolve_output_folder_for()."""
        folder = self._resolve_output_folder_for(entry.get("remote_filename"), entry.get("remote_subfolder"))
        remote_filename = entry.get("remote_filename")
        if folder and remote_filename:
            target_file = os.path.join(folder, remote_filename)
        else:
            target_file = os.path.abspath(entry["local_path"])
            folder = os.path.dirname(target_file)
        return target_file, folder

    def _gallery_reveal_in_explorer(self, entry):
        """Magnifier action: opens the folder with this entry's file
        selected/highlighted, via the same cross-platform logic (and
        Windows foreground fix) as comfy_open_output_folder()."""
        target_file, folder = self._gallery_resolve_target(entry)
        self._reveal_file_in_explorer(target_file, folder)

    def _gallery_open_full_view(self, entry):
        """Click-on-thumbnail action: opens the image in the system's
        default viewer. Prefers the real ComfyUI output file (same
        priority as the magnifier/"Open folder"), falling back to the
        local preview-cache copy if that file isn't reachable (e.g. a
        remote ComfyUI instance with no shared filesystem)."""
        target_file, _ = self._gallery_resolve_target(entry)
        if not os.path.isfile(target_file):
            target_file = entry["local_path"]
        if not os.path.isfile(target_file):
            messagebox.showwarning("Open image", "This image file is no longer available.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(target_file)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target_file])
            else:
                subprocess.Popen(["xdg-open", target_file])
        except Exception as e:
            messagebox.showwarning("Open image", f"Could not open image:\n{e}")

    # ==========================================================
    #                 PROMPT ASSEMBLY LOGIC (CORE)
    # ==========================================================
    def read_file_content(self, category, filename):
        if not filename or filename == "None":
            return ""
        filepath = os.path.join(self.DATA_DIR, category, f"{filename}.txt")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def _build_style_block(self, valid_chars_count):
        """Builds the Style block for the Default Template.

        Rule (Default Template only): when exactly 1 character is selected,
        the "a scene of N characters" count prefix is dropped — only the
        literal "a scene of 1 characters" phrase is removed, any joining
        punctuation that was already glued to the style tags stays as-is.
        For 0 or 2+ characters the original behavior is unchanged.
        """
        style_name = self.selected_style.get()
        style_tags = self.read_file_content("styles", style_name)
        if style_tags:
            block = f"{style_tags}, a scene of {valid_chars_count} characters" if valid_chars_count > 0 else style_tags
        else:
            block = f"a scene of {valid_chars_count} characters" if valid_chars_count > 0 else ""

        if valid_chars_count == 1:
            block = block.replace(f"a scene of {valid_chars_count} characters", "").rstrip()

        return block

    def _build_characters_block(self, valid_chars):
        char_lines = []
        valid_chars_count = len(valid_chars)
        for idx, slot in enumerate(valid_chars):
            c_name = slot["char_var"].get()
            c_tags = self.read_file_content("characters", c_name)

            o_selection = slot["outfit_var"].get()
            o_tags = ""
            if o_selection and o_selection != "None":
                if o_selection.startswith("Canon "):
                    c_num = o_selection.split(" ")[1]
                    o_tags = self.read_file_content("outfits", f"{c_name}_Canon_{c_num}")
                else:
                    o_tags = self.read_file_content("outfits", o_selection)

            full_char_prompt = f"{c_tags}, {o_tags}" if o_tags else c_tags

            # Default Template rule: force a trailing period at the end of
            # each character's paragraph (character tags + outfit tags),
            # without duplicating one that's already there.
            full_char_prompt = full_char_prompt.rstrip()
            if full_char_prompt and not full_char_prompt.endswith("."):
                full_char_prompt += "."

            if valid_chars_count > 1:
                prefix = PREFIXES[idx] if idx < len(PREFIXES) else f"Character {idx + 1}:"
                char_lines.append(f"{prefix} {full_char_prompt}")
            else:
                char_lines.append(full_char_prompt)
        return "\n".join(char_lines)

    def _build_scenario_block(self):
        scen_name = self.selected_scenario.get()
        return self.read_file_content("scenarios", scen_name)

    def generate_prompt(self):
        """Entry point: routes to standard or custom prompt assembly."""
        # Move focus away from whatever widget currently has it so that, if
        # the user was mid-typing in an AutocompleteCombobox (Who:/Outfit:),
        # its <FocusOut> commit logic runs before we read its value.
        self.root.focus_set()

        # Task 7.2: autofill the LoRA Manager from whichever library
        # entries are active *before* assembling the prompt text — only
        # when ComfyUI is connected (LoRA Manager doesn't even exist
        # otherwise, and there's no point writing lora_slots data that a
        # disconnected/text-only user will never see or need). This
        # intentionally only runs on "Generate prompt and copy", not on
        # "Generate in ComfyUI" — that gives the user a window between the
        # two presses to fine-tune strengths or add extra manual LoRAs
        # before actually submitting to ComfyUI, instead of having any
        # such tweak silently overwritten right before submission.
        if self.comfy_connected:
            self._lora_autofill_from_library()

        if self.combo_template_category.get() == "Custom":
            self.generate_custom_prompt()
        else:
            self.generate_standard_prompt()

    def generate_standard_prompt(self):
        valid_chars = [slot for slot in self.active_characters
                       if slot["char_var"].get() and slot["char_var"].get() != "None"]
        valid_chars_count = len(valid_chars)

        blocks = {}
        blocks["style"] = self._build_style_block(valid_chars_count)
        blocks["characters"] = self._build_characters_block(valid_chars)
        blocks["scenario"] = self._build_scenario_block()

        paragraphs = [blocks[key] for key in self.block_order if blocks.get(key, "").strip()]
        final_prompt = "\n\n".join(paragraphs)

        if not final_prompt.strip():
            messagebox.showinfo("Empty prompt", "Select at least one style, character, or scenario.")
            return

        self._finalize_generated_prompt(final_prompt)

    def _finalize_generated_prompt(self, final_prompt):
        """Common tail for both the Standard and Custom builders, once a
        final_prompt string has been assembled. Updates the Result panel
        and history, then always copies to the clipboard.

        Task 2: this no longer hands off to ComfyUI itself — submission to
        ComfyUI is now a separate, explicit action (the "🎨 Generate in
        ComfyUI" button / on_generate_in_comfy_clicked()), which reads the
        text back out of txt_output rather than being called from here.
        This keeps Custom Template generation going through the exact same
        path as standard generation (preserving the Task 0b fix) while still
        making ComfyUI submission independent of which builder produced the
        text."""
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", final_prompt)
        self._last_generated = final_prompt
        self.add_to_history(final_prompt)

        self.root.clipboard_clear()
        self.root.clipboard_append(final_prompt)
        self.lbl_copy_status.configure(text="✓ Prompt generated and copied to clipboard")

    # ==========================================================
    #          LORA AUTOFILL FROM LIBRARY (TASK 7.2)
    # ==========================================================

    def _collect_active_library_loras(self):
        """Returns a de-duplicated, order-preserving list of LoRA names
        bound (Task 7.1, load_library_meta) to whichever library entries
        are currently active in the Builder — covering both the Standard
        template path (style/characters/outfits/scenario) and the Custom
        template path (custom_active_slots + custom style/scenario), in
        the order those entries are referenced.

        Mirrors the same "Canon N" -> f"{char_name}_Canon_{n}" outfit name
        resolution used by _build_characters_block()/generate_custom_prompt()
        so the lookup always hits the entry actually shown to the user.
        """
        ordered_names = []  # (category, name) in mention order

        def add(category, name):
            if name and name != "None":
                ordered_names.append((category, name))

        if self.combo_template_category.get() == "Custom":
            for slot in self.custom_active_slots:
                char_name = slot["char_var"].get()
                add("characters", char_name)
                o_selection = slot["outfit_var"].get()
                if o_selection and o_selection != "None":
                    if o_selection.startswith("Canon ") and char_name and char_name != "None":
                        c_num = o_selection.split(" ")[1]
                        add("outfits", f"{char_name}_Canon_{c_num}")
                    else:
                        add("outfits", o_selection)
            if self.custom_style_combo is not None:
                add("styles", self.custom_style_var.get())
            if self.custom_scenario_combo is not None:
                add("scenarios", self.custom_scenario_var.get())
        else:
            add("styles", self.selected_style.get())
            for slot in self.active_characters:
                char_name = slot["char_var"].get()
                add("characters", char_name)
                o_selection = slot["outfit_var"].get()
                if o_selection and o_selection != "None":
                    if o_selection.startswith("Canon ") and char_name and char_name != "None":
                        c_num = o_selection.split(" ")[1]
                        add("outfits", f"{char_name}_Canon_{c_num}")
                    else:
                        add("outfits", o_selection)
            add("scenarios", self.selected_scenario.get())

        result = []
        seen = set()
        for category, name in ordered_names:
            lora = self.load_library_meta(category, name).get("lora")
            if lora and lora not in seen:
                seen.add(lora)
                result.append(lora)
        return result

    def _lora_autofill_from_library(self):
        """Task 7.2: recomputes the auto-owned LoRA slots from whichever
        library entries are currently active, while leaving manually
        edited slots untouched (smart merge, per the agreed design):

        1. Collect the de-duplicated LoRA list implied by active entries.
        2. Keep all current manual slots (auto flag False/absent) as-is.
        3. Drop the old auto slots and rebuild them from the fresh list,
           skipping any name that's already covered by a manual slot (a
           manual slot always wins over an autofill for the same LoRA).
        4. If nothing is left at all, fall back to a single empty slot.
        5. Rebuild the widgets and persist.

        Safe to call often (every generation) — it's a no-op in terms of
        user-visible disruption when there are no active library->LoRA
        bindings or when autofill's result doesn't change.
        """
        auto_loras = self._collect_active_library_loras()

        manual_entries = [e for e in self._lora_slots_data
                           if not e.get("auto") and e.get("name", LORA_NONE_VALUE) != LORA_NONE_VALUE]
        manual_names = {e["name"] for e in manual_entries}

        new_auto_entries = [
            {"name": lora, "strength": 1.0, "auto": True}
            for lora in auto_loras
            if lora not in manual_names
        ]

        combined = manual_entries + new_auto_entries
        if not combined:
            combined = [{"name": LORA_NONE_VALUE, "strength": 1.0, "auto": False}]

        self._lora_slots_data = combined
        self._build_lora_slots()
        self._lora_persist()

    # ==========================================================
    #                  COMFYUI INTEGRATION (UI side)
    # ==========================================================
    # ==========================================================
    #                    LORA MANAGER (TASK 4)
    # ==========================================================

    def _build_lora_slots(self):
        """Creates LoRA slot widgets from self._lora_slots_data.
        Called once at startup; afterwards individual slots are
        added/removed via _lora_add_slot()/_lora_remove_slot()."""
        # Destroy any existing slot widgets
        for slot in self.lora_slots:
            slot["frame"].destroy()
        self.lora_slots.clear()

        source = self._lora_slots_data if self._lora_slots_data else []
        # Always show at least 1 empty slot
        if not source:
            source = [{"name": LORA_NONE_VALUE, "strength": 1.0, "auto": False}]

        for entry in source:
            self._lora_create_slot(
                name=entry.get("name", LORA_NONE_VALUE),
                strength=entry.get("strength", 1.0),
                auto=entry.get("auto", False),
            )
        self._lora_update_add_button()

    def _lora_create_slot(self, name=LORA_NONE_VALUE, strength=1.0, auto=False):
        """Creates one LoRA slot row and appends it to self.lora_slots.

        Task 7.2: `auto` marks whether this slot was placed by the
        library-driven autofill (True) or is a manual user edit (False).
        Auto slots get recomputed/dropped on the next autofill pass; manual
        slots are never touched by it. A small [A]/[M] tag to the left of
        the combo gives an at-a-glance read of which is which."""
        idx = len(self.lora_slots)  # 0-based index at creation time

        row = ttk.Frame(self.lora_inner_frame)
        row.pack(fill="x", pady=2)

        # Auto/Manual tag — purely informational, click does nothing.
        tag_var = tk.StringVar()
        lbl_tag = ttk.Label(row, textvariable=tag_var, width=3, anchor="center",
                             style="LoraTagAuto.TLabel" if auto else "LoraTagManual.TLabel")
        lbl_tag.pack(side="left", padx=(0, 4))

        def _set_tag(is_auto):
            tag_var.set("[A]" if is_auto else "[M]")
            lbl_tag.configure(style="LoraTagAuto.TLabel" if is_auto else "LoraTagManual.TLabel")

        _set_tag(auto)

        # LoRA name combo
        combo_var = tk.StringVar(value=name)
        # Values are injected later by _lora_update_combos() once loras are fetched.
        # Show the saved name even before connecting so data isn't lost.
        choices = [LORA_NONE_VALUE] + self._available_loras
        if name not in choices:
            choices = [name] + choices  # keep saved name visible even if not yet fetched

        # Task 5A/5B fix: use the app's existing AutocompleteCombobox widget
        # (already used for Style/Who/Outfit — see build_forge_tab's style
        # row and build_custom_template_form's character/outfit rows)
        # instead of a hand-rolled ttk.Combobox + readonly/normal state
        # juggling. AutocompleteCombobox already solves both bugs properly:
        # a single click anywhere on the field opens the full list
        # (_on_click), and typing live-filters it via its own borderless
        # Toplevel+Listbox popup that never steals keyboard focus from the
        # Entry (_on_keyrelease/_open_popup) — which is exactly the
        # mechanism that makes search work reliably for Style/Who/Outfit.
        # A previous attempt at fixing 5A/5B by switching ttk.Combobox
        # between "readonly"/"normal" and reopening the native popdown via
        # StringVar trace + after() did not reproduce that behaviour and
        # left both bugs in place.
        combo = AutocompleteCombobox(row, textvariable=combo_var, values=choices, width=28)
        combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        combo.bind("<<ComboboxSelected>>",
                    lambda e: self._lora_on_slot_changed(downgrade_row=row), add="+")

        # Task 5C fix: mouse wheel over a LoRA combobox should scroll the
        # surrounding lora_canvas list, not change the selected value.
        # AutocompleteCombobox doesn't bind the wheel itself, so this is
        # still needed and independent of the 5A/5B widget swap above.
        def _block_scroll(event, canvas=self.lora_canvas):
            delta = getattr(event, "delta", 0) or (-120 if event.num == 5 else 120)
            # On Windows/macOS, delta is a multiple of 120 (or 1 on macOS
            # trackpads with inertial scrolling) per wheel "click" — scaling
            # the scroll amount by that magnitude (instead of always moving
            # exactly 1 unit) keeps fast scrolling responsive instead of
            # feeling sluggish/throttled.
            units = max(1, abs(delta) // 120)
            canvas.yview_scroll(-units if delta > 0 else units, "units")
            return "break"

        combo.bind("<MouseWheel>", _block_scroll)
        combo.bind("<Button-4>", _block_scroll)
        combo.bind("<Button-5>", _block_scroll)

        # Strength entry
        str_var = tk.StringVar(value=str(strength))
        str_entry = ttk.Entry(row, textvariable=str_var, width=7)
        str_entry.pack(side="left", padx=(0, 4))
        str_entry.bind("<FocusOut>", lambda e: self._lora_validate_strength(str_var, downgrade_row=row))
        str_entry.bind("<Return>",   lambda e: self._lora_validate_strength(str_var, downgrade_row=row))
        str_var.trace_add("write", lambda *_: self._lora_on_slot_changed_debounce(downgrade_row=row))

        # Delete button (always show, but the last remaining slot just clears itself)
        btn_del = ttk.Button(row, text="🗑", width=3,
                              command=lambda i=idx: self._lora_remove_slot_by_ref(row))
        btn_del.pack(side="left")

        slot = {
            "frame":    row,
            "combo":    combo,
            "combo_var": combo_var,
            "str_var":  str_var,
            "str_entry": str_entry,
            "btn_del":  btn_del,
            "auto":     auto,
            "set_tag":  _set_tag,
        }
        self.lora_slots.append(slot)
        self._lora_update_add_button()
        # Refresh theming for the new widgets
        self._lora_apply_theme()
        return slot

    def _lora_remove_slot_by_ref(self, row_frame):
        """Remove the slot whose frame is row_frame. If it's the last slot,
        clear it instead of deleting — we always keep at least one row."""
        idx = next((i for i, s in enumerate(self.lora_slots)
                    if s["frame"] is row_frame), None)
        if idx is None:
            return
        if len(self.lora_slots) <= 1:
            # Last slot: clear values instead of destroying
            self.lora_slots[0]["combo_var"].set(LORA_NONE_VALUE)
            self.lora_slots[0]["str_var"].set("1.0")
            if self.lora_slots[0].get("auto"):
                self.lora_slots[0]["auto"] = False
                self.lora_slots[0]["set_tag"](False)
            self._lora_on_slot_changed()
            return
        self.lora_slots[idx]["frame"].destroy()
        self.lora_slots.pop(idx)
        self._lora_update_add_button()
        self._lora_on_slot_changed()

    def _lora_add_slot(self):
        """Add one new empty LoRA slot (up to MAX_LORA_SLOTS)."""
        if len(self.lora_slots) >= MAX_LORA_SLOTS:
            return
        self._lora_create_slot()
        self._lora_on_slot_changed()

    def _lora_clear_all(self):
        """Remove all LoRA slots and leave exactly one empty slot. (Task 2.9)"""
        for slot in self.lora_slots:
            slot["frame"].destroy()
        self.lora_slots.clear()
        self._lora_create_slot()   # one empty row
        self._lora_update_add_button()
        self._lora_on_slot_changed()

    def _lora_update_add_button(self):
        """Show/hide the Add button based on slot count."""
        if not hasattr(self, "btn_lora_add"):
            return
        if len(self.lora_slots) >= MAX_LORA_SLOTS:
            self.btn_lora_add.configure(state="disabled")
        else:
            self.btn_lora_add.configure(state="normal")

    def _lora_validate_strength(self, var, downgrade_row=None):
        """Clamp the strength entry to [LORA_STRENGTH_MIN, LORA_STRENGTH_MAX]."""
        try:
            v = float(var.get())
            v = max(LORA_STRENGTH_MIN, min(LORA_STRENGTH_MAX, v))
            var.set(f"{v:.2f}")
        except ValueError:
            var.set("1.00")
        self._lora_on_slot_changed(downgrade_row=downgrade_row)

    def _lora_on_slot_changed(self, downgrade_row=None):
        """Sync in-memory slot data and persist to settings immediately.

        Task 7.2: if downgrade_row is given, the edit came from the user
        directly touching that slot's combo/strength widgets — if that
        slot was an autofill-owned ("auto") slot, it stops being one, so
        the next autofill pass won't silently overwrite a value the user
        just set by hand. The [A]/[M] tag is updated to match."""
        if downgrade_row is not None:
            for slot in self.lora_slots:
                if slot["frame"] is downgrade_row and slot.get("auto"):
                    slot["auto"] = False
                    slot["set_tag"](False)
                    break
        self._lora_sync_data()
        self._lora_persist()

    def _lora_on_slot_changed_debounce(self, downgrade_row=None):
        """Debounced version for rapid widget edits (strength typing)."""
        if self._lora_slots_save_after_id:
            self.root.after_cancel(self._lora_slots_save_after_id)
        self._lora_slots_save_after_id = self.root.after(
            500, lambda: self._lora_on_slot_changed(downgrade_row=downgrade_row))

    def _lora_sync_data(self):
        """Build self._lora_slots_data from current widget values."""
        result = []
        for slot in self.lora_slots:
            name = slot["combo_var"].get().strip()
            try:
                strength = float(slot["str_var"].get())
            except ValueError:
                strength = 1.0
            result.append({"name": name, "strength": strength, "auto": bool(slot.get("auto"))})
        self._lora_slots_data = result

    def _lora_persist(self):
        """Write lora_slots to settings.json."""
        self.settings["lora_slots"] = self._lora_slots_data
        self.save_json(self.SETTINGS_FILE, self.settings)

    def _lora_update_combos(self):
        """Refresh all slot combo values after _available_loras is updated."""
        choices = [LORA_NONE_VALUE] + self._available_loras
        for slot in self.lora_slots:
            current = slot["combo_var"].get()
            # Keep current value; if it's no longer in list, prepend it so it's not lost
            slot_choices = choices if current in choices else [current] + choices
            slot["combo"]["values"] = slot_choices

    def _lora_apply_theme(self):
        """Apply current color theme to all LoRA tk (non-ttk) widgets."""
        c = self.colors
        if hasattr(self, "lora_canvas"):
            self.lora_canvas.configure(bg=c["bg_alt"])
        for slot in self.lora_slots:
            try:
                slot["str_entry"].configure(
                    background=c["bg_input"], foreground=c["fg"],
                    insertbackground=c["fg"])
            except Exception:
                pass

    def _fetch_available_loras(self):
        """Fetch LoRA list from /promptforge/loras in a background thread.
        Updates self._available_loras and all combo dropdowns on completion."""
        def worker():
            url = f"{self.comfy_client.base_url}{COMFY_LORAS_PATH}"
            try:
                with urllib.request.urlopen(url, timeout=COMFY_HTTP_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    loras = data.get("loras", [])
                    if not isinstance(loras, list):
                        loras = []
            except Exception:
                loras = []
            self.root.after(0, lambda: self._on_loras_fetched(loras))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loras_fetched(self, loras: list):
        """Called on the main thread once LoRA fetch completes."""
        self._available_loras = loras
        self._lora_update_combos()

    def on_comfy_toggle(self):
        """Handles the "ComfyUI connected?" checkbox. Runs the health
        check off the main thread so a dead/unreachable ComfyUI doesn't
        freeze the UI for COMFY_HTTP_TIMEOUT seconds."""
        if not self.comfy_enabled.get():
            self.comfy_connected = False
            self.frame_comfy_options.pack_forget()
            self.frame_comfy_result.pack_forget()
            self.frame_lora.pack_forget()
            self.btn_generate_comfy.pack_forget()
            self.lbl_comfy_status.configure(text="")
            self._refresh_lib_lora_visibility()
            return

        host = self.ent_comfy_host.get().strip() or COMFY_DEFAULT_HOST
        try:
            port = int(self.ent_comfy_port.get().strip() or COMFY_DEFAULT_PORT)
        except ValueError:
            messagebox.showwarning("Invalid port", "Port must be a number.")
            self.comfy_enabled.set(False)
            return

        self.comfy_host = host
        self.comfy_port = port
        self.comfy_client = ComfyUIClient(host, port)
        self.settings["comfy_host"] = host
        self.settings["comfy_port"] = port
        self.save_json(self.SETTINGS_FILE, self.settings)

        self.lbl_comfy_status.configure(text="Checking connection…")
        self.ent_comfy_host.configure(state="disabled")
        self.ent_comfy_port.configure(state="disabled")
        self.chk_comfy_enabled.configure(state="disabled")

        def worker():
            try:
                self.comfy_client.check_connection()
                try:
                    out_dir = self.comfy_client.get_output_dir()
                except ComfyUIError:
                    out_dir = None
                # Try to fetch the live graph to check the bridge + node presence.
                graph, err = self._fetch_live_graph()
                if err:
                    workflow_ok, workflow_msg = False, err
                else:
                    workflow_ok, workflow_msg = self._validate_live_graph(graph)
                self.root.after(0, lambda: self._on_comfy_check_done(True, "", out_dir, workflow_ok, workflow_msg))
            except ComfyUIError as e:
                self.root.after(0, lambda: self._on_comfy_check_done(False, str(e), None, False, ""))
            except Exception as e:
                # Anything *unexpected* here (a malformed/unusual graph
                # from the bridge, a socket error that doesn't happen to
                # surface as ComfyUIError, etc.) used to propagate out of
                # worker() uncaught — which kills only this background
                # thread silently (Python doesn't crash the process for
                # an uncaught thread exception), but means
                # _on_comfy_check_done() never runs. Since that's the
                # *only* place that re-enables chk_comfy_enabled/
                # ent_comfy_host/ent_comfy_port and clears the "Checking
                # connection…" label, the ComfyUI section was left
                # permanently disabled and stuck — indistinguishable from
                # a real freeze to the user, even though the rest of the
                # app (and the window's own message loop) was still
                # perfectly responsive the whole time. Always reaching
                # _on_comfy_check_done(), even on a surprise error, is
                # what guarantees the UI never gets stranded like that.
                self.root.after(0, lambda e=e: self._on_comfy_check_done(
                    False, f"Unexpected error while checking connection: {e}", None, False, ""))

        threading.Thread(target=worker, daemon=True).start()

    def _on_comfy_check_done(self, success, error_msg, out_dir, workflow_ok, workflow_msg):
        self.ent_comfy_host.configure(state="normal")
        self.ent_comfy_port.configure(state="normal")
        self.chk_comfy_enabled.configure(state="normal")

        if not success:
            self.comfy_connected = False
            self.comfy_enabled.set(False)
            self.frame_comfy_options.pack_forget()
            self.frame_comfy_result.pack_forget()
            self.frame_lora.pack_forget()
            self.btn_generate_comfy.pack_forget()
            self.lbl_comfy_status.configure(text=f"✗ {error_msg}")
            self._refresh_lib_lora_visibility()
            messagebox.showerror("ComfyUI", f"Could not connect to ComfyUI:\n{error_msg}")
            return

        self.comfy_connected = True
        self.comfy_output_dir = out_dir
        self._refresh_lib_lora_visibility()
        self.frame_comfy_options.pack(fill="x")
        self.frame_comfy_result.pack(fill="x", pady=(10, 0))
        # Deferred (not called synchronously here): lets Tk finish its own
        # pending geometry pass for the widgets just packed above before
        # we go measuring/resizing them on top of that — forcing it all
        # through immediately via update_idletasks() in the same callback
        # is exactly the kind of thing that can misbehave on a tightly-
        # constrained (small) window where there's little slack to settle into.
        self.root.after_idle(self._resize_comfy_result_zone)

        if workflow_ok:
            self.lbl_comfy_status.configure(text="✓ Connected — graph ready")
            self.btn_generate_comfy.pack(side="left", fill="x", expand=True, padx=(8, 0))
            # Show LoRA section between frame_comfy and actions_frame.
            # Re-pack in correct order to ensure LoRA sits right below ComfyUI block.
            self.frame_lora.pack_forget()
            self.actions_frame.pack_forget()
            self.frame_lora.pack(fill="x", padx=(0, 10), pady=6)
            self.actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))
            # Kick off background fetch of available LoRAs
            self._fetch_available_loras()
        else:
            self.lbl_comfy_status.configure(
                text="⚠ Connected — open ComfyUI in browser with the node in your graph")
            self.btn_generate_comfy.pack_forget()
            self.frame_lora.pack_forget()

    def _fetch_live_graph(self):
        """Fetches the current graph from the JS bridge route
        GET /promptforge/graph (served by the custom node's Python side).
        Returns (graph_dict, None) on success or (None, error_str) on failure.
        Always called from a background thread — blocks briefly."""
        url = f"{self.comfy_client.base_url}{COMFY_GRAPH_PATH}"
        try:
            with urllib.request.urlopen(url, timeout=COMFY_HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                graph = data.get("graph")
                if not isinstance(graph, dict):
                    return None, "Bridge returned unexpected data (no 'graph' key)."
                return graph, None
        except urllib.error.HTTPError as e:
            if e.code == 503:
                try:
                    body = json.loads(e.read().decode("utf-8"))
                    detail = body.get("detail", "")
                except Exception:
                    detail = ""
                return None, (
                    "No graph snapshot available yet.\n"
                    "Open the ComfyUI browser tab (or reload it) so the "
                    "PromptForge Bridge extension can push the current graph." +
                    (f"\n\nDetails: {detail}" if detail else "")
                )
            return None, f"HTTP {e.code} from ComfyUI bridge: {e.reason}"
        except urllib.error.URLError as e:
            return None, f"Could not reach ComfyUI at {self.comfy_client.base_url}: {e.reason}"
        except json.JSONDecodeError:
            return None, "ComfyUI bridge returned invalid JSON."

    def _validate_live_graph(self, graph):
        """Checks that a fetched graph dict contains exactly one
        PromptForgeConnection node. Returns (ok: bool, message: str)."""
        node_id, node = ComfyUIClient.find_node_by_class_type(graph, COMFY_NODE_CLASS_TYPE)
        if node is None:
            return False, (
                f"No \"{COMFY_NODE_CLASS_TYPE}\" node was found in the "
                f"currently open ComfyUI workflow. Add the node to your "
                f"graph and make sure the browser tab is open."
            )
        return True, ""

    def _on_comfy_seed_mode_changed(self):
        if self.comfy_seed_mode.get() == "fixed":
            self.ent_comfy_seed.configure(state="normal")
        else:
            self.ent_comfy_seed.configure(state="disabled")

    def _on_comfy_resolution_changed(self, _event=None):
        choice = self.comfy_resolution_choice.get()
        for label, w, h in COMFY_RESOLUTION_PRESETS:
            if label == choice:
                if w is None:
                    self.ent_comfy_width.configure(state="normal")
                    self.ent_comfy_height.configure(state="normal")
                else:
                    self.comfy_width_var.set(str(w))
                    self.comfy_height_var.set(str(h))
                    self.ent_comfy_width.configure(state="disabled")
                    self.ent_comfy_height.configure(state="disabled")
                return

    def on_generate_clicked(self):
        """Entry point for "⚡ Generate prompt and copy". Pure text operation:
        assembles the prompt from the active builder (standard or custom),
        writes it to txt_output, and copies it to the clipboard. Never
        touches ComfyUI, so it isn't gated on comfy_busy."""
        self.generate_prompt()

    def on_generate_in_comfy_clicked(self):
        """Entry point for "🎨 Generate in ComfyUI". Deliberately does NOT
        rebuild the prompt from the blocks/template — it takes whatever
        text currently sits in txt_output (which the user may have hand-
        edited after generating) and submits exactly that."""
        if self.comfy_busy:
            messagebox.showinfo("ComfyUI", "A generation is already in progress.")
            return
        prompt_text = self.txt_output.get("1.0", tk.END).strip()
        if not prompt_text:
            messagebox.showinfo(
                "Empty prompt",
                "Generate a prompt first (or type one into the result box).")
            return
        self._start_comfy_generation(prompt_text)

    def _show_comfy_stop_button(self):
        """Switches btn_generate_comfy into its "Stop" state once ComfyUI
        has accepted the job (i.e. submit_prompt() returned a prompt_id).
        Purely cosmetic/control-flow — the live preview frames keep
        streaming in exactly as before; this just gives the user a way to
        abort early if the preview shows something's gone wrong (wrong
        character picked, bad composition, etc.)."""
        if not self.comfy_busy:
            return  # job already finished/failed/was stopped before this fired
        self.btn_generate_comfy.configure(
            text="⏹ Stop generation in ComfyUI",
            state="normal",
            command=self.on_comfy_stop_clicked)

    def _restore_comfy_generate_button(self):
        """Restores btn_generate_comfy to its normal "Generate in ComfyUI"
        state/label/command. Called from both the success and failure
        completion handlers so the button never gets stuck saying "Stop"
        after a job has actually ended."""
        self.btn_generate_comfy.configure(
            text="🎨 Generate in ComfyUI",
            state="normal",
            command=self.on_generate_in_comfy_clicked)

    def on_comfy_stop_clicked(self):
        """Handler for "⏹ Stop generation in ComfyUI". Sends a real
        POST /interrupt to ComfyUI so the GPU actually stops sampling —
        this is not just a local "give up waiting" cancel. Also tries to
        dequeue the same prompt_id in case it hadn't started executing
        yet (still queued behind another job), since /interrupt only ever
        affects whatever is currently running.

        Both calls are best-effort and run on a background thread (they're
        blocking HTTP calls) — wait_for_completion()'s should_cancel flag
        is set unconditionally afterwards regardless of whether the HTTP
        calls succeeded, so the UI always stops waiting even if ComfyUI
        is unreachable right at this moment."""
        if not self.comfy_busy or self._comfy_stopping:
            return
        self._comfy_stopping = True
        self.btn_generate_comfy.configure(state="disabled", text="Stopping…")
        prompt_id = self._comfy_current_prompt_id

        def worker():
            try:
                self.comfy_client.interrupt()
            except ComfyUIError:
                pass  # best-effort — the cancel flag below still stops our own wait either way
            if prompt_id:
                try:
                    self.comfy_client.delete_queue_item(prompt_id)
                except ComfyUIError:
                    pass
            self._comfy_cancel_flag = True

        threading.Thread(target=worker, daemon=True).start()

    # ---- ComfyUI: submission pipeline (threaded) ----
    def _start_comfy_generation(self, prompt_text):
        """Fetches the live graph from the bridge, patches it, and submits.
        The graph fetch is the only blocking network call that happens on the
        main thread here — it's fast (local HTTP), but we wrap it in the
        same background worker as the rest of the generation pipeline."""

        # Seed (resolve before handing off to thread)
        if self.comfy_seed_mode.get() == "fixed":
            try:
                seed = int(self.comfy_seed_value.get().strip())
            except ValueError:
                messagebox.showwarning("Invalid seed", "Seed must be a whole number.")
                return
        else:
            seed = random.randint(0, 2**32 - 1)
            self.comfy_seed_value.set(str(seed))

        # Resolution
        try:
            width  = int(self.comfy_width_var.get().strip())
            height = int(self.comfy_height_var.get().strip())
            if width <= 0 or height <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid resolution",
                                    "Width and height must be positive whole numbers.")
            return

        # Task 7.3: validate LoRA Manager slots before submitting to
        # ComfyUI. Only meaningful here (Generate in ComfyUI) — "Generate
        # prompt and copy" never touches ComfyUI and always works
        # regardless of what's in the LoRA Manager.
        missing_loras = [
            entry["name"] for entry in self._lora_slots_data
            if entry.get("name", LORA_NONE_VALUE) != LORA_NONE_VALUE
            and entry["name"] not in self._available_loras
        ]
        if missing_loras:
            if not self._available_loras:
                # List hasn't loaded yet (or failed) — don't hard-block,
                # just warn, per the plan ("don't block if the list is
                # simply empty/not yet loaded").
                self.lbl_comfy_result_status.configure(
                    text="⚠ LoRA list not loaded yet — skipping LoRA validation.")
            else:
                messagebox.showerror(
                    "Missing LoRA",
                    "Следующие LoRA не найдены в ComfyUI:\n"
                    + "\n".join(f"- {name}" for name in missing_loras))
                return

        # LoRA slots — read from the active slot data on the main thread
        # (before the worker starts, same pattern as negative_text).
        lora_slots_snapshot = list(self._lora_slots_data)

        # Negative prompt — read from the active tab's widget on the main
        # thread (before the worker starts, so no cross-thread widget access).
        if self.combo_template_category.get() == "Custom" and \
                hasattr(self, "txt_neg_prompt_custom") and \
                self.txt_neg_prompt_custom.winfo_exists():
            negative_text = self.txt_neg_prompt_custom.get("1.0", tk.END).strip()
        else:
            negative_text = self.txt_neg_prompt.get("1.0", tk.END).strip() \
                if hasattr(self, "txt_neg_prompt") else ""

        # Snapshot output dir (for mtime fallback)
        self._comfy_last_seen_files = set()
        if self.comfy_output_dir and os.path.isdir(self.comfy_output_dir):
            try:
                self._comfy_last_seen_files = set(os.listdir(self.comfy_output_dir))
            except OSError:
                pass

        self.comfy_busy = True
        self._comfy_cancel_flag = False
        self._comfy_current_prompt_id = None
        self._comfy_stopping = False
        # Disabled (not yet "Stop") until submit_prompt() returns a
        # prompt_id below — there's nothing to interrupt before ComfyUI
        # has actually accepted the job.
        self.btn_generate_comfy.configure(state="disabled")
        self.lbl_comfy_result_status.configure(text="Fetching graph from ComfyUI…")
        self.comfy_result_zone.show_placeholder()

        def worker():
            # 1. Fetch live graph from the JS bridge
            graph, err = self._fetch_live_graph()
            if err:
                self.root.after(0, lambda: self._on_comfy_generation_failed(err))
                return

            # 2. Validate
            ok, msg = self._validate_live_graph(graph)
            if not ok:
                self.root.after(0, lambda: self._on_comfy_generation_failed(msg))
                return

            # 3. Patch the PromptForgeConnection node
            node_id, node = ComfyUIClient.find_node_by_class_type(graph, COMFY_NODE_CLASS_TYPE)
            node.setdefault("inputs", {})
            node["inputs"]["prompt"]          = prompt_text
            node["inputs"]["seed"]            = seed
            node["inputs"]["width"]           = width
            node["inputs"]["height"]          = height
            node["inputs"]["negative_prompt"] = negative_text

            # 4. Patch PromptForgeMultiLoraLoader node if present in graph.
            # Graceful fallback (Task 2.7): absent node or malformed slot data
            # must never abort an otherwise valid generation.
            lora_node = None
            for nid, n in graph.items():
                if n.get("class_type") == "PromptForgeMultiLoraLoader":
                    lora_node = n
                    break
            if lora_node is not None:
                lora_node.setdefault("inputs", {})
                active_count = 0
                for i, slot in enumerate(lora_slots_snapshot, start=1):
                    if i > MAX_LORA_SLOTS:
                        break
                    try:
                        slot_name = (slot.get("name") or "").strip() or LORA_NONE_VALUE
                        slot_str = float(slot.get("strength", 1.0))
                        slot_str = max(LORA_STRENGTH_MIN, min(LORA_STRENGTH_MAX, slot_str))
                    except (ValueError, TypeError, AttributeError):
                        slot_name = LORA_NONE_VALUE
                        slot_str = 1.0
                    lora_node["inputs"][f"lora_{i}_name"] = slot_name
                    lora_node["inputs"][f"lora_{i}_strength"] = slot_str
                    active_count = i
                for i in range(active_count + 1, MAX_LORA_SLOTS + 1):
                    lora_node["inputs"][f"lora_{i}_name"] = LORA_NONE_VALUE
                    lora_node["inputs"][f"lora_{i}_strength"] = 1.0

            self.root.after(0, lambda: self.lbl_comfy_result_status.configure(
                text="Submitting to ComfyUI…"))

            try:
                prompt_id = self.comfy_client.submit_prompt(graph)
                self._comfy_current_prompt_id = prompt_id
                self.root.after(0, lambda: self.lbl_comfy_result_status.configure(
                    text=f"Queued ({prompt_id[:8]}…) — generating…"))
                self.root.after(0, self._show_comfy_stop_button)

                # Task 8: live TAESD/latent2rgb preview frames. Throttled
                # here (in this WS-listener thread) so we don't flood the
                # Tk main loop with a decode+redraw for every single
                # KSampler step. Whether this ever fires depends entirely
                # on ComfyUI's own "Live preview method" setting — nothing
                # to gate on this side.
                def _on_preview_frame(img_bytes):
                    now = time.time()
                    if now - self._comfy_last_preview_ts < self.COMFY_PREVIEW_MIN_INTERVAL:
                        return
                    self._comfy_last_preview_ts = now
                    self.root.after(0, lambda b=img_bytes: self._on_comfy_preview_bytes(b))

                entry = self.comfy_client.wait_for_completion(
                    prompt_id,
                    progress_callback=lambda cur, total: self.root.after(
                        0, lambda c=cur, t=total: self._on_comfy_progress(c, t)),
                    preview_callback=_on_preview_frame,
                    should_cancel=lambda: self._comfy_cancel_flag)

                # Primary path: download via /view (works with any subfolder,
                # any OS, even remote ComfyUI — no local path needed).
                filename, subfolder, img_type = ComfyUIClient.extract_image_info(entry)
                if filename:
                    try:
                        img_bytes = self.comfy_client.download_image(
                            filename, subfolder, img_type)
                        self.root.after(0, lambda b=img_bytes, n=filename, sf=subfolder:
                            self._on_comfy_image_bytes(b, n, sf))
                        return
                    except ComfyUIError:
                        pass  # fall through to local-path fallback

                # Fallback: scan local output dir by mtime (works when
                # /view fails or history has no image entry).
                image_path = self._find_newest_new_file()
                if image_path and os.path.exists(image_path):
                    self.root.after(0, lambda p=image_path:
                        self._on_comfy_generation_done(p))
                else:
                    self.root.after(0, lambda: self._on_comfy_generation_failed(
                        "Generation finished but the result image couldn't be located.\n"
                        "Check that SaveImage is in your graph and that ComfyUI's output "
                        "folder is accessible."))
            except ComfyUIError as e:
                self.root.after(0, lambda err=str(e): self._on_comfy_generation_failed(err))

        threading.Thread(target=worker, daemon=True).start()

    def _find_newest_new_file(self):
        """Fallback: scans comfy_output_dir recursively for the newest image
        file that wasn't present before submission. Recurses into subdirs
        so output/Anima/ and other subfolder prefixes are covered."""
        if not self.comfy_output_dir or not os.path.isdir(self.comfy_output_dir):
            return None
        candidates = []
        try:
            for root_dir, dirs, files in os.walk(self.comfy_output_dir):
                for fname in files:
                    if os.path.splitext(fname)[1].lower() not in IMAGE_EXTENSIONS:
                        continue
                    full = os.path.join(root_dir, fname)
                    # _comfy_last_seen_files holds flat names from the top-level
                    # dir — for subdirs we just compare mtime against job start.
                    rel = os.path.relpath(full, self.comfy_output_dir)
                    if rel in self._comfy_last_seen_files:
                        continue
                    candidates.append((os.path.getmtime(full), full))
        except OSError:
            return None
        if not candidates:
            return None
        candidates.sort(key=lambda t: t[0], reverse=True)
        return candidates[0][1]

    # ---- progress & image callbacks (always called on the main thread) ----

    def _on_comfy_progress(self, current, total):
        """Updates the progress bar during generation.
        current/total are node counts from /queue polling."""
        if total <= 0:
            return
        pct = min(100.0, 100.0 * current / total)
        self.comfy_progress_var.set(pct)
        self.lbl_comfy_progress.configure(text=f"{current}/{total}")
        # Make the progress bar visible the first time we get a reading
        if not self.frame_comfy_progress.winfo_ismapped():
            self.frame_comfy_progress.pack(fill="x", pady=(6, 0))
            self._resize_comfy_result_zone()

    def _on_comfy_preview_bytes(self, img_bytes):
        """Task 8: live TAESD/latent2rgb preview frame, decoded straight
        from the WebSocket (never touches disk). Always called on the
        main thread via root.after().

        This only ever fires if ComfyUI itself is sending preview frames,
        which is controlled entirely by the user's own ComfyUI setting
        (Settings -> Comfy > Execution -> "Live preview method"). There
        is no separate Prompt Forge toggle to keep in sync with that —
        if the user has it set to "none", no frames are sent and this
        method simply never runs.

        Guarded on comfy_busy so a stray frame that was already in
        flight when the job finished/got cancelled can't briefly
        overwrite the final image (or a cleared placeholder) with a
        stale mid-generation preview.
        """
        if not self.comfy_busy:
            return
        self.comfy_result_zone.show_image_bytes(img_bytes)

    def _on_comfy_image_bytes(self, img_bytes, filename, subfolder=""):
        """Receives raw image bytes downloaded from /view, saves them to a
        numbered file next to prompt_forge_data so PIL can open them, then
        displays and remembers the path for Open folder."""
        # Remember ComfyUI's own filename/subfolder for this result — this
        # is what lets "Open folder" later point at ComfyUI's real output/
        # folder instead of this local throwaway preview copy.
        self.comfy_last_remote_filename = filename
        self.comfy_last_remote_subfolder = subfolder or ""

        # Save alongside prompt_forge_data for a predictable, accessible
        # location. Each result gets its own numbered file (result_NNN.*)
        # rather than overwriting a single "last_result" file — this is
        # what backs the Gallery (Task 3), letting it show every image
        # generated this session instead of only the most recent one.
        # The whole folder is wiped at startup (init_folders()), so these
        # never pile up across sessions.
        tmp_dir = os.path.join(self.DATA_DIR, "_comfy_previews")
        os.makedirs(tmp_dir, exist_ok=True)
        self._comfy_session_image_counter += 1
        ext = os.path.splitext(filename)[1] or ".png"
        tmp_path = os.path.join(tmp_dir, f"result_{self._comfy_session_image_counter:03d}{ext}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(img_bytes)
        except OSError as e:
            self._on_comfy_generation_failed(f"Could not save preview image: {e}")
            return
        self._on_comfy_generation_done(tmp_path, remote_name=filename)

    def _on_comfy_generation_done(self, image_path, remote_name=None):
        """Shared completion handler for both the local-path and
        downloaded-bytes paths. remote_name is the original filename from
        ComfyUI (used for display) when the image was downloaded via /view."""
        self.comfy_busy = False
        self._comfy_current_prompt_id = None
        self._comfy_stopping = False
        self._restore_comfy_generate_button()
        self.comfy_last_image_path = image_path
        if not remote_name:
            # Local mtime-scan fallback: image_path already lives inside
            # ComfyUI's real output dir, so there's no separate remote
            # filename/subfolder to remember — comfy_open_output_folder()
            # will just use image_path's own directory.
            self.comfy_last_remote_filename = None
            self.comfy_last_remote_subfolder = None
        self.comfy_result_zone.show_image_path(image_path)

        display_name = remote_name or os.path.basename(image_path)
        self.lbl_comfy_result_status.configure(text=f"✓ {display_name}")

        # Gallery (Task 3): every successful result gets a thumbnail,
        # using whatever remote filename/subfolder this result has (set,
        # or just cleared above for the local-scan fallback) — the same
        # output_dir-vs-local-copy priority comfy_open_output_folder()
        # uses for "Open folder".
        self._gallery_register_result(
            local_path=image_path,
            remote_filename=self.comfy_last_remote_filename,
            remote_subfolder=self.comfy_last_remote_subfolder,
            display_name=display_name,
        )

        # Hide progress bar, reset it
        self.frame_comfy_progress.pack_forget()
        self.comfy_progress_var.set(0.0)
        self.lbl_comfy_progress.configure(text="")
        self._resize_comfy_result_zone()

        # Show Open folder button now that there's something to open
        self.btn_comfy_open_folder.pack(side="right")

    def _on_comfy_generation_failed(self, error_msg):
        was_user_stop = self._comfy_stopping
        self.comfy_busy = False
        self._comfy_current_prompt_id = None
        self._comfy_stopping = False
        self._restore_comfy_generate_button()
        self.frame_comfy_progress.pack_forget()
        self.comfy_progress_var.set(0.0)
        self.lbl_comfy_progress.configure(text="")
        self._resize_comfy_result_zone()
        if was_user_stop:
            # Expected, user-initiated abort — not an error, so no
            # error dialog (that would be a confusing "failure" popup
            # for something the user explicitly asked for).
            self.lbl_comfy_result_status.configure(text="⏹ Generation stopped.")
        else:
            self.lbl_comfy_result_status.configure(text=f"✗ Generation failed")
            messagebox.showerror("ComfyUI generation failed", error_msg)

    def comfy_open_output_folder(self):
        """Opens the folder containing the last generated image in the
        OS file explorer, with that image already selected/highlighted —
        the same behavior as Windows Explorer's "Show in folder" or
        macOS Finder's "Reveal". Prefers ComfyUI's real output/ folder
        (+ whatever subfolder the node saved into) over the local
        throwaway preview copy used just to render the thumbnail —
        see _resolve_comfy_output_folder()."""
        if not self.comfy_last_image_path:
            return

        folder = self._resolve_comfy_output_folder()
        if folder and self.comfy_last_remote_filename:
            target_file = os.path.join(folder, self.comfy_last_remote_filename)
        else:
            # Local mtime-scan fallback: comfy_last_image_path already
            # lives inside ComfyUI's real output dir.
            target_file = os.path.abspath(self.comfy_last_image_path)
            folder = os.path.dirname(target_file)

        self._reveal_file_in_explorer(target_file, folder)

    def _reveal_file_in_explorer(self, target_file, folder):
        """Opens `folder` in the OS file explorer with `target_file`
        selected/highlighted if possible (Windows "Show in folder" /
        macOS Finder "Reveal"). Falls back to just opening the folder
        when the file can't be located there, or on platforms without a
        "select" mechanism (Linux has no universal way to highlight a
        specific file across desktop environments). Shared by the
        Builder's "Open folder" button (comfy_open_output_folder) and the
        Gallery's per-image magnifier action (_gallery_reveal_in_explorer)."""
        try:
            if sys.platform == "win32":
                if os.path.isfile(target_file):
                    # /select, opens the folder with the file highlighted
                    # — identical to right-click → "Show in folder".
                    proc = subprocess.Popen(["explorer", "/select,", os.path.normpath(target_file)])
                    self._win_bring_explorer_to_front(proc.pid)
                else:
                    os.startfile(folder)
            elif sys.platform == "darwin":
                if os.path.isfile(target_file):
                    subprocess.Popen(["open", "-R", target_file])
                else:
                    subprocess.Popen(["open", folder])
            else:
                # No universal "select this file in the file manager" on
                # Linux (varies per desktop environment/FM) — open the
                # containing folder, which is the best cross-DE option.
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showwarning("Open folder", f"Could not open folder:\n{e}")

    @staticmethod
    def _win_bring_explorer_to_front(pid):
        """Best-effort: makes the freshly-launched Explorer window come up
        ON TOP of Prompt Forge instead of opening behind it.

        Windows clicked the "Open folder" button knowing it should result
        in a visible folder window — but Windows itself is conservative
        about letting any background process force its own window to the
        foreground (anti-focus-stealing protection), and a process we just
        spawned with subprocess.Popen counts as "background" from the
        OS's point of view even though the user just triggered it via a
        click in our window a moment ago. AllowSetForegroundWindow is the
        official, narrow exception for exactly this case: "a process I
        just launched is allowed to foreground itself once." It only
        affects that one process/that one call, asks for no new
        permissions, and needs nothing beyond the ctypes already used
        elsewhere for the taskbar icon — so it's safe to attempt and
        harmless if it fails (e.g. on non-Windows, or older interpreters
        without ctypes.windll)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(pid)
        except Exception:
            pass

    def _resolve_output_folder_for(self, remote_filename, remote_subfolder):
        """Resolves the real ComfyUI output folder (output_dir/subfolder)
        for an arbitrary remote filename/subfolder pair. If
        comfy_output_dir hasn't been discovered yet (e.g. the live-graph
        fetch never needed it), asks ComfyUI directly via GET
        /system_stats right here at call time — a fast, local HTTP call.
        Returns None if there's nothing better than a local preview copy
        to offer.

        Generalized out of the original _resolve_comfy_output_folder() so
        the Gallery (Task 3) — where every cell has its own remote name,
        not just the single "last result" the Builder panel tracks — can
        use the exact same output_dir-vs-local-copy priority."""
        if not remote_filename:
            return None  # this result came from the local-scan fallback

        out_dir = self.comfy_output_dir
        if not out_dir:
            try:
                out_dir = self.comfy_client.get_output_dir()
                if out_dir:
                    self.comfy_output_dir = out_dir
            except Exception:
                out_dir = None

        if not out_dir:
            return None

        subfolder = remote_subfolder or ""
        folder = os.path.join(out_dir, subfolder) if subfolder else out_dir
        return folder if os.path.isdir(folder) else None

    def _resolve_comfy_output_folder(self):
        """Builder-panel convenience wrapper: resolves the output folder
        for the single most recent result tracked on self."""
        return self._resolve_output_folder_for(
            self.comfy_last_remote_filename, self.comfy_last_remote_subfolder)


if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = PromptForgeApp(root)
    root.mainloop()

