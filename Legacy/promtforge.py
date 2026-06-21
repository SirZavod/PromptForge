import os
import re
import sys
import glob
import json
import time
import uuid
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

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


class PromptForgeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Prompt Forge v2.0")
        self._apply_app_icon()
        self.root.geometry("1280x860")
        self.root.minsize(1040, 680)

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

        self.style = ttk.Style()
        self.apply_theme()

        self.create_ui()
        self.reload_all_lists()
        self.refresh_library_list()
        self.refresh_history_list()

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

    def refresh_themed_widgets(self):
        """Recolors widgets that tk (not ttk) doesn't pick up via ttk.Style."""
        c = self.colors
        widgets = [
            getattr(self, "txt_output", None),
            getattr(self, "txt_lib_tags", None),
            getattr(self, "txt_lib_preview", None),
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

    # ==========================================================
    #                          UI: ROOT
    # ==========================================================
    def create_ui(self):
        c = self.colors
        # Top bar: title + theme toggle
        topbar = tk.Frame(self.root, bg=c["bg"])
        topbar.pack(fill="x", padx=18, pady=(14, 0))

        tk.Label(topbar, text="⚡ Prompt Forge", bg=c["bg"], fg=c["fg"],
                 font=("Segoe UI", 16, "bold")).pack(side="left")
        tk.Label(topbar, text="prompt builder", bg=c["bg"], fg=c["fg_dim"],
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

        self.notebook.add(self.tab_forge, text="🛠  Builder")
        self.notebook.add(self.tab_library, text="📚  Library")
        self.notebook.add(self.tab_history, text="🕘  History")

        self.build_forge_tab()
        self.build_library_tab()
        self.build_history_tab()

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
        self.combo_style = ttk.Combobox(row_style, textvariable=self.selected_style, state="readonly")
        self.combo_style.pack(side="left", fill="x", expand=True)
        self.combo_style.bind("<<ComboboxSelected>>", lambda e: self.update_live_preview())
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
        self.combo_scenario = ttk.Combobox(row_scen, textvariable=self.selected_scenario, state="readonly")
        self.combo_scenario.pack(side="left", fill="x", expand=True)
        self.combo_scenario.bind("<<ComboboxSelected>>", lambda e: self.update_live_preview())
        btn_scen_preview = ttk.Button(row_scen, text="👁", width=3,
                                       command=lambda: self.quick_preview("scenarios", self.selected_scenario))
        btn_scen_preview.pack(side="left", padx=(6, 0))
        Tooltip(btn_scen_preview, "Show the content of the selected scenario", self)

        # --- Actions ---
        actions_frame = ttk.Frame(left)
        actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))
        btn_generate = ttk.Button(actions_frame, text="⚡ Generate and copy", style="Accent.TButton",
                                   command=self.generate_prompt)
        btn_generate.pack(side="left", fill="x", expand=True)
        btn_clear = ttk.Button(actions_frame, text="Clear all", style="Ghost.TButton", command=self.clear_forge)
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

        self._last_generated = ""
        self.refresh_themed_widgets()

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
                ttk.Label(row, text=f"Character {idx}:", style="CardTitle.TLabel").pack(side="left", padx=(0, 10))

                ttk.Label(row, text="Who:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
                char_var = tk.StringVar()
                combo_char = ttk.Combobox(row, textvariable=char_var, state="readonly", width=20)
                combo_char["values"] = ["None"] + self.get_file_list("characters")
                combo_char.current(0)
                combo_char.pack(side="left", padx=(0, 14))

                outfit_var = tk.StringVar()
                outfit_combo = None
                if idx in parsed["outfit_idx"]:
                    ttk.Label(row, text="Outfit:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
                    outfit_combo = ttk.Combobox(row, textvariable=outfit_var, state="readonly", width=20)
                    outfit_combo["values"] = ["None"]
                    outfit_combo.current(0)
                    outfit_combo.pack(side="left")
                    combo_char.bind("<<ComboboxSelected>>",
                                     lambda e, cv=char_var, co=outfit_combo: self.update_outfit_list(cv, co))

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
            self.custom_style_combo = ttk.Combobox(style_frame, textvariable=self.custom_style_var, state="readonly")
            self.custom_style_combo["values"] = ["None"] + self.get_file_list("styles")
            self.custom_style_combo.current(0)
            self.custom_style_combo.pack(fill="x")

        if parsed["use_scenario"]:
            scen_frame = ttk.LabelFrame(self.custom_section, text=" Scenario ", padding=12)
            scen_frame.pack(fill="x", pady=6)
            self.custom_scenario_var.set("None")
            self.custom_scenario_combo = ttk.Combobox(scen_frame, textvariable=self.custom_scenario_var, state="readonly")
            self.custom_scenario_combo["values"] = ["None"] + self.get_file_list("scenarios")
            self.custom_scenario_combo.current(0)
            self.custom_scenario_combo.pack(fill="x")

        if not slot_indices and not parsed["use_style"] and not parsed["use_scenario"]:
            ttk.Label(self.custom_section, text="This template consists only of fixed text.",
                      style="Dim.TLabel").pack(anchor="w", pady=6)

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

        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", final_prompt)

        self.root.clipboard_clear()
        self.root.clipboard_append(final_prompt)
        self.lbl_copy_status.configure(text="✓ Prompt generated and copied to clipboard")

        self._last_generated = final_prompt
        self.add_to_history(final_prompt)

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

        row2 = ttk.Frame(slot_frame, style="Card.TFrame")
        row2.pack(fill="x", pady=(8, 0))

        ttk.Label(row2, text="Who:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        combo_char = ttk.Combobox(row2, textvariable=char_var, state="readonly", width=22)
        combo_char["values"] = ["None"] + self.get_file_list("characters")
        combo_char.current(0)
        combo_char.pack(side="left", padx=(0, 14))

        btn_char_preview = ttk.Button(row2, text="👁", width=3,
                                       command=lambda cv=char_var: self.quick_preview("characters", cv))
        btn_char_preview.pack(side="left", padx=(0, 14))
        Tooltip(btn_char_preview, "Show character description", self)

        ttk.Label(row2, text="Outfit:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        combo_outfit = ttk.Combobox(row2, textvariable=outfit_var, state="readonly", width=22)
        combo_outfit["values"] = ["None"]
        combo_outfit.current(0)
        combo_outfit.pack(side="left", padx=(0, 14))

        btn_outfit_preview = ttk.Button(row2, text="👁", width=3,
                                         command=lambda ov=outfit_var, cv=char_var: self.quick_preview_outfit(cv, ov))
        btn_outfit_preview.pack(side="left")
        Tooltip(btn_outfit_preview, "Show outfit description", self)

        combo_char.bind("<<ComboboxSelected>>",
                         lambda event, cv=char_var, co=combo_outfit: self.update_outfit_list(cv, co))

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

        self.txt_lib_tags = scrolledtext.ScrolledText(right, height=10, font=self.default_font, wrap=tk.WORD,
                                                         relief="flat", borderwidth=0,
                                                         bg=c["bg_input"], fg=c["fg"], insertbackground=c["fg"],
                                                         selectbackground=c["accent"], selectforeground=c["accent_text"])
        self.txt_lib_tags.pack(fill="both", expand=True, pady=8)

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

        self.lbl_lib_status.configure(text=f"Editing existing entry: {base}")

    def start_new_library_entry(self, keep_category=False):
        self.lib_selected_file = None
        self.lib_editing_canon_owner = None
        self.tree_library.selection_remove(self.tree_library.selection())
        self.ent_lib_name.configure(state="normal")
        self.ent_lib_name.delete(0, tk.END)
        self.txt_lib_tags.delete("1.0", tk.END)
        if not keep_category:
            self.is_canon_var.set(False)
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

        filepath = os.path.join(self.DATA_DIR, cat, filename)

        # protection against overwriting a new entry with the same name
        if not is_editing_canon and self.lib_selected_file is None and os.path.exists(filepath):
            if not messagebox.askyesno("Entry exists",
                                        f"An entry named \"{os.path.splitext(filename)[0]}\" already exists. Overwrite?"):
                return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(tags)
            self.lbl_lib_status.configure(text=f"✓ Saved as {filename}")
            self.refresh_library_list()
            self.reload_all_lists()
            saved_base = os.path.splitext(filename)[0]
            self.lib_selected_file = saved_base
            if self.tree_library.exists(saved_base):
                self.tree_library.selection_set(saved_base)
                self.tree_library.see(saved_base)
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
        style_name = self.selected_style.get()
        style_tags = self.read_file_content("styles", style_name)
        if style_tags:
            if valid_chars_count > 0:
                return f"{style_tags}, a scene of {valid_chars_count} characters"
            return style_tags
        elif valid_chars_count > 0:
            return f"a scene of {valid_chars_count} characters"
        return ""

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

        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", final_prompt)

        self.root.clipboard_clear()
        self.root.clipboard_append(final_prompt)
        self.lbl_copy_status.configure(text="✓ Prompt generated and copied to clipboard")

        self._last_generated = final_prompt
        self.add_to_history(final_prompt)


if __name__ == "__main__":
    root = tk.Tk()
    app = PromptForgeApp(root)
    root.mainloop()
