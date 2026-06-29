import os
import re
import sys
import subprocess
import glob
import json
import time
import uuid
import shutil
import zipfile
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
from tkinter import ttk, messagebox, scrolledtext, filedialog, simpledialog

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

# ===================== Library folders (virtual subfolders) =====================
# Per-category mapping of {entry_name: "folder/path"} persisted in a single
# JSON file. Folders here are PURE UI/organization metadata: they never
# change where a .txt/.jpg/.meta.json actually lives on disk, and the
# Builder/get_file_list/history/lora-binding code never has to know they
# exist — they keep working off the same flat, globally-unique-per-category
# entry name as before. See _folders.json / load_folder_map / etc.
LIBRARY_FOLDERS_FILE_NAME = "_folders.json"
# Path separator used INSIDE a folder path value (e.g. "Casual Clothes/Wednesday").
# Never a literal OS path — purely a display hierarchy.
FOLDER_PATH_SEP = "/"
# Auto-managed virtual folder that canon outfits are filed into automatically
# the moment they're marked "Is this a character's canon outfit?". Users
# cannot rename it, delete it, or drop ordinary (non-canon) outfits into it
# manually — see _is_protected_folder().
CANONICAL_OUTFITS_FOLDER = "Canonical Outfits"

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
# How long "🎨 Generate in ComfyUI" briefly disables itself after a click,
# purely to absorb panic double/triple-clicking — NOT related to comfy_busy
# (the button stays usable while a generation is in flight; this only
# guards against the same click landing in the queue several times).
COMFY_QUEUE_DEBOUNCE_MS = 450
# No app-side cap on how many items can sit in the local queue — ComfyUI's
# own server-side queue has no hard limit either, and is the thing that
# would actually choke first if someone queued an unreasonable number of
# jobs. That's accepted as the user's own problem (see the queue feature
# discussion) rather than something this app second-guesses with an
# arbitrary number.

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

_NATURAL_SORT_RE = re.compile(r'(\d+)')


def natural_sort_key(s):
    """Sort key that compares embedded numbers numerically instead of
    character-by-character — "Canon 2" before "Canon 10" before
    "Canon 21", not "Canon 1" < "Canon 10" < "Canon 11" ... < "Canon 2"
    the way plain string sorting would put them (see the Canonical
    Outfits sort-order bug report this fixes). Splits the string into
    alternating digit/non-digit runs; digit runs become int for
    comparison, everything else is lowercased for a case-insensitive
    compare exactly like every sort site here already wanted via
    str.lower()/.lower(). Used by every sort of a human-readable library/
    folder/LoRA-path name in the app — not just Canonical Outfits, since
    "Pose 2" vs "Pose 10" in any ordinary category dropdown has the
    identical bug otherwise."""
    return [int(chunk) if chunk.isdigit() else chunk.lower()
            for chunk in _NATURAL_SORT_RE.split(s)]


CATEGORY_LABELS = {
    "styles": "Style",
    "scenarios": "Scenario",
    "characters": "Character",
    "outfits": "Outfit",
    "tools": "Tool",
}

CATEGORY_ICONS = {
    "styles": "🎨",
    "scenarios": "🎬",
    "characters": "🧑",
    "outfits": "👕",
    "tools": "🔧",
}

PREFIXES = ["First:", "Second:", "Third:", "Fourth:", "Fifth:", "Sixth:", "Seventh:", "Eighth:"]

# Display names for the Standard builder's block_order ("Style →
# Characters → Scenario → Tools", and the "Block order..." reorder
# dialog's listbox). Deliberately separate from CATEGORY_LABELS (which
# says "Character"/"Tool", singular, for the Library tab's per-entry
# labels) — block_order keys name a whole SECTION of the builder, where
# the plural "Characters"/"Tools" reads better. Kept as one shared
# constant rather than copy-pasted per use site, since a third copy is
# exactly the kind of thing that quietly goes stale (this used to be two
# separate inline dicts in open_order_dialog and _order_to_text — adding
# "tools" to only one of them would have been an easy, silent mistake).
BLOCK_ORDER_LABELS = {
    "style": "Style",
    "characters": "Characters",
    "scenario": "Scenario",
    "tools": "Tools",
}

INVALID_FS_CHARS = r'[\\/:*?"<>|]'

# Custom template variables are written directly in the template text as
# "[Name 1]", "[Description 2]", "[Outfit 1]", "[Style]", "[Scenario]".
# The number after "Name"/"Description"/"Outfit" ties the variable to a
# specific "template character" (slot) — the same one for all three variable types.
CUSTOM_VAR_PATTERN = re.compile(
    r"\[(Name|Description|Outfit)\s+(\d+)\]|\[(Style)\]|\[(Scenario)\]|\[(Tool)\]")

# In-app guide (F1 / "❓ Guide"). Structured multi-language from the
# start so adding a translation later is just filling in a dict entry —
# no changes to the modal/rendering code itself. Per the guide feature
# discussion: write English first (for an absolute beginner), translate
# to the rest of Civitai's main audience languages afterward. Every
# non-English language below is an EXPLICIT placeholder (its own marked
# "translation pending" text, not a silent copy of the English section)
# so there's never ambiguity about whether a translation actually exists
# yet — a half-translated guide that quietly falls back to English mid-
# section would be more confusing than one that's honest about being
# untranslated so far.
GUIDE_LANGUAGES = {
    "en": "English",
    "ru": "Русский",
    "zh": "中文",
    "ja": "日本語",
}

_GUIDE_PENDING_NOTE = {
    "ru": "Перевод этого раздела пока не готов. Ниже — текст на английском.",
    "zh": "本节翻译尚未完成。以下为英文原文。",
    "ja": "このセクションの翻訳はまだ準備中です。以下は英語版です。",
}


def _guide_pending(lang, english_title, english_body):
    """Builds a placeholder section for a not-yet-translated language —
    shows the English content with an explicit note at the top saying
    so, rather than silently presenting English as if it were the
    translation."""
    note = _GUIDE_PENDING_NOTE.get(lang, "Translation pending — showing English below.")
    return english_title, f"[{note}]\n\n{english_body}"


GUIDE_CONTENT = {
    "en": {
        "quick_start": ("Quick start", """\
Welcome! This is the order things actually need to happen in, the first
time you open PromptForge with a library you didn't build yourself.

1. Go to the Library tab. Click through Styles, Characters, Outfits,
   Scenarios, and Tools at the top-left and look at a few entries —
   just to get a feel for what's actually in this library before doing
   anything else. If everything is empty, you haven't pointed
   PromptForge at a populated prompt_forge_data/ folder yet (or you're
   starting from scratch — see "Library & Subfolders" below for how
   entries work).

2. Go to the Builder tab. Pick a Style, add at least one Character (and
   an Outfit for them), optionally a Scenario. Click
   "⚡ Generate prompt and copy" — this works with zero setup, no
   ComfyUI required, and just builds text you can paste anywhere.

3. If you want PromptForge to generate the image for you directly
   (instead of pasting the prompt somewhere else), see "Connecting to
   ComfyUI" below — it's a separate, optional step with its own
   one-time setup.

4. (Optional, only if you downloaded LoRA files for this library) Once
   ComfyUI is connected, go back to the Library tab and click
   "🔍 Check LoRA dependencies" to confirm every LoRA the library
   expects is actually where ComfyUI can find it. This catches "did I
   actually download everything?" before you start generating dozens
   of characters, not after a confusing result on one of them.

That's the whole loop. Everything else in this guide is detail on one
piece of it."""),

        "library": ("Library & Subfolders", """\
The Library tab holds everything reusable: Styles, Characters, Outfits,
Scenarios, and Tools. Each entry is just a name plus some text (its
"tags") — the Builder pastes that text into the final prompt wherever
you place that entry.

Subfolders are PURELY for browsing. Dragging an entry into a folder, or
organizing your library into "Anime & Cartoon" / "Casual Clothes" / etc.
has zero effect on search, on the Builder's dropdowns, or on which LoRA
is bound to what — an entry's NAME is still the one thing that
identifies it everywhere else in the app. Right-click anywhere in the
list for folder options (New folder, Move to..., rename, delete) — a
right-click on empty space still offers "New folder", just not "Move
to..." (nothing was selected to move).

Canonical Outfits is a special, automatically-managed folder: outfits
you've marked as a character's "canon" look get filed there
automatically, and you can't manually drag an ordinary outfit into it.

Each entry can optionally have: a reference image (drag a file onto the
editor, or click to browse), a source URL (to credit/relocate the
original model), and a bound LoRA (see "LoRA Manager" below for what
that actually does)."""),

        "tools_category": ("The Tools category", """\
Tools are library entries that usually have NO real prompt text — their
whole reason for existing is a bound LoRA (an anatomy fixer, a hand
detailer, a sharpness LoRA, anything Stable Diffusion effectively can't
do without). Unlike every other category, a Tool can be saved with
completely empty tags.

If a Tool DOES have a short tag (some workflows trigger a specific LoRA
behavior with something like "@fixedanatomy"), you can mark it "Force
this tool's tag to the very start of the prompt" in the Library editor —
that tag then always lands as the very first thing in the assembled
prompt, ahead of Style/Characters/Scenario, no matter how you've
reordered everything else via "Block order...". Tools without that flag
just sit wherever "Tools" falls in your block order, like any other
section.

In the Builder, the Tools section starts collapsed — click it open with
"▸ Tools" when you actually want to look at or change what's in it."""),

        "lora_manager": ("LoRA Manager", """\
Every active Style, Character, Outfit, and Tool that has a LoRA bound to
it in the Library gets pulled into the LoRA Manager automatically,
tagged [A] (automatic). You can also add a LoRA by hand with
"+ Add LoRA", tagged [M] (manual) — useful for a one-off LoRA you don't
want to permanently bind to a library entry.

The LoRA Manager section starts expanded by default, but is collapsible
(click "▾ LoRA" to fold it away) — once your auto-bound LoRAs are set
the way you want, there's usually no reason to keep staring at the list
while you work on Characters/Scenario. Your slots and strengths persist
between sessions.

Before every "🎨 Generate in ComfyUI", every active slot's LoRA name is
checked against ComfyUI's own live LoRA list — a missing file is caught
right there, before anything is submitted, instead of silently being
skipped mid-generation."""),

        "comfyui": ("Connecting to ComfyUI", """\
Direct generation is entirely optional — "⚡ Generate prompt and copy"
always works with zero ComfyUI setup. Connecting unlocks
"🎨 Generate in ComfyUI" (submit and watch it generate without leaving
PromptForge), the Negative prompt section, the LoRA Manager, and the
generation queue.

Setup: install the companion PromptForge Connection custom node package
into ComfyUI/custom_nodes/, place a PromptForge Connector node somewhere
in your ComfyUI graph, then tick "ComfyUI connected?" in the Builder's
ComfyUI panel.

IMPORTANT — generation always targets the LAST ACTIVE workflow tab in
your browser. PromptForge has no concept of "which workflow you meant":
it asks the bridge for whatever ComfyUI graph was most recently active
in the browser, and submits there. If you have two workflows open and
clicked over to a different tab just to glance at it, your next
generation goes to THAT one, LoRAs included. This holds even if you
close the browser tab, close the browser entirely, or kill the browser
process afterward — ComfyUI keeps using whichever workflow was last
active. That also means you can free up the RAM a browser tab uses
once you've confirmed the right workflow is active, without affecting
generation at all.

Live preview frames depend entirely on ComfyUI's own Settings → Comfy →
Execution → Live preview method setting — if it's set to "none", no
frames arrive, and that's not something PromptForge controls."""),

        "queue": ("The generation queue", """\
Clicking "🎨 Generate in ComfyUI" always succeeds immediately — it adds
your current prompt, seed, resolution, and LoRA snapshot to a queue
rather than refusing if something is already generating. Everything
about that click (including which LoRAs and strengths are active right
then) is frozen into that queue entry — changing a LoRA strength
afterward only affects FUTURE clicks, never one already queued.

Exactly one job runs with ComfyUI at a time; queued items wait their
turn and start automatically as each one finishes. "⏹ Stop" cancels
only the one currently running, then the next queued item starts
automatically — it never touches anything still waiting. "🗑 Clear
queue" removes everything still WAITING, but never the one already
generating (matching how ComfyUI's own built-in queue UI behaves) — use
Stop for that one specifically.

The small "📋 N queued" counter next to Generate is there so a rapid
flurry of clicks has visible confirmation that they actually landed,
instead of wondering if anything happened."""),

        "history_gallery": ("History & Gallery", """\
Every prompt you generate is saved to History automatically, with a
star/favorite and one-click restore back into the Builder.

When ComfyUI is connected, History entries also carry which LoRAs (and
at what strength) were active for that specific generation, plus an
"Open image" button to jump straight to the result — using the exact
same "last known link" logic as the Gallery's own magnifier icon. If the
underlying file has since been moved, renamed, or deleted in ComfyUI's
own output folder, that's not something PromptForge can recover from;
there's no thumbnail cached as a fallback by design.

The Gallery tab shows every image generated through ComfyUI THIS
session as a thumbnail — hover to reveal it in your file explorer, click
to open it full-size."""),

        "known_issues": ("Known issues", """\
Theme toggle doesn't always fully recolor every widget immediately — a
few may keep their old colors until you restart the app. Purely
cosmetic, nothing is lost.

Toggling "ComfyUI connected?" while the app is in a small/non-maximized
window can occasionally cause a UI freeze or crash, depending on your
display resolution and the window's current size. If this happens,
maximize the window before checking that box."""),
    },
    "ru": {
        "quick_start": ("Быстрый старт", """\
Добро пожаловать! Это порядок, в котором нужно делать всё при первом запуске
PromptForge с чужой библиотекой.

1. Откройте вкладку Library. Кликните по Styles, Characters, Outfits, Scenarios
   и Tools слева сверху и посмотрите несколько записей — просто чтобы понять,
   что вообще в этой библиотеке, перед тем как что-то делать. Если везде пусто,
   вы ещё не указали PromptForge на папку prompt_forge_data/ (или стартуете с нуля —
   см. "Library & Subfolders" ниже, как это работает).

2. Откройте вкладку Builder. Выберите Style, добавьте хотя бы одного Character
   (и Outfit для него), опционально Scenario. Кликните "⚡ Generate prompt and copy" —
   это работает без всяких настроек ComfyUI, просто генерирует текст, который
   можно вставить куда угодно.

3. Если хотите, чтобы PromptForge сгенерировал изображение прямо сейчас
   (вместо того чтобы просто скопировать промпт), см. "Connecting to ComfyUI"
   ниже — это отдельная опциональная настройка с собственной инструкцией.

4. (Опционально, только если вы скачали LoRA файлы) Как только ComfyUI
   подключится, вернитесь на вкладку Library и кликните
   "🔍 Check LoRA dependencies" — это проверит, что все нужные LoRA находятся там,
   где их может найти ComfyUI. Лучше узнать про недостающие файлы до того, как
   вы сгенерируете кучу результатов.

Вот весь цикл. Всё остальное в этом гайде — детали."""),

        "library": ("Библиотека и подпапки", """\
Вкладка Library хранит всё переиспользуемое: Styles, Characters, Outfits,
Scenarios и Tools. Каждая запись — это просто имя плюс текст ("теги"). Builder
вставляет этот текст в финальный промпт, куда бы вы ни поместили эту запись.

Подпапки — ТОЛЬКО для просмотра. Перемещение записи в папку или организация
библиотеки в "Anime & Cartoon" / "Casual Clothes" и т.д. совсем не влияет на
поиск, на выпадающие списки Builder или на привязку LoRA — имя записи всё равно
остаётся единственным идентификатором во всём приложении. Кликните правой кнопкой
в списке для опций папок (New folder, Move to, rename, delete) — клик на пустом месте
тоже предлагает "New folder", но не "Move to" (нечего перемещать).

Canonical Outfits — это специальная, автоматически управляемая папка: outfits,
которые вы отметили как "канонический" вид персонажа, автоматически там появляются,
и вы не можете вручную переместить туда обычный outfit.

Каждая запись может содержать: референсное изображение (перетащите файл или
кликните Browse), URL источника (для кредита или переадресации оригинальной модели)
и привязанный LoRA (см. "LoRA Manager" ниже, что это делает)."""),

        "tools_category": ("Категория Tools", """\
Tools — это записи библиотеки, которые обычно НЕ имеют реального текста промпта —
их единственная причина существования — привязанный LoRA (фиксер анатомии, детализер
рук, LoRA резкости, или что-то, что Stable Diffusion не может сделать без него).
В отличие от всех остальных категорий, Tool можно сохранить совсем без тегов.

Если Tool ВСЕ ЖЕ имеет короткий тег (например, "@fixedanatomy"), вы можете отметить
"Force this tool's tag to the very start of the prompt" в редакторе Library — тогда
этот тег будет всегда в самом начале собранного промпта, перед Style/Characters/Scenario,
независимо от того, как вы переупорядочили всё остальное через "Block order...".
Tools без этого флага просто стоят там, где "Tools" находится в вашем блоке, как
любая другая секция.

В Builder секция Tools начинается закрытой — кликните её открыть с помощью
"▸ Tools" когда хотите посмотреть или изменить её содержимое."""),

        "lora_manager": ("Менеджер LoRA", """\
Каждый активный Style, Character, Outfit и Tool, у которого есть привязанный LoRA
в Library, автоматически попадает в LoRA Manager, помеченный [A] (automatic).
Вы также можете добавить LoRA вручную через "+ Add LoRA", помеченный [M] (manual) —
полезно для одноразового LoRA, который вы не хотите постоянно привязывать к записи.

Секция LoRA Manager по умолчанию развёрнута, но её можно свернуть (кликните
"▾ LoRA") — как только ваши автопривязанные LoRA установлены как надо, обычно
нет причины смотреть на список, пока вы работаете с Characters/Scenario.
Ваши слоты и силы сохраняются между сеансами.

Перед каждым "🎨 Generate in ComfyUI" имя каждого активного LoRA проверяется
против живого списка LoRA в ComfyUI — недостающий файл будет поймана прямо здесь,
перед отправкой, вместо того чтобы молча пропуститься во время генерации."""),

        "comfyui": ("Подключение к ComfyUI", """\
Прямая генерация совсем опциональна — "⚡ Generate prompt and copy" всегда работает
без настройки ComfyUI. Подключение разблокирует "🎨 Generate in ComfyUI" (отправьте
и смотрите генерацию, не покидая PromptForge), секцию Negative prompt, LoRA Manager
и очередь генерации.

Настройка: установите пакет PromptForge Connection custom node в ComfyUI/custom_nodes/,
поместите PromptForge Connector node куда-то в ваш ComfyUI граф, затем отметьте
"ComfyUI connected?" в ComfyUI панели Builder.

ВАЖНО — генерация ВСЕГДА нацелена на ПОСЛЕДНЮЮ АКТИВНУЮ вкладку workflow в браузере.
PromptForge не знает "какой workflow вы имели в виду": она просит bridge текущий
ComfyUI граф и отправляет туда. Если у вас открыто два workflow и вы кликнули на
другую вкладку просто чтобы взглянуть, ваша следующая генерация пойдёт ТУДА, LoRA
включены. Это верно даже если вы закроете вкладку, закроете браузер целиком или
убьёте процесс браузера — ComfyUI продолжит использовать последний активный workflow.
Это значит, что вы можете освободить оперативку вкладки браузера, как только подтвердили
нужный workflow, генерация при этом не пострадает.

Фреймы live preview полностью зависят от настройки ComfyUI Settings → Comfy →
Execution → Live preview method — если там "none", фреймы не придут, это не то,
что PromptForge контролирует."""),

        "queue": ("Очередь генерации", """\
Клик "🎨 Generate in ComfyUI" ВСЕГДА успешен сразу — он добавляет ваш текущий
промпт, seed, разрешение и снимок LoRA в очередь, вместо отказа если что-то уже
генерируется. ВСЁ про этот клик (включая какие LoRA и силы активны прямо сейчас)
замораживается в записи очереди — изменение силы LoRA потом влияет только на
БУДУЩИЕ клики, никогда на уже поставленное в очередь.

Только один job работает с ComfyUI в раз; предметы очереди ждут своей очереди
и стартуют автоматически как каждый закончится. "⏹ Stop" отменяет только текущий,
затем следующий в очереди стартует автоматически — он ничего не трогает в ожидании.
"🗑 Clear queue" удаляет всё ещё ОЖИДАЮЩЕЕ, но никогда текущий (совпадает как ComfyUI
собственный UI очереди ведёт себя) — используйте Stop для того конкретно.

Маленький "📋 N queued" счётчик рядом с Generate — это чтобы быстрая серия кликов
имела видимое подтверждение что они приземлились, вместо гадания приземлилось ли что-то."""),

        "history_gallery": ("История и Галерея", """\
Каждый промпт что вы генерируете, автоматически сохраняется в History со звёздочкой
и одноклик восстановлением в Builder.

Когда ComfyUI подключена, записи History также содержат какие LoRA (и с какой силой)
были активны для этой конкретной генерации, плюс кнопка "Open image" чтобы прыгнуть
прямо на результат — используя точно ту же логику "последняя известная ссылка" как
собственная иконка лупы Галереи. Если базовый файл с тех пор был перемещён, переименован
или удалён в собственной папке output ComfyUI, это то, что PromptForge не может восстановить;
нет кэшированного thumbnail как fallback по дизайну.

Вкладка Gallery показывает каждое изображение сгенерированное через ComfyUI В ЭТОМ
сеансе как thumbnail — наведитесь чтобы показать его в файловом менеджере, кликните
чтобы открыть полноразмерно."""),

        "known_issues": ("Известные проблемы", """\
Переключение темы не всегда полностью перекрашивает каждый виджет сразу — несколько
могут хранить старые цвета пока вы не перезагрузите приложение. Чисто косметическое,
ничего не потеряно.

Переключение "ComfyUI connected?" пока приложение в маленьком/не-максимизированном
окне может иногда вызвать зависание UI или крах, в зависимости от вашего разрешения
монитора и текущего размера окна. Если это произойдёт, максимизируйте окно перед
отметкой галочки."""),
    },
    "zh": {
        "quick_start": ("快速开始", """\
欢迎！这是第一次用你没有自己构建的库打开 PromptForge 时实际需要发生的顺序。

1. 转到 Library 标签页。点击左上角的 Styles、Characters、Outfits、Scenarios 和 Tools，
   并查看几个条目 — 只是为了在做任何其他事情之前感受一下这个库中实际包含的内容。
   如果一切都是空的，说明你还没有将 PromptForge 指向填充有内容的 prompt_forge_data/ 
   文件夹（或者你是从头开始的 — 见下面的"Library & Subfolders"了解条目如何工作）。

2. 转到 Builder 标签页。选择一个 Style，添加至少一个 Character（以及他们的 Outfit），
   可选地添加一个 Scenario。点击"⚡ Generate prompt and copy" — 这无需任何设置、
   不需要 ComfyUI，只是生成可以粘贴到任何地方的文本。

3. 如果你想让 PromptForge 直接为你生成图像（而不是粘贴提示词到别处），
   请参阅下面的"Connecting to ComfyUI" — 这是一个单独的、可选的步骤，有自己的一次性设置。

4. （可选，仅当你为这个库下载了 LoRA 文件时）一旦 ComfyUI 连接，
   返回 Library 标签页并点击"🔍 Check LoRA dependencies"以确认库期望的每个 LoRA 
   实际上都在 ComfyUI 能找到的地方。这可以在你开始生成数十个角色之前捕捉到
   "我真的下载了所有东西吗？"的问题，而不是之后在某个结果上看到混乱。

这就是整个循环。本指南中的其他一切都是其中某一部分的细节。"""),

        "library": ("库和子文件夹", """\
Library 标签页包含所有可重用的内容：Styles、Characters、Outfits、Scenarios 和 Tools。
每个条目只是一个名称加上一些文本（其"标签"）— Builder 将该文本粘贴到最终提示词中的任何位置。

子文件夹纯粹用于浏览。将条目拖到文件夹中，或将你的库组织成"Anime & Cartoon"/"Casual Clothes"等，
对搜索、Builder 的下拉菜单或 LoRA 的绑定没有任何影响 — 条目的名称仍然是在应用的其他地方
标识它的唯一东西。右键单击列表中的任何位置以获取文件夹选项（New folder、Move to...、
rename、delete）— 右键单击空白处仍然提供"New folder"，但不提供"Move to..."（没有选中任何东西来移动）。

Canonical Outfits 是一个特殊的、自动管理的文件夹：你标记为角色"canon"外观的服装会自动
被归档在那里，你无法手动将普通服装拖入其中。

每个条目可以选择包含：参考图像（将文件拖到编辑器上，或单击浏览）、源 URL
（用于指定或重定位原始模型）以及绑定的 LoRA（见下面的"LoRA Manager"了解它实际上做什么）。"""),

        "tools_category": ("Tools 类别", """\
Tools 是库条目，通常没有真正的提示词文本 — 它们存在的唯一原因是绑定的 LoRA
（解剖学修复器、手部细节器、锐度 LoRA，任何 Stable Diffusion 实际上无法做到的事情）。
与其他每个类别不同，Tool 可以以完全空的标签保存。

如果 Tool 确实有一个简短的标签（某些工作流用"@fixedanatomy"之类的东西触发特定的 LoRA 行为），
你可以在 Library 编辑器中标记它"Force this tool's tag to the very start of the prompt" —
该标签随后总是会在组装的提示词的最开始，在 Style/Characters/Scenario 之前，无论你如何通过
"Block order..."重新排序其他所有内容。没有该标志的 Tools 只是坐在你的块顺序中"Tools"落在的地方，
就像任何其他部分一样。

在 Builder 中，Tools 部分开始是折叠的 — 当你实际想查看或更改其内容时，用"▸ Tools"点击打开它。"""),

        "lora_manager": ("LoRA 管理器", """\
Library 中每个绑定了 LoRA 的活跃 Style、Character、Outfit 和 Tool 都自动进入 LoRA 管理器，
标记为 [A]（自动）。你也可以用"+ Add LoRA"手动添加 LoRA，标记为 [M]（手动）—
对于你不想永久绑定到库条目的一次性 LoRA 很有用。

LoRA 管理器部分默认展开，但可以折叠（单击"▾ LoRA"折起）—
一旦你的自动绑定 LoRA 设置成你想要的样子，通常就没有理由在处理 Characters/Scenario 时一直盯着列表。
你的插槽和强度在会话之间持续存在。

在每个"🎨 Generate in ComfyUI"之前，每个活跃插槽的 LoRA 名称都会针对 ComfyUI 自己的实时 LoRA 列表进行检查 —
缺失的文件在这里被捕捉，在提交之前，而不是在生成过程中被静默跳过。"""),

        "comfyui": ("连接到 ComfyUI", """\
直接生成完全是可选的 — "⚡ Generate prompt and copy"总是无需任何 ComfyUI 设置而工作。
连接解锁"🎨 Generate in ComfyUI"（提交并观看它生成，无需离开 PromptForge）、
Negative prompt 部分、LoRA 管理器和生成队列。

设置：将 PromptForge Connection 自定义节点包安装到 ComfyUI/custom_nodes/，
在 ComfyUI 图中的某处放置一个 PromptForge Connector 节点，然后在 Builder 的 ComfyUI 面板中
勾选"ComfyUI connected?"。

重要 — 生成总是针对你浏览器中的最后活跃工作流标签页。PromptForge 没有"你指的是哪个工作流"的概念：
它向桥询问在浏览器中最近活跃的 ComfyUI 图，然后提交到那里。
如果你打开了两个工作流并点击到不同的标签页只是看一眼，你的下一个生成就会去那里，LoRA 包括在内。
即使你关闭浏览器标签页、完全关闭浏览器或在之后杀死浏览器进程，这也成立 —
ComfyUI 会继续使用最后活跃的工作流。这也意味着一旦你确认了正确的工作流处于活跃状态，
你可以释放浏览器标签页使用的 RAM，而不会影响生成。

实时预览帧完全取决于 ComfyUI 自己的 Settings → Comfy → Execution → Live preview method 设置 —
如果设置为"none"，就不会有帧到达，这不是 PromptForge 控制的东西。"""),

        "queue": ("生成队列", """\
点击"🎨 Generate in ComfyUI"总是立即成功 — 它将你当前的提示词、种子、分辨率和 LoRA 快照
添加到队列中，而不是在已有东西生成时拒绝。关于该点击的所有内容（包括哪些 LoRA 和强度在那时是活跃的）
都被冻结到该队列条目中 — 之后改变 LoRA 强度只影响未来的点击，永远不会影响已经排队的。

一次只有一个任务与 ComfyUI 一起运行；排队的项目等待轮到它们，并在每个完成时自动开始。
"⏹ Stop"只取消当前正在运行的，然后下一个排队项目自动开始 —
它永远不会触及仍在等待的任何东西。"🗑 Clear queue"删除仍然在等待中的所有内容，
但永远不是已经生成的那个（符合 ComfyUI 自己的内置队列 UI 的行为）—
为那个具体的使用 Stop。

"Generate"旁边的小"📋 N queued"计数器存在的目的是，快速的一连串点击有可见的确认他们实际上着陆了，
而不是想知道是否有什么发生。"""),

        "history_gallery": ("历史和画廊", """\
你生成的每个提示词都自动保存到 History，带有一个星标/收藏夹和一键恢复到 Builder。

当 ComfyUI 连接时，History 条目还包含该特定生成时哪些 LoRA（以及什么强度）处于活跃状态，
加上一个"Open image"按钮直接跳到结果 — 使用与 Gallery 自己的放大镜图标完全相同的
"最后已知链接"逻辑。如果底层文件自那时以来在 ComfyUI 自己的输出文件夹中被移动、重命名或删除，
这不是 PromptForge 可以恢复的东西；根据设计，没有缓存的缩略图作为后备。

Gallery 标签页显示在此会话中通过 ComfyUI 生成的每个图像作为缩略图 —
悬停以在文件浏览器中显示它，点击以全尺寸打开它。"""),

        "known_issues": ("已知问题", """\
主题切换不总是立即完全重新着色每个小部件 — 一些可能在你重启应用前保留其旧颜色。
纯粹是外观问题，没有丢失任何东西。

在应用位于小/未最大化窗口时切换"ComfyUI connected?"可能偶尔导致 UI 冻结或崩溃，
取决于你的显示分辨率和窗口的当前大小。如果发生这种情况，在勾选该框之前最大化窗口。"""),
    },
    "ja": {
        "quick_start": ("クイックスタート", """\
ようこそ！これは、自分で構築していないライブラリで初めて PromptForge を開くときに
実際に起こる必要がある順序です。

1. Library タブに移動します。左上の Styles、Characters、Outfits、Scenarios、
   Tools をクリックして、いくつかのエントリを見てください — 何か他にすることの前に、
   このライブラリに実際に何が含まれているかを感じるためだけです。
   すべてが空の場合、PromptForge をまだ populate された prompt_forge_data/ 
   フォルダに指していないか（またはゼロから開始しています — 
   エントリがどのように機能するかについては下の「Library & Subfolders」を参照）。

2. Builder タブに移動します。Style を選択し、少なくとも 1 つの Character（および彼らの Outfit）を追加し、
   オプションで Scenario を追加します。「⚡ Generate prompt and copy」をクリックします — 
   これはセットアップなしで、ComfyUI は不要で、単にどこにでも貼り付けられるテキストを生成します。

3. PromptForge に直接イメージを生成させたい場合（プロンプトを他の場所に貼り付ける代わりに）、
   下の「Connecting to ComfyUI」を参照してください — これは別の、オプションのステップで、
   独自の 1 回限りのセットアップがあります。

4. （オプション、このライブラリ用に LoRA ファイルをダウンロードした場合のみ）
   ComfyUI が接続されたら、Library タブに戻り、「🔍 Check LoRA dependencies」をクリックして、
   ライブラリが期待するすべての LoRA が ComfyUI が見つけられる場所に実際にあることを確認します。
   これは数十のキャラクターを生成し始めた後ではなく、その前に「本当にすべてをダウンロードしたか？」
   をキャッチします。

これが全体のループです。このガイドの他のすべては、その一部の細節です。"""),

        "library": ("ライブラリとサブフォルダ", """\
Library タブには、すべての再利用可能なもの、つまり Styles、Characters、Outfits、
Scenarios、Tools が含まれています。各エントリは単なる名前とテキスト（「タグ」）です — 
Builder はそのテキストを最終プロンプトにあなたがそのエントリを配置する場所に貼り付けます。

サブフォルダは閲覧専用です。エントリをフォルダにドラッグしたり、ライブラリを
「Anime & Cartoon」/「Casual Clothes」などに整理したりすることは、検索、Builder の
ドロップダウン、または LoRA がバインドされている内容に一切影響しません — エントリの
名前は、アプリ全体で他の場所で識別される唯一のものです。
リストのどこかを右クリックしてフォルダオプション（New folder、Move to...、
rename、delete）を取得します — 空白をクリックすると「New folder」が提供されますが、
「Move to...」は提供されません（移動するものが選択されていません）。

Canonical Outfits は特殊な、自動管理フォルダです。キャラクターの「canonical」ルックアスとしてマークした
衣装は自動的にそこに提出され、普通の衣装を手動でそこにドラッグすることはできません。

各エントリはオプションで次のものを含めることができます：参照画像
（編集者にファイルをドラッグするか、参照をクリックします）、
ソース URL（元のモデルをクレジットまたはリダイレクトするため）、
およびバインドされた LoRA（それが実際に何をするかについては下の「LoRA Manager」参照）。"""),

        "tools_category": ("Tools カテゴリー", """\
Tools は通常、実際のプロンプトテキストを持たないライブラリエントリです — それが存在する唯一の理由は
バインドされた LoRA（解剖学フィクサー、手詳細記述子、シャープネス LoRA、
Stable Diffusion が実際に行うことができないもの）です。他のすべてのカテゴリーとは異なり、
Tool は完全に空のタグで保存できます。

Tool が実際に短いタグを持つ場合（一部のワークフローは「@fixedanatomy」のような
特定の LoRA 動作をトリガーします）、Library エディターで
「Force this tool's tag to the very start of the prompt」をマークできます — 
そのタグはその後、「Block order...」で他のすべてを再度配列する方法に関係なく、
組み立てられたプロンプトの最初に、Style/Characters/Scenario の前に常に出現します。
そのフラグなしの Tools は、他のセクション同様に、ブロック順で「Tools」が落ちる場所に座ります。

Builder では、Tools セクションは折りたたまれた状態で開始します — 
実際にそれを見たり、その内容を変更したりしたい場合は、「▸ Tools」で開いてクリックします。"""),

        "lora_manager": ("LoRA マネージャー", """\
Library で LoRA がバインドされたすべてのアクティブな Style、Character、Outfit、および Tool は
自動的に LoRA Manager に引き込まれ、[A]（自動）とタグされます。「+ Add LoRA」で
LoRA を手動で追加することもでき、[M]（手動）とタグされます — 
ライブラリエントリに永続的にバインドしたくない 1 回限りの LoRA に役立ちます。

LoRA Manager セクションはデフォルトで展開されていますが、折りたたむことができます
（「▾ LoRA」をクリックして折りたたみます）— 自動バインドされた LoRA が希望の方法で
設定されたら、Characters/Scenario で作業中にリストを見続ける理由は通常ありません。
スロットと強度はセッション間で保持されます。

すべての「🎨 Generate in ComfyUI」の前に、すべてのアクティブスロットの LoRA 名は
ComfyUI 自体のライブ LoRA リストに対してチェックされます — 
生成中に静かにスキップされるのではなく、提出される前にここで欠落ファイルがキャッチされます。"""),

        "comfyui": ("ComfyUI への接続", """\
直接生成は完全にオプションです — 「⚡ Generate prompt and copy」は常に ComfyUI セットアップなしで動作します。
接続すると、「🎨 Generate in ComfyUI」（送信して PromptForge を離さずに生成を見ます）、
Negative prompt セクション、LoRA Manager、および生成キューがアンロックされます。

セットアップ：PromptForge Connection カスタムノードパッケージを ComfyUI/custom_nodes/ にインストールし、
ComfyUI グラフの どこかに PromptForge Connector ノードを配置してから、
Builder の ComfyUI パネルの「ComfyUI connected?」をチェックします。

重要 — 生成は常にブラウザーで最後にアクティブなワークフロータブをターゲットにします。
PromptForge には「どのワークフローを意味したか」の概念がありません。
ブリッジにブラウザーで最近アクティブだった ComfyUI グラフを質問し、そこに送信します。
2 つのワークフローが開かれており、一見するためだけに別のタブをクリックした場合、
次の生成はそこに行き、LoRA が含まれます。これは、ブラウザータブを閉じたり、
ブラウザーを完全に閉じたり、その後ブラウザープロセスを強制終了した場合でも適用されます — 
ComfyUI は最後にアクティブなワークフローを使い続けます。
これはまた、正しいワークフローがアクティブであることを確認したら、ブラウザータブが使用する RAM を
解放でき、生成に影響を与えないことを意味します。

ライブプレビューフレームは、ComfyUI 自体の Settings → Comfy → Execution → 
Live preview method 設定に完全に依存しています — 「none」に設定されている場合、
フレームは到着せず、これは PromptForge が制御していません。"""),

        "queue": ("生成キュー", """\
「🎨 Generate in ComfyUI」をクリックすると、常に直ちに成功します — 
現在のプロンプト、シード、解像度、および LoRA スナップショットをキューに追加します。
何か生成中の場合は拒否せず、キューに追加します。
そのクリックに関するすべてのもの（どの LoRA と強度がその時点でアクティブか含む）
がキューエントリに固定されます — その後に LoRA 強度を変更すると、
既にキューに入れられたもの、決して将来のクリックのみが影響を受けます。

一度に ComfyUI で正確に 1 つのジョブが実行されます。
キューに入れられたアイテムは順番を待ち、各アイテムが完了すると自動的に開始されます。
「⏹ Stop」は現在実行中のもののみをキャンセルし、
次のキューに入れられたアイテムは自動的に開始されます — 待機中のものには一切触れません。
「🗑 Clear queue」は待機中のすべてを削除しますが、既に生成中のものは削除しません
（ComfyUI 自体の組み込みキュー UI がどのように動作するかと一致します）— 
その 1 つについては Stop を使用します。

「Generate」の横にある小さな「📋 N queued」カウンター は、
クリックの急速な一連が実際に着地したという可視確認があるためです。
何かが起こったかどうかを疑問に思うのではなく。"""),

        "history_gallery": ("履歴とギャラリー", """\
生成するすべてのプロンプトは自動的に History に保存され、スター/お気に入りと
ワンクリック復元が Builder に戻ります。

ComfyUI が接続されている場合、History エントリは、
その特定の生成に対してアクティブだった LoRA（および強度）も含み、
さらに結果に直接ジャンプするための「Open image」ボタンがあります — 
Gallery 自体の虫眼鏡アイコンとまったく同じ「最後の既知リンク」ロジックを使用します。
基になるファイルがその後 ComfyUI 自体の出力フォルダで移動、名前変更、
または削除された場合、これは PromptForge が回復できることではありません。
設計上、フォールバックとしてキャッシュされたサムネイルはありません。

Gallery タブは、このセッションで ComfyUI を通じて生成されたすべてのイメージを
サムネイルとして表示します — ホバーしてファイルエクスプローラーで表示し、
クリックしてフルサイズで開きます。"""),

        "known_issues": ("既知の問題", """\
テーマトグルは常に即座にすべてのウィジェットを完全に再着色するわけではありません — 
いくつかは、アプリを再起動するまで古い色を保つことができます。
純粋に美学的で、何も失われていません。

アプリが小/非最大化ウィンドウにあるときに「ComfyUI connected?」をトグルすると、
ディスプレイの解像度とウィンドウの現在のサイズに応じて、
UI フリーズまたはクラッシュが時々発生する可能性があります。
これが発生した場合、そのボックスをチェックする前にウィンドウを最大化します。"""),
    },
}

for _lang in GUIDE_LANGUAGES:
    if _lang in ("en", "ru", "zh", "ja"):
        continue
    GUIDE_CONTENT[_lang] = {
        key: _guide_pending(_lang, title, body)
        for key, (title, body) in GUIDE_CONTENT["en"].items()
    }

# Section order for the guide's left-hand navigation list — GUIDE_CONTENT
# is keyed by language, but every language shares this same section order
# (a dict literal's insertion order isn't something to rely on after the
# placeholder-generation loop above runs, hence a separate explicit list).
GUIDE_SECTION_ORDER = [
    "quick_start", "library", "tools_category", "comfyui",
    "lora_manager", "queue", "history_gallery", "known_issues",
]


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
        self.CATEGORIES = ["styles", "scenarios", "characters", "outfits", "tools"]
        self.TEMPLATES_FILE = os.path.join(self.DATA_DIR, "_templates.json")
        self.HISTORY_FILE = os.path.join(self.DATA_DIR, "_history.json")
        self.SETTINGS_FILE = os.path.join(self.DATA_DIR, "_settings.json")
        self.FOLDERS_FILE = os.path.join(self.DATA_DIR, LIBRARY_FOLDERS_FILE_NAME)
        self.init_folders()

        # Settings (theme, etc.)
        self.settings = self.load_json(self.SETTINGS_FILE, {"theme": "dark"})
        self.theme_name = self.settings.get("theme", "dark")
        self.colors = THEMES[self.theme_name]
        # Height (px) of the Library image preview/drop zone. Persisted and
        # shared across all four categories (styles/scenarios/characters/
        # outfits) — one slider controls them all.
        #
        # Clamped defensively on load: these values only ever come from
        # the slider (already clamped to [MIN_PERCENT, MAX_PERCENT] in
        # set_percent()) or this same default, so a value outside that
        # range here would mean a corrupted/hand-edited settings.json —
        # re-clamping rather than trusting the file keeps a bad value
        # from compounding into more layout/resize work than the slider
        # itself would ever produce.
        self.lib_image_zone_percent = max(ImageDropZone.MIN_PERCENT, min(ImageDropZone.MAX_PERCENT,
            float(self.settings.get("lib_image_zone_percent", ImageDropZone.DEFAULT_PERCENT))))
        self._image_zone_save_after_id = None
        # Height (%) of the ComfyUI "Latest image" result viewer in the
        # Forge/Builder tab. Persisted the same way as the Library zone.
        self.comfy_result_zone_percent = max(ResultImageViewer.MIN_PERCENT, min(ResultImageViewer.MAX_PERCENT,
            float(self.settings.get("comfy_result_zone_percent", 55))))
        self._comfy_result_zone_save_after_id = None
        # Rolling state for the cascade circuit-breaker in
        # _resize_comfy_result_zone() — see that method's docstring.
        self._comfy_zone_cascade_history = []
        self._comfy_zone_last_applied = []

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
        # id (from add_to_history's return value) of the history entry
        # created for the in-flight job — set right after a successful
        # submit_prompt() (see add_comfy_history_entry), cleared once the
        # job ends. Lets _attach_image_to_history_entry() update exactly
        # that entry once the image is ready, with no text matching.
        self._comfy_current_history_id = None
        self._comfy_stopping = False           # True once Stop has been clicked, until the job actually ends

        # ---- Local generation queue (Task: ComfyUI generation queue) ----
        # comfy_busy stays a pure status flag — "ComfyUI is generating
        # something right now" — and is no longer a gate that refuses new
        # clicks. Every click on "🎨 Generate in ComfyUI" snapshots all of
        # its parameters immediately (on the main thread, in
        # on_generate_in_comfy_clicked) and appends one dict to this list;
        # _maybe_start_next_queued_generation() pops index 0 and hands it
        # to _start_comfy_generation() whenever ComfyUI is free. Exactly
        # one job is ever in flight with ComfyUI at a time — this is a
        # queue the *app* manages locally, not something the app tells
        # ComfyUI's own server-side queue to juggle in parallel, which
        # would make "which job's live preview is this?" ambiguous (see
        # the queue feature discussion).
        #
        # Each queued item is a dict:
        #   {"prompt_text": str, "seed": int, "width": int, "height": int,
        #    "negative_text": str, "lora_slots_snapshot": list,
        #    "history_id": str}
        # — everything _start_comfy_generation needs to actually submit,
        # frozen at the moment the user clicked, plus the history entry id
        # already created for it (see add_comfy_history_entry) so there is
        # nothing left to look up or match by the time it's this item's
        # turn to run.
        self._comfy_queue: list = []
        # Debounce-only: blocks the button for COMFY_QUEUE_DEBOUNCE_MS after
        # each click so a panicked double/triple/500x click doesn't queue
        # the same generation that many times. This is independent of
        # comfy_busy — the button stays clickable (to keep adding to the
        # queue) while a generation is in flight; this timer only guards
        # against rapid repeat clicks of the SAME click.
        self._comfy_queue_debounce_until = 0.0
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
        self.active_tools = []  # list of dicts: {frame, tool_var, tool_combo, idx_label}
        self.custom_active_tools = []  # Custom Template's own Tools slots: {frame, tool_var}

        # Order of prompt assembly blocks: list of block keys
        # available blocks: "style", "characters", "scenario", "tools"
        self.block_order = ["style", "characters", "scenario", "tools"]
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

        # ---- Library virtual folders state ----
        # Per-category {entry_name: "folder/path"} maps, loaded from
        # _folders.json. Purely a UI/organization layer — never consulted
        # by get_file_list/Builder/history/LoRA logic, only by the
        # Library tab's tree rendering and move/search behavior.
        self._folder_maps = self.load_json(self.FOLDERS_FILE, {})
        for _cat in self.CATEGORIES:
            self._folder_maps.setdefault(_cat, {})
        # Folders created via "New folder" before anything has been filed
        # into them yet. Not persisted on their own — purely so a freshly
        # created empty folder doesn't disappear from the tree until the
        # user drops something into it (list_all_folders only derives
        # paths from entries that actually exist in _folder_maps). Reset
        # on every app restart, same lifecycle as e.g. gallery_entries.
        self._empty_folders = {cat: set() for cat in self.CATEGORIES}
        # Per-category set of folder paths the user has manually expanded.
        # A category not visited yet simply has no entry here, which
        # _is_folder_expanded() treats as "collapsed" (the default state
        # the moment a new subfolder is created, or the first time the
        # user opens a category — see the user-facing spec).
        self._expanded_folders = {cat: set() for cat in self.CATEGORIES}
        # Drag state for mouse-based "press entry -> drop onto folder".
        self._lib_drag_item = None
        self._lib_drag_started = False
        # Snapshot of the full multi-selection taken at press-time, before
        # ttk's native click handling could collapse it to one row — see
        # _on_lib_tree_press for why tree.selection() alone isn't enough.
        self._lib_drag_snapshot = None
        # Row under the most recent click — recorded on ButtonPress before
        # Tk fires <<TreeviewOpen>>/<<TreeviewClose>>, since tree.focus()
        # is not reliable for "which row was just toggled" (see
        # _on_library_folder_toggled).
        self._lib_last_toggled_iid = None

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
        """Returns {"source_url": str|None, "lora": str|None,
        "force_first": bool} for this entry. Missing/corrupt sidecar ->
        no link, no binding, force_first=False.

        force_first only has any effect for the "tools" category (see
        _build_tools_block) — a Tool entry with this set and a non-empty
        tags/content is pulled out of the normal block_order position and
        always placed at the very start of the assembled prompt, ahead of
        Style/Characters/Scenario, so a tag like "@fixedanatomy" reaches
        the model before anything else can be conditioned around it. It's
        stored generically here rather than gated to "tools" at the
        sidecar level, same as source_url/lora already are, since nothing
        stops some future category from wanting the same knob."""
        empty = {"source_url": None, "lora": None, "force_first": False}
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
                "force_first": bool(data.get("force_first", False)),
            }
        except Exception:
            return empty

    def save_library_meta(self, category, name, source_url=None, lora=None, force_first=False):
        """Writes the sidecar JSON, or removes it if every field ends up
        empty/default (so entries with nothing special don't grow a
        stray file)."""
        if not name:
            return
        if not source_url and not lora and not force_first:
            self.delete_library_meta(category, name)
            return
        path = self.library_meta_path(category, name)
        try:
            cat_dir = os.path.join(self.DATA_DIR, category)
            if not os.path.exists(cat_dir):
                os.makedirs(cat_dir)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"source_url": source_url or None, "lora": lora or None,
                           "force_first": bool(force_first)}, f, ensure_ascii=False, indent=2)
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

    # ==========================================================
    #         LIBRARY VIRTUAL FOLDERS (subfolder organization)
    # ==========================================================
    # Folders here are a pure UI/organization layer on top of the existing
    # flat-per-category storage. An entry's name stays the single, globally
    # -unique-within-its-category identifier it always was — get_file_list,
    # the Builder's dropdowns, history, and the LoRA auto-fill logic never
    # need to know folders exist at all. Only the Library tab's tree view,
    # its search box, and its move/organize actions consult this map.
    #
    # Persisted as {category: {entry_name: "Folder/Sub Folder"}} in
    # self.FOLDERS_FILE. A missing key simply means "lives at the root of
    # the category" — there is no need to ever write an explicit "" value.
    def save_folder_map(self):
        self.save_json(self.FOLDERS_FILE, self._folder_maps)

    def get_entry_folder(self, category, name):
        """Returns the folder path string an entry is filed under, or ""
        if it lives at the root of the category."""
        return self._folder_maps.get(category, {}).get(name, "") or ""

    def set_entry_folder(self, category, name, folder_path):
        """Files `name` under `folder_path` ("" = root of the category).
        Does not touch any file on disk — folders are virtual."""
        cat_map = self._folder_maps.setdefault(category, {})
        folder_path = (folder_path or "").strip("/")
        if folder_path:
            cat_map[name] = folder_path
        else:
            cat_map.pop(name, None)
        self.save_folder_map()

    def remove_entry_folder_entry(self, category, name):
        """Drops any folder assignment for `name` (used when an entry is
        deleted, so the manifest doesn't accumulate references to files
        that no longer exist)."""
        cat_map = self._folder_maps.get(category)
        if cat_map and name in cat_map:
            del cat_map[name]
            self.save_folder_map()

    def rename_entry_folder_entry(self, category, old_name, new_name):
        """Carries an entry's folder assignment over on rename/duplicate,
        mirroring rename_library_image/rename_library_meta above."""
        if not old_name or old_name == new_name:
            return
        cat_map = self._folder_maps.get(category)
        if cat_map and old_name in cat_map:
            cat_map[new_name] = cat_map.pop(old_name)
            self.save_folder_map()

    def list_all_folders(self, category):
        """Returns every distinct folder path used in this category
        (including ancestors of nested paths, even if nothing is filed
        directly in them, and including freshly-created empty folders),
        sorted alphabetically depth-first. Used to populate the
        "Move to..." submenu and the folder picker."""
        paths = set(self._empty_folders.get(category, set()))
        for folder_path in self._folder_maps.get(category, {}).values():
            if not folder_path:
                continue
            parts = folder_path.split(FOLDER_PATH_SEP)
            for depth in range(1, len(parts) + 1):
                paths.add(FOLDER_PATH_SEP.join(parts[:depth]))
        return sorted(paths, key=natural_sort_key)

    def _is_protected_folder(self, category, folder_path):
        """Canonical Outfits (outfits category only) is auto-managed:
        users cannot rename it, delete it, or hand-drop ordinary entries
        into it. Returns True if `folder_path` IS that folder or a path
        nested under it."""
        if category != "outfits":
            return False
        return (folder_path == CANONICAL_OUTFITS_FOLDER
                or folder_path.startswith(CANONICAL_OUTFITS_FOLDER + FOLDER_PATH_SEP))

    def _file_canon_outfit_into_folder(self, char_name, num):
        """Auto-files a canon outfit into the Canonical Outfits folder the
        moment it's created/saved as canon. Called from save_to_library."""
        base = f"{char_name}_Canon_{num}"
        self.set_entry_folder("outfits", base, CANONICAL_OUTFITS_FOLDER)

    def move_entries_to_folder(self, category, names, folder_path):
        """Moves a batch of entries (e.g. a multi-selection) into
        folder_path in one go. Refuses to drop ordinary outfits into the
        protected Canonical Outfits folder, and silently skips canon
        outfits if a non-protected target was requested by mistake (canon
        outfits are only ever moved automatically, never by hand) — see
        is_canon_outfit_name(). Returns the number of entries actually moved.
        """
        moved = 0
        for name in names:
            is_canon = category == "outfits" and self.is_canon_outfit_name(name)
            if is_canon:
                continue  # canon outfits' folder is managed automatically only
            if self._is_protected_folder(category, folder_path):
                continue  # users can't manually file ordinary entries in here
            self.set_entry_folder(category, name, folder_path)
            moved += 1
        return moved

    @staticmethod
    def is_canon_outfit_name(base):
        return "_Canon_" in base

    def create_new_folder(self, category, parent_path, folder_name):
        """Registers a brand-new (initially empty) folder so it shows up
        in the tree immediately, without requiring an entry to be moved
        into it first. Empty folders are remembered for the session via
        self._empty_folders (not persisted standalone — they become
        "real" the moment an entry is filed into them; until then they'd
        otherwise vanish on the next refresh since list_all_folders only
        derives paths from entries that exist)."""
        folder_name = (folder_name or "").strip()
        if not folder_name or FOLDER_PATH_SEP in folder_name:
            return None
        full_path = f"{parent_path}{FOLDER_PATH_SEP}{folder_name}" if parent_path else folder_name
        self._empty_folders.setdefault(category, set()).add(full_path)
        return full_path

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
        # Re-applies tag_configure for lora_ok/lora_candidate/lora_missing
        # with the new theme's colors — otherwise they'd keep showing the
        # PREVIOUS theme's green/yellow/red until something else happens
        # to trigger a refresh.
        if hasattr(self, "tree_library"):
            self.refresh_library_list()

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

        CASCADE CIRCUIT BREAKER (freeze fix): `right` is bound to (not
        frame_comfy_result) specifically to avoid the obvious
        self-referential loop — see the comment at that bind() call. But
        on a short/tightly-constrained column (smaller window — e.g.
        non-native DPI scaling — and/or the progress bar adding extra
        height during generation), the card's required height can still
        end up close enough to `right`'s actual height that changing the
        canvas's height nudges `right`'s rendered size too, which fires
        <Configure> on `right` again on a LATER Tk event-loop tick —
        after this call has already returned and reset
        `_resizing_comfy_zone` in its `finally`. That guard only blocks
        SYNCHRONOUS re-entry; it does nothing against this asynchronous
        chain, which can then ping-pong between two heights forever
        (each pass individually looks legitimate — a >1px change — so
        nothing inside a single pass ever decides to stop), pegging the
        UI thread and freezing the app with no traceback. Two
        independent guards close that gap:
          - a short rolling counter of how many times this method has
            run inside CASCADE_WINDOW_MS; once it's been called more
            times than CASCADE_MAX_CALLS in that window, every call
            after that is a no-op until the window lapses, regardless
            of how legitimate any individual computation looks.
          - skipping apply_panel_height() entirely if the freshly
            computed `available` matches either of the last two values
            actually applied — catches a settled value being re-applied
            for no reason, *and* a 2-cycle oscillation between two
            specific heights, without needing to know which case it is.
        A real, user-driven resize (window resize, maximize, sash drag)
        only ever needs one or two corrective passes to settle, so this
        is generous headroom for legitimate use and a hard stop for a
        runaway loop.
        """
        if not hasattr(self, "comfy_result_zone") or not hasattr(self, "frame_comfy_result"):
            return
        if right_panel_height is None:
            if not hasattr(self, "forge_right_panel"):
                return
            right_panel_height = self.forge_right_panel.winfo_height()
        if right_panel_height <= 1:
            return

        # --- cascade circuit breaker: rolling call-rate cap ---
        CASCADE_WINDOW_MS = 400
        CASCADE_MAX_CALLS = 6
        now_ms = time.monotonic() * 1000.0
        history = getattr(self, "_comfy_zone_cascade_history", None)
        if history is None:
            history = []
            self._comfy_zone_cascade_history = history
        history.append(now_ms)
        cutoff = now_ms - CASCADE_WINDOW_MS
        while history and history[0] < cutoff:
            history.pop(0)
        if len(history) > CASCADE_MAX_CALLS:
            # Almost certainly a feedback loop, not real user activity —
            # bail out without touching anything so it has a chance to
            # settle on its own instead of being kept alive by us.
            return

        # Re-entrancy guard: this method measures real widget geometry via
        # update_idletasks(), which can synchronously dispatch any other
        # pending Tk events (including another <Configure> bound to
        # _on_comfy_panel_resize) before returning. Without this guard, an
        # unexpected event chain could re-enter this same method while the
        # first call is still mid-measurement; the guard makes any such
        # re-entry a harmless no-op instead of a runaway recursive resize.
        # (This alone does NOT stop the slower, asynchronous cascade
        # described above — that's what the call-rate cap above and the
        # repeat-value check below are for.)
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

            recent = getattr(self, "_comfy_zone_last_applied", [])
            if available in recent:
                # Already applied this exact value (or its oscillation
                # partner) very recently — re-applying it again is either
                # a no-op or feeds a 2-cycle; skip either way.
                return
            self.comfy_result_zone.apply_panel_height(available)
            recent.append(available)
            self._comfy_zone_last_applied = recent[-2:]
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

        guide_btn = tk.Label(theme_btn, text="❓ Guide", bg=c["bg"], fg=c["fg_dim"],
                              font=self.small_font, cursor="hand2")
        guide_btn.pack(side="right", padx=(0, 14))
        guide_btn.bind("<Button-1>", lambda e: self.open_guide())
        Tooltip(guide_btn, "Open the in-app guide (F1)", self)
        self.root.bind("<F1>", lambda e: self.open_guide())

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
    #       LEFT-COLUMN SCROLLREGION SUSPEND/RESUME (crash fix)
    # ==========================================================
    def _update_left_scrollregion_now(self):
        """Performs the actual scrollregion recalculation immediately —
        the one expensive bbox("all") geometry scan that every other
        mechanism here exists to avoid running redundantly. Safe to call
        directly (e.g. right after a suspended burst resumes) since it
        doesn't schedule anything itself."""
        self._left_scrollregion_pending = None
        if hasattr(self, "left_canvas"):
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

    def _suspend_left_scrollregion_updates(self):
        """Context manager: use this to wrap any deliberate BURST of
        several pack()/pack_forget() calls on widgets inside the
        scrollable left column (e.g. _on_comfy_check_done toggling 7+
        widgets in one go when ComfyUI connects/disconnects).

        Without this, each individual pack change fires its own
        <Configure> event on left_content, and even with debouncing via
        after_idle, Tk still has to dispatch and partially process every
        one of those events before the debounce can coalesce them — on a
        small/tightly-constrained window, that's exactly the documented
        "tkinter geometry calculation bottleneck" crash/freeze, just
        amplified by however many widgets the burst touches. This
        suspends recalculation entirely for the duration of the `with`
        block (a counter, not a flag, so nested bursts compose safely —
        only the outermost exit actually triggers anything), then
        performs exactly ONE recalculation immediately on exit, after
        every pack change in the burst has already settled.

        Usage:
            with self._suspend_left_scrollregion_updates():
                self.frame_a.pack_forget()
                self.frame_b.pack(...)
                self.frame_c.pack(...)
            # exactly one bbox("all") scan happens here, not three
        """
        app = self

        class _Suspender:
            def __enter__(self):
                app._left_scrollregion_suspended += 1
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                app._left_scrollregion_suspended -= 1
                if app._left_scrollregion_suspended == 0:
                    # Cancel any debounced call that snuck in before this
                    # suspension started (shouldn't normally happen, but
                    # avoids a redundant second recalculation if it did).
                    if app._left_scrollregion_pending is not None:
                        app.root.after_cancel(app._left_scrollregion_pending)
                        app._left_scrollregion_pending = None
                    app._update_left_scrollregion_now()
                return False

        return _Suspender()

    # ==========================================================
    #             GENERIC COLLAPSIBLE SECTION HELPER
    # ==========================================================
    def _make_collapsible_section(self, parent, title, settings_key, default_expanded=True):
        """Builds a header row with a ▾/▸ toggle + title, and returns
        (header_frame, body_frame). The caller packs header_frame once,
        packs whatever content it wants into body_frame, and never has
        to touch body_frame's own pack()/pack_forget() again — toggling
        is handled entirely here.

        Used by Negative prompt, LoRA Manager, and Tools (see the layout
        feedback this responds to: those three stay visually "full" all
        the time even though most of a session never needs to look at
        or touch them again after the first setup — a fixed negative
        prompt, auto-filled LoRA slots, a one-off anatomy-fixer tool).
        One shared implementation rather than three separate ad-hoc
        ones, so toggle behavior/persistence is consistent everywhere
        it's used and only needs fixing in one place if it's ever wrong.

        settings_key namespaces the persisted expand/collapse state in
        self.settings (e.g. "section_collapsed_negative_prompt") — saved
        immediately on toggle, so "I haven't touched this in a month"
        stays collapsed across restarts exactly as left, not reset to
        some default every launch."""
        collapsed = self.settings.get(f"section_collapsed_{settings_key}", not default_expanded)

        header_frame = ttk.Frame(parent)
        toggle_btn = ttk.Button(header_frame, text=("▸" if collapsed else "▾"),
                                 style="Ghost.TButton")
        toggle_btn.pack(side="left")
        ttk.Label(header_frame, text=title, style="TLabel").pack(side="left", padx=(4, 0))

        body_frame = ttk.Frame(parent)
        if not collapsed:
            body_frame.pack(fill="x", pady=(4, 0))

        def toggle():
            now_collapsed = body_frame.winfo_ismapped()
            if now_collapsed:
                body_frame.pack_forget()
                toggle_btn.configure(text="▸")
            else:
                body_frame.pack(fill="x", pady=(4, 0))
                toggle_btn.configure(text="▾")
            self.settings[f"section_collapsed_{settings_key}"] = now_collapsed
            self.save_json(self.SETTINGS_FILE, self.settings)

        toggle_btn.configure(command=toggle)
        return header_frame, body_frame

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

        # The whole left column is wrapped in its own scrollable Canvas —
        # without this, the column had no outer scroll mechanism at all
        # and simply had to fit within whatever height the window
        # happened to have. That was fine by accident while there were
        # only 3 builder sections; adding a 4th (Tools) used up the
        # remaining slack and pushed Negative prompt / ComfyUI /
        # LoRA Manager below the visible area with no way to reach them.
        # left_content below is a plain Frame holding the exact same
        # children as before (Prompt Template, Standard/Custom content,
        # Negative prompt, ComfyUI, LoRA, actions) — nothing about how
        # those are built or parented changes, only that the whole thing
        # now lives inside a canvas that scrolls as a unit.
        # Added to paned BEFORE right, so it stays the left-hand pane —
        # PanedWindow.add() order is left-to-right display order.
        left_outer = ttk.Frame(paned)
        paned.add(left_outer, weight=3)
        left_canvas = tk.Canvas(left_outer, bg=c["bg"], highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_content = ttk.Frame(left_canvas)
        self.left_canvas = left_canvas
        self.left_content = left_content
        # Debounced via after_idle rather than recalculating synchronously
        # on every single <Configure> — a burst of several pack_forget()/
        # pack() calls in one Tk callback (e.g. _on_comfy_check_done
        # toggling 7+ widgets when ComfyUI connects) fires this many times
        # in a row otherwise, each one doing a full bbox("all") geometry
        # scan in the middle of that same callback — a direct
        # amplification of the documented tkinter geometry-calculation
        # crash/freeze. self._left_scrollregion_suspended is a counter
        # (not a bool) so nested suspend calls compose safely; callers
        # doing a deliberate burst of pack changes should wrap them with
        # _suspend_left_scrollregion_updates() (see that method) to
        # guarantee exactly one recalculation after the whole burst
        # settles, rather than relying on debounce alone — debounce still
        # dispatches and handles N events even if it coalesces the
        # expensive part, which isn't free either on a tightly-
        # constrained window.
        self._left_scrollregion_suspended = 0
        self._left_scrollregion_pending = None

        def _schedule_left_scrollregion_update(event=None):
            if self._left_scrollregion_suspended > 0:
                return
            if self._left_scrollregion_pending is not None:
                self.root.after_cancel(self._left_scrollregion_pending)
            self._left_scrollregion_pending = self.root.after_idle(self._update_left_scrollregion_now)

        left_content.bind("<Configure>", _schedule_left_scrollregion_update)
        left_canvas_window = left_canvas.create_window((0, 0), window=left_content, anchor="nw")
        # Keep left_content as wide as the visible canvas, so its
        # children's fill="x" packing still spans the full column width
        # instead of shrinking to its own contents' minimum width.
        left_canvas.bind("<Configure>",
                          lambda e: left_canvas.itemconfigure(left_canvas_window, width=e.width))
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_scroll.pack(side="right", fill="y")

        def _on_left_mousewheel(event):
            # Windows/macOS deliver delta in multiples of 120; Linux
            # delivers raw small deltas via <Button-4>/<Button-5> instead
            # (not handled here — this mirrors what's already standard
            # for this codebase's other scroll areas, none of which
            # special-case Linux either).
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # Bound only while the cursor is actually over this canvas, not
        # via bind_all — so it can never fight with chars_canvas/
        # tools_canvas (the independent inner scroll areas for Characters
        # and Tools) if those pick up their own wheel handling later.
        left_canvas.bind("<Enter>", lambda e: left_canvas.bind_all("<MouseWheel>", _on_left_mousewheel))
        left_canvas.bind("<Leave>", lambda e: left_canvas.unbind_all("<MouseWheel>"))

        left = left_content

        right = ttk.Frame(paned)
        self.forge_right_panel = right
        paned.add(right, weight=2)

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

        # --- Tools (dynamic container) ---
        # Anatomy fixers, hand detailers, and similar "no scene content,
        # just a LoRA (and maybe a short trigger tag)" library entries —
        # see the Tools feature discussion. Structurally a simpler sibling
        # of the Characters section above: one combobox per slot, no
        # outfit sub-selection, since a Tool entry has no second axis to
        # pick. Entries marked "force to start of prompt" in the Library
        # are pulled out of block_order entirely at assembly time (see
        # _build_tools_block) — this section is just where they're picked.
        #
        # Collapsible, defaulting to COLLAPSED (unlike LoRA/Negative
        # prompt, which default to expanded) — see the layout feedback
        # this responds to: once a tool is picked and its LoRA auto-
        # fills, there's usually no reason to keep staring at the list
        # while working on Characters/Scenario. "+ Add tool" and the
        # count live in the ALWAYS-VISIBLE collapsible header itself
        # (not inside the collapsible body), so a first-time user still
        # immediately sees how to add one even though the section starts
        # collapsed.
        self.frame_tools_container = ttk.Frame(self.standard_section)
        self.frame_tools_container.pack(fill="x", pady=6)

        tools_header, tools_body = self._make_collapsible_section(
            self.frame_tools_container, "Tools", "tools", default_expanded=False)
        tools_header.pack(fill="x", pady=(0, 6))
        btn_add_tool = ttk.Button(tools_header, text="＋ Add tool", style="Accent.TButton",
                                   command=self.add_tool_slot)
        btn_add_tool.pack(side="left", padx=(10, 0))
        self.lbl_tools_count = ttk.Label(tools_header, text="0 tools", style="Dim.TLabel")
        self.lbl_tools_count.pack(side="left", padx=12)

        # Fixed, modest height (not fill="both"/expand=True like the
        # Characters canvas above) — Tools is a small, usually-empty-or-
        # few-items optional section (anatomy fixers, detailers; see the
        # Tools feature discussion), not a primary scrolling area someone
        # fills with many entries. Giving it expand=True here was the
        # actual layout bug: it competed with Characters' own
        # expand=True for the same leftover vertical space, which is
        # what pushed Negative prompt / ComfyUI / LoRA Manager off
        # the bottom of the window. It still scrolls internally
        # (tools_scroll below) if someone adds more tools than fit in
        # this height.
        tools_canvas_holder = ttk.Frame(tools_body)
        tools_canvas_holder.pack(fill="x")

        self.tools_canvas = tk.Canvas(tools_canvas_holder, bg=c_bg, highlightthickness=0, height=140)
        tools_scroll = ttk.Scrollbar(tools_canvas_holder, orient="vertical", command=self.tools_canvas.yview)
        self.scroll_tools = ttk.Frame(self.tools_canvas)
        self.scroll_tools.bind("<Configure>",
                                lambda e: self.tools_canvas.configure(scrollregion=self.tools_canvas.bbox("all")))
        self.tools_canvas.create_window((0, 0), window=self.scroll_tools, anchor="nw")
        self.tools_canvas.configure(yscrollcommand=tools_scroll.set)
        self.tools_canvas.pack(side="left", fill="x", expand=True)
        tools_scroll.pack(side="right", fill="y")

        self.placeholder_tools = ttk.Label(self.scroll_tools,
                                            text="No tools added. Click \"＋ Add tool\" (optional — anatomy "
                                                 "fixers, detailers, etc.).",
                                            style="Dim.TLabel")
        self.placeholder_tools.pack(anchor="w", pady=10, padx=4)

        # --- Negative prompt (Standard tab) ---
        # Parented to `left` (not `standard_section`) so it stays visible
        # when the user switches to Custom Templates — same reasoning as
        # the ComfyUI panel below.
        #
        # Visibility (a): negative_text is read ONLY by
        # on_generate_in_comfy_clicked (to snapshot it into a queue item)
        # and patched ONLY into the ComfyUI graph in _start_comfy_
        # generation — it has zero effect on the text that "⚡ Generate
        # prompt and copy" produces. So the WHOLE section is only ever
        # shown while ComfyUI is connected (toggled in
        # _refresh_neg_prompt_visibility, called from the same places
        # that already toggle frame_comfy/frame_lora) — in non-ComfyUI
        # mode it's pure dead space with nothing it actually affects.
        self.frame_neg_prompt = ttk.Frame(left)
        # Not packed yet — _refresh_neg_prompt_visibility() packs it in
        # once comfy_connected is True, alongside frame_comfy/frame_lora.

        # Collapsible (b): once shown, a negative prompt set once and
        # left alone for weeks doesn't need to sit fully expanded taking
        # up space every session — collapsed/expanded state persists
        # across restarts via the shared helper.
        neg_header, neg_body = self._make_collapsible_section(
            self.frame_neg_prompt, "Negative prompt", "negative_prompt", default_expanded=True)
        neg_header.pack(fill="x")
        self.txt_neg_prompt = scrolledtext.ScrolledText(
            neg_body, font=self.mono_font, wrap=tk.WORD,
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
        self.frame_comfy = ttk.LabelFrame(left, text=" ComfyUI ", padding=12)
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
        # Collapsible (see the layout feedback this responds to): auto-
        # filled LoRA slots don't need to sit fully expanded every
        # session once they're set — collapsed/expanded state persists
        # across restarts via the shared helper.
        self.frame_lora = ttk.Frame(left)
        lora_header, lora_body = self._make_collapsible_section(
            self.frame_lora, "⚙️ LoRA", "lora_manager", default_expanded=True)
        lora_header.pack(fill="x")

        # Inner scrollable area: Canvas + Scrollbar + inner frame.
        # Same pattern as Gallery tab (Task 3).
        lora_canvas_frame = ttk.Frame(lora_body)
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
        lora_btn_row = ttk.Frame(lora_body)
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
        #
        # Task: generation queue (bugfix). This used to be a SECOND state
        # of btn_generate_comfy itself (its text/command swapped to
        # "⏹ Stop" while busy) — which meant the only button that could
        # add to the queue was unreachable for the entire duration of
        # whatever was already running, defeating the queue's whole
        # point (you couldn't queue a second item until the first one
        # finished). Stop is now its own separate button, shown next to
        # Generate — not instead of it — only while comfy_busy is True,
        # so Generate stays clickable (keeps adding to the queue) at the
        # same time Stop is available (to cancel whatever's active).
        self.btn_comfy_stop = ttk.Button(self.actions_frame, text="⏹ Stop",
                                          style="Ghost.TButton", command=self.on_comfy_stop_clicked)
        # Not packed yet either — shown/hidden by _show_comfy_stop_button /
        # _restore_comfy_generate_button alongside comfy_busy's lifecycle.
        btn_clear = ttk.Button(self.actions_frame, text="Clear all", style="Ghost.TButton", command=self.clear_forge)
        btn_clear.pack(side="left", padx=(8, 0))

        # Task: generation queue. A second row, shown/hidden in lockstep
        # with btn_generate_comfy (it has no meaning while ComfyUI isn't
        # connected) — a count label that's always visible the moment
        # anything is queued (clicking the same button repeatedly should
        # always visibly confirm "yes, that landed"), and "🗑 Clear queue"
        # for dropping everything still pending (never the one already
        # generating — see clear_comfy_queue's docstring).
        self.frame_comfy_queue_row = ttk.Frame(left)
        self.lbl_comfy_queue_count = ttk.Label(self.frame_comfy_queue_row, text="", style="Dim.TLabel")
        self.lbl_comfy_queue_count.pack(side="left")
        self.btn_comfy_clear_queue = ttk.Button(self.frame_comfy_queue_row, text="🗑 Clear queue",
                                                  style="Ghost.TButton", state="disabled",
                                                  command=self.clear_comfy_queue)
        self.btn_comfy_clear_queue.pack(side="right")

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
        return " → ".join(BLOCK_ORDER_LABELS[k] for k in self.block_order)

    def clear_forge(self):
        if not messagebox.askyesno("Clear", "Reset all selected builder blocks?"):
            return
        self.selected_style.set("None")
        self.selected_scenario.set("None")
        for slot in list(self.active_characters):
            slot["frame"].destroy()
        self.active_characters.clear()
        self.update_chars_placeholder()
        for slot in list(self.active_tools):
            slot["frame"].destroy()
        self.active_tools.clear()
        self.update_tools_placeholder()
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

    # ---- In-app guide (F1 / "❓ Guide") ----
    def open_guide(self):
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("PromptForge Guide")
        dlg.configure(bg=c["bg"])

        top_row = ttk.Frame(dlg)
        top_row.pack(fill="x", padx=14, pady=(14, 8))
        ttk.Label(top_row, text="❓ PromptForge Guide", style="Title.TLabel").pack(side="left")

        lang_var = tk.StringVar(value=self.settings.get("guide_language", "en"))
        lang_combo = ttk.Combobox(top_row, state="readonly", width=14,
                                   values=list(GUIDE_LANGUAGES.values()))
        lang_combo.pack(side="right")
        ttk.Label(top_row, text="Language:", style="TLabel").pack(side="right", padx=(0, 6))
        # Combobox shows display names ("English", "Русский", ...) but
        # everything else here keys off the language code — keep a
        # lookup both ways so picking a display name resolves back to
        # the code GUIDE_CONTENT is actually indexed by.
        code_by_display = {v: k for k, v in GUIDE_LANGUAGES.items()}
        lang_combo.set(GUIDE_LANGUAGES.get(lang_var.get(), "English"))

        body = ttk.Frame(dlg)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        nav_frame = ttk.Frame(body)
        nav_frame.pack(side="left", fill="y", padx=(0, 10))
        section_list = tk.Listbox(nav_frame, bg=c["bg_card"], fg=c["fg"],
                                   selectbackground=c["accent"], selectforeground=c["accent_text"],
                                   relief="flat", borderwidth=0, highlightthickness=0,
                                   width=22, exportselection=False)
        section_list.pack(fill="y", expand=True)

        txt_frame = ttk.Frame(body)
        txt_frame.pack(side="left", fill="both", expand=True)
        guide_txt = scrolledtext.ScrolledText(txt_frame, wrap=tk.WORD, font=self.default_font,
                                               bg=c["bg_input"], fg=c["fg"], relief="flat", borderwidth=0)
        guide_txt.pack(fill="both", expand=True)
        guide_txt.configure(state="disabled")

        def render_section(index):
            lang = lang_var.get()
            content = GUIDE_CONTENT.get(lang, GUIDE_CONTENT["en"])
            section_key = GUIDE_SECTION_ORDER[index]
            title, text = content.get(section_key, GUIDE_CONTENT["en"][section_key])
            guide_txt.configure(state="normal")
            guide_txt.delete("1.0", tk.END)
            guide_txt.insert("1.0", text)
            guide_txt.configure(state="disabled")

        def populate_section_list():
            lang = lang_var.get()
            content = GUIDE_CONTENT.get(lang, GUIDE_CONTENT["en"])
            section_list.delete(0, tk.END)
            for key in GUIDE_SECTION_ORDER:
                title, _ = content.get(key, GUIDE_CONTENT["en"][key])
                section_list.insert(tk.END, title)

        def on_section_select(event=None):
            sel = section_list.curselection()
            if sel:
                render_section(sel[0])

        def on_language_changed(event=None):
            code = code_by_display.get(lang_combo.get(), "en")
            lang_var.set(code)
            self.settings["guide_language"] = code
            self.save_json(self.SETTINGS_FILE, self.settings)
            # Re-populate titles in the new language, but keep whatever
            # section was selected selected — switching language should
            # never silently jump you back to the first section.
            current_sel = section_list.curselection()
            current_index = current_sel[0] if current_sel else 0
            populate_section_list()
            section_list.selection_set(current_index)
            render_section(current_index)

        section_list.bind("<<ListboxSelect>>", on_section_select)
        lang_combo.bind("<<ComboboxSelected>>", on_language_changed)

        populate_section_list()
        section_list.selection_set(0)
        render_section(0)

        ttk.Button(dlg, text="Close", style="Ghost.TButton", command=dlg.destroy).pack(
            fill="x", padx=14, pady=(0, 14))

        self._finalize_dialog(dlg, min_w=720, min_h=520)

    # ---- Block order dialog ----
    def open_order_dialog(self):
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("Prompt block order")
        dlg.configure(bg=c["bg"])
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="Choose the block order from top to bottom:", style="TLabel").pack(anchor="w", padx=14, pady=(14, 6))

        names = BLOCK_ORDER_LABELS
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
            loaded_order = list(self.templates[name])
            # Migration: a template saved before a given block existed
            # (e.g. "tools", added later) won't list it at all — append
            # any such missing-but-known keys to the end rather than
            # silently dropping that whole section out of every prompt
            # built from this template from now on. Preserves the user's
            # original relative order for every block that WAS saved.
            for key in BLOCK_ORDER_LABELS:
                if key not in loaded_order:
                    loaded_order.append(key)
            self.block_order = loaded_order
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
            with self._suspend_left_scrollregion_updates():
                self.tpl_controls_standard.pack_forget()
                self.tpl_controls_custom.pack(fill="x")
                self.standard_section.pack_forget()
                self.custom_section.pack(fill="both", expand=True)
                # Global negative-prompt field is hidden in Custom mode —
                # each custom template has its own field inside custom_section.
                self.frame_neg_prompt.pack_forget()
                # Bugfix: the queue row was never re-packed here, only
                # actions_frame was — leaving it stuck at its OLD position
                # (from whenever ComfyUI was first connected) once
                # actions_frame moved to the end of the pack order below
                # it. Re-pack it right after actions_frame every time,
                # same as the Standard branch does.
                self.frame_comfy_queue_row.pack_forget()
                if self.comfy_connected and self.comfy_enabled.get():
                    self.frame_comfy_queue_row.pack(fill="x", padx=(0, 10), pady=(4, 0))
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
            with self._suspend_left_scrollregion_updates():
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
                self.frame_comfy_queue_row.pack_forget()
                # Only re-shown if ComfyUI is actually connected — see
                # frame_neg_prompt's own comment at creation time for why it
                # has no purpose at all otherwise. Mirrors frame_comfy's own
                # gating right below.
                if self.comfy_connected:
                    self.frame_neg_prompt.pack(fill="x", padx=(0, 10), pady=6)
                self.frame_comfy.pack(fill="x", padx=(0, 10), pady=6)
                # If frame_lora isn't visible yet (e.g. ComfyUI just connected
                # while we were in Custom mode), pack it now in the right slot.
                if self.comfy_connected and self.comfy_enabled.get():
                    if not self.frame_lora.winfo_ismapped():
                        self.frame_lora.pack(fill="x", padx=(0, 10), pady=6)
                self.actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))
                if self.comfy_connected and self.comfy_enabled.get():
                    self.frame_comfy_queue_row.pack(fill="x", padx=(0, 10), pady=(4, 0))

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
        """Finds [Name N]/[Description N]/[Outfit N]/[Style]/[Scenario]/[Tool] variables in the template text."""
        name_idx, desc_idx, outfit_idx = set(), set(), set()
        use_style = use_scenario = use_tool = False
        for m in CUSTOM_VAR_PATTERN.finditer(text or ""):
            kind, idx, style_kw, scen_kw, tool_kw = m.groups()
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
            elif tool_kw:
                use_tool = True
        return {
            "name_idx": name_idx, "desc_idx": desc_idx, "outfit_idx": outfit_idx,
            "use_style": use_style, "use_scenario": use_scenario, "use_tool": use_tool,
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

        self.custom_active_tools = []
        if parsed["use_tool"]:
            # Mirrors Standard builder's Tools section structurally (a
            # list of slots with "+ Add tool", not a single combobox like
            # Style/Scenario above) — Tools is conceptually a LIST there,
            # and Custom Templates offers the same thing, just filled into
            # wherever the single [Tool] tag sits in the template text
            # (see generate_custom_prompt: every active slot's tag joins
            # with ", " into that one spot).
            tools_frame = ttk.LabelFrame(self.custom_section, text=" Tools ", padding=12)
            tools_frame.pack(fill="x", pady=6)
            tools_header = ttk.Frame(tools_frame)
            tools_header.pack(fill="x", pady=(0, 6))
            ttk.Button(tools_header, text="＋ Add tool", style="Accent.TButton",
                       command=self.add_custom_tool_slot).pack(side="left")
            self.lbl_custom_tools_count = ttk.Label(tools_header, text="0 tools", style="Dim.TLabel")
            self.lbl_custom_tools_count.pack(side="left", padx=12)
            self.custom_tools_list_frame = ttk.Frame(tools_frame)
            self.custom_tools_list_frame.pack(fill="x")
            self.placeholder_custom_tools = ttk.Label(
                self.custom_tools_list_frame, text="No tools added. Click \"＋ Add tool\".",
                style="Dim.TLabel")
            self.placeholder_custom_tools.pack(anchor="w", pady=6, padx=4)

        if not slot_indices and not parsed["use_style"] and not parsed["use_scenario"] and not parsed["use_tool"]:
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
        ttk.Button(btns_row2, text="＋ Tool",
                   command=lambda: insert_var("Tool")).pack(side="left", expand=True, fill="x", padx=2)

        ttk.Label(dlg,
                  text="Each click on \"Name/Description/Outfit\" adds a variable for the next "
                       "template character in sequence (1, 2, 3…). Only the fields you actually "
                       "used here will appear in the builder — if you don't need a style, scenario, "
                       "or tool, just don't add them.",
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

        tool_val = ""
        if parsed["use_tool"]:
            tool_parts = []
            for slot in self.custom_active_tools:
                tool_name = slot["tool_var"].get()
                if not tool_name or tool_name == "None":
                    continue
                tags = self.read_file_content("tools", tool_name)
                if tags:
                    tool_parts.append(tags)
            tool_val = ", ".join(tool_parts)

        def repl(m):
            kind, idx, style_kw, scen_kw, tool_kw = m.groups()
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
            if tool_kw:
                return tool_val
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

    def add_tool_slot(self):
        """Adds a row for selecting a Tools-category library entry —
        structurally the simplest possible sibling of add_character_slot
        above: one combobox, no second axis to pick (no outfit
        equivalent), since a Tool entry is either a bare LoRA binding or
        a short trigger tag, never a scene description with its own
        sub-parts."""
        slot_frame = ttk.Frame(self.scroll_tools, style="Card.TFrame", padding=10)
        slot_frame.pack(fill="x", pady=5, padx=2)

        tool_var = tk.StringVar()

        top_row = ttk.Frame(slot_frame, style="Card.TFrame")
        top_row.pack(fill="x")

        idx_label = ttk.Label(top_row, text=f"Tool {len(self.active_tools) + 1}",
                               style="CardTitle.TLabel")
        idx_label.pack(side="left")

        btn_remove = ttk.Button(top_row, text="✕", width=3, style="Ghost.TButton")
        btn_remove.pack(side="right")
        Tooltip(btn_remove, "Remove tool", self)

        tool_row = ttk.Frame(slot_frame, style="Card.TFrame")
        tool_row.pack(fill="x", pady=(8, 0))

        ttk.Label(tool_row, text="Tool:", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        combo_tool = AutocompleteCombobox(tool_row, textvariable=tool_var)
        combo_tool["values"] = ["None"] + self.get_file_list("tools")
        combo_tool.current(0)
        combo_tool.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_tool_preview = ttk.Button(tool_row, text="👁", width=3,
                                       command=lambda tv=tool_var: self.quick_preview("tools", tv))
        btn_tool_preview.pack(side="left")
        Tooltip(btn_tool_preview, "Show tool description/tag (if any)", self)

        slot_info = {
            "frame": slot_frame,
            "tool_var": tool_var,
            "tool_combo": combo_tool,
            "idx_label": idx_label,
        }
        btn_remove.configure(command=lambda info=slot_info: self.remove_tool_slot(info))

        self.active_tools.append(slot_info)
        self.update_tools_placeholder()

    def remove_tool_slot(self, info):
        info["frame"].destroy()
        self.active_tools.remove(info)
        for i, slot in enumerate(self.active_tools, start=1):
            slot["idx_label"].configure(text=f"Tool {i}")
        self.update_tools_placeholder()

    def update_tools_placeholder(self):
        if self.active_tools:
            self.placeholder_tools.pack_forget()
        else:
            self.placeholder_tools.pack(anchor="w", pady=10, padx=4)
        self.lbl_tools_count.configure(text=f"{len(self.active_tools)} tool(s)")

    def add_custom_tool_slot(self):
        """Custom Template's own Tools slot — simpler than Standard's
        (no canvas/scrollbar, no preview eye button) since this is the
        less-frequently-used path and a template with a [Tool] tag is
        unlikely to need dozens of slots the way a long Builder session
        might accumulate characters. Kept in its own
        self.custom_active_tools list, separate from Standard's
        self.active_tools, exactly like custom_active_slots is already
        separate from active_characters."""
        slot_frame = ttk.Frame(self.custom_tools_list_frame, style="Card.TFrame", padding=8)
        slot_frame.pack(fill="x", pady=3)

        tool_var = tk.StringVar()
        row = ttk.Frame(slot_frame, style="Card.TFrame")
        row.pack(fill="x")
        combo_tool = AutocompleteCombobox(row, textvariable=tool_var)
        combo_tool["values"] = ["None"] + self.get_file_list("tools")
        combo_tool.current(0)
        combo_tool.pack(side="left", fill="x", expand=True, padx=(0, 8))

        slot_info = {"frame": slot_frame, "tool_var": tool_var, "tool_combo": combo_tool}
        btn_remove = ttk.Button(row, text="✕", width=3, style="Ghost.TButton",
                                 command=lambda info=slot_info: self.remove_custom_tool_slot(info))
        btn_remove.pack(side="left")

        self.custom_active_tools.append(slot_info)
        self.update_custom_tools_placeholder()

    def remove_custom_tool_slot(self, info):
        info["frame"].destroy()
        self.custom_active_tools.remove(info)
        self.update_custom_tools_placeholder()

    def update_custom_tools_placeholder(self):
        if self.custom_active_tools:
            self.placeholder_custom_tools.pack_forget()
        else:
            self.placeholder_custom_tools.pack(anchor="w", pady=6, padx=4)
        self.lbl_custom_tools_count.configure(text=f"{len(self.custom_active_tools)} tool(s)")

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

        for f in sorted(canon_files, key=natural_sort_key):
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

    def _show_lora_dependency_report(self, missing, content):
        """Same layout as _show_preview_dialog, plus a "🔎 Find
        candidates" button that hands off to the interactive candidate-
        confirmation dialog (_show_lora_candidates_dialog). Kept as its
        own method (not a parameter bolted onto _show_preview_dialog)
        since this dialog needs to carry the missing dict forward to the
        next step, which a generic text-preview dialog has no reason to
        know about."""
        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("LoRA dependency check")
        dlg.configure(bg=c["bg"])
        ttk.Label(dlg, text="LoRA dependency check", style="Title.TLabel").pack(
            anchor="w", padx=14, pady=(14, 6))
        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD, font=self.default_font,
                                         bg=c["bg_input"], fg=c["fg"], relief="flat", borderwidth=0)
        txt.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        txt.insert("1.0", content)
        txt.configure(state="disabled")

        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=14, pady=(0, 14))

        def open_candidates():
            dlg.destroy()
            self._show_lora_candidates_dialog(missing)

        ttk.Button(btn_row, text="🔎 Find candidates", style="Accent.TButton",
                   command=open_candidates).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(btn_row, text="Close", style="Ghost.TButton", command=dlg.destroy).pack(
            side="left", fill="x", expand=True)

        self._finalize_dialog(dlg, min_w=480, min_h=320)

    def _show_lora_candidates_dialog(self, missing):
        """Interactive candidate-confirmation dialog — the actual UI for
        the auto-link-by-name feature. For each missing LoRA path:
          - single match found -> shown with a "Use this" button that
            applies it immediately on click (one-click fix, but never
            silent — the user sees exactly what's about to change).
          - 2+ matches found (a real name collision) -> every option is
            listed with its OWN "Use this" button; nothing is pre-picked,
            so a genuine ambiguity between two different LoRAs (e.g. for
            different base models sharing a filename) can never be
            resolved by guessing wrong.
          - no match found -> shown as plain text, no button — there is
            truly nothing to suggest, only a manual fix would help.
        Applying a candidate updates that row in place (so the dialog
        stays open and usable for the remaining rows) rather than closing
        the whole dialog after every single click."""
        candidates = self.find_lora_candidates(list(missing.keys()))

        c = self.colors
        dlg = tk.Toplevel(self.root)
        dlg.title("LoRA candidates")
        dlg.configure(bg=c["bg"])
        ttk.Label(dlg, text="🔎 LoRA candidates", style="Title.TLabel").pack(
            anchor="w", padx=14, pady=(14, 6))
        ttk.Label(dlg, style="Dim.TLabel", wraplength=520, justify="left", text=
                  "Matched by filename only, ignoring folder — review each one before "
                  "applying. A path with more than one match is a real name collision "
                  "(e.g. two different LoRAs for different base models): nothing is "
                  "picked automatically, choose which one is actually correct.").pack(
            anchor="w", padx=14, pady=(0, 8))

        list_canvas_frame = ttk.Frame(dlg)
        list_canvas_frame.pack(fill="both", expand=True, padx=14)
        list_scroll = ttk.Scrollbar(list_canvas_frame, orient="vertical")
        list_scroll.pack(side="right", fill="y")
        list_canvas = tk.Canvas(list_canvas_frame, bg=c["bg"], highlightthickness=0,
                                 yscrollcommand=list_scroll.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_scroll.configure(command=list_canvas.yview)
        list_inner = ttk.Frame(list_canvas)
        list_inner.bind("<Configure>", lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        canvas_window = list_canvas.create_window((0, 0), window=list_inner, anchor="nw")
        list_canvas.bind("<Configure>", lambda e: list_canvas.itemconfigure(canvas_window, width=e.width))

        def _on_candidates_mousewheel(event):
            list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        # Scoped to this canvas only (Enter/Leave), not bind_all — so it
        # can't fight with any other scroll area if this dialog is ever
        # combined with one.
        list_canvas.bind("<Enter>", lambda e: list_canvas.bind_all("<MouseWheel>", _on_candidates_mousewheel))
        list_canvas.bind("<Leave>", lambda e: list_canvas.unbind_all("<MouseWheel>"))

        single_match_paths = [mp for mp, result in candidates.items() if isinstance(result, str)]

        row_use_this = {}  # missing_path -> callable, only for single-match rows

        for missing_path in sorted(missing.keys(), key=natural_sort_key):
            row = ttk.Frame(list_inner, style="Card.TFrame", padding=8)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=f"✗ {missing_path}", style="CardTitle.TLabel",
                      wraplength=460, justify="left").pack(anchor="w")
            affected = missing[missing_path]
            affected_desc = ", ".join(f"[{CATEGORY_LABELS.get(cat, cat)}] {name}" for cat, name in affected)
            ttk.Label(row, text=f"used by: {affected_desc}", style="CardDim.TLabel",
                      wraplength=460, justify="left").pack(anchor="w", pady=(2, 6))

            result = candidates.get(missing_path)
            if result is None:
                ttk.Label(row, text="No matching filename found anywhere in ComfyUI's "
                                     "LoRA list — nothing to suggest.", style="Dim.TLabel").pack(anchor="w")
                continue

            option_paths = [result] if isinstance(result, str) else result
            if len(option_paths) > 1:
                ttk.Label(row, text=f"⚠ {len(option_paths)} files share this name — pick the correct one:",
                          style="Dim.TLabel").pack(anchor="w", pady=(0, 4))

            for candidate_path in option_paths:
                cand_row = ttk.Frame(row)
                cand_row.pack(fill="x", pady=2)
                ttk.Label(cand_row, text=f"→ {candidate_path}", style="TLabel",
                          wraplength=380, justify="left").pack(side="left", fill="x", expand=True)

                def use_this(mp=missing_path, cp=candidate_path, aff=affected, r=row):
                    updated = self.apply_lora_candidate(mp, cp, aff)
                    for child in r.winfo_children():
                        child.destroy()
                    ttk.Label(r, text=f"✓ Re-pointed to {cp}", style="TLabel").pack(anchor="w")
                    ttk.Label(r, text=f"{updated} entr{'y' if updated == 1 else 'ies'} updated.",
                              style="Dim.TLabel").pack(anchor="w")
                    self.reload_all_lists()

                ttk.Button(cand_row, text="Use this", command=use_this).pack(side="left", padx=(8, 0))

                # Only single-match rows have exactly one (candidate_path,
                # use_this) pair — that's the only case "Use all" below
                # is allowed to trigger automatically. A collision row
                # (len(option_paths) > 1) deliberately never lands here.
                if len(option_paths) == 1:
                    row_use_this[missing_path] = use_this

        if single_match_paths:
            def use_all_single_matches():
                # Snapshot first — use_this() destroys each row's
                # children as it goes, which would otherwise mutate
                # row_use_this's iteration out from under us.
                for fn in list(row_use_this.values()):
                    fn()
                bulk_btn.configure(state="disabled", text="✓ Applied")

            bulk_row = ttk.Frame(dlg)
            bulk_row.pack(fill="x", padx=14, pady=(8, 0))
            bulk_btn = ttk.Button(
                bulk_row, text=f"✓ Use all {len(single_match_paths)} single-match candidate"
                               f"{'s' if len(single_match_paths) != 1 else ''}",
                style="Accent.TButton", command=use_all_single_matches)
            bulk_btn.pack(fill="x")
            Tooltip(bulk_btn, "Applies every candidate that had EXACTLY ONE match. "
                              "Real name collisions (2+ matches) are never included — "
                              "those still need a manual pick below.", self)

        ttk.Button(dlg, text="Close", style="Ghost.TButton", command=dlg.destroy).pack(
            fill="x", padx=14, pady=14)

        self._finalize_dialog(dlg, min_w=560, min_h=420)

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

        export_import_row = ttk.Frame(left)
        export_import_row.pack(fill="x", pady=(0, 8))
        ttk.Button(export_import_row, text="📦 Export library", style="Ghost.TButton",
                   command=self.export_library).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(export_import_row, text="📥 Import library", style="Ghost.TButton",
                   command=self.import_library).pack(side="left", fill="x", expand=True, padx=(4, 0))

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

        # ---- Folder toolbar (subfolders are a pure organization layer
        # over the library — see _folder_maps) ----
        folder_toolbar = ttk.Frame(left)
        folder_toolbar.pack(fill="x", pady=(0, 8))
        self.btn_lib_expand_all = ttk.Button(folder_toolbar, text="▾ Expand all",
                                              command=self.expand_all_library_folders)
        self.btn_lib_expand_all.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_lib_collapse_all = ttk.Button(folder_toolbar, text="▸ Collapse all",
                                                command=self.collapse_all_library_folders)
        self.btn_lib_collapse_all.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_lib_new_folder = ttk.Button(folder_toolbar, text="📁＋ New folder",
                                              command=self.prompt_new_library_folder)
        self.btn_lib_new_folder.pack(side="left", fill="x", expand=True, padx=(4, 0))

        list_holder = ttk.Frame(left)
        list_holder.pack(fill="both", expand=True)

        columns = ("tags",)
        # show="tree headings": the built-in #0 column carries the
        # indentation/disclosure-triangle hierarchy (folders as parent
        # rows, entries as their — possibly root-level — children), and
        # also doubles as the "Name" column so nothing about the existing
        # two-column layout (name + tags preview) has to change visually.
        self.tree_library = ttk.Treeview(list_holder, columns=columns, show="tree headings",
                                          selectmode="extended")
        self.tree_library.heading("#0", text="Name")
        self.tree_library.heading("tags", text="Tags preview")
        self.tree_library.column("#0", width=180, anchor="w", stretch=True)
        self.tree_library.column("tags", width=260, anchor="w")
        self.tree_library.pack(side="left", fill="both", expand=True)
        self.tree_library.bind("<<TreeviewSelect>>", self.on_library_select)
        self.tree_library.bind("<<TreeviewOpen>>", self._on_library_folder_toggled)
        self.tree_library.bind("<<TreeviewClose>>", self._on_library_folder_toggled)
        # Recorded first (no add="+", so it runs before the native
        # open/close handling and before our drag-press handler below) —
        # see _on_lib_tree_disclosure_press / _on_library_folder_toggled.
        self.tree_library.bind("<ButtonPress-1>", self._on_lib_tree_disclosure_press)
        # Mouse drag: press on an entry, drag onto a folder row, release to move.
        self.tree_library.bind("<ButtonPress-1>", self._on_lib_tree_press, add="+")
        self.tree_library.bind("<B1-Motion>", self._on_lib_tree_drag, add="+")
        self.tree_library.bind("<ButtonRelease-1>", self._on_lib_tree_drop, add="+")
        # Right-click: "Move to..." / "New folder" / "Rename folder" / "Delete folder" context menu.
        right_click_event = "<Button-2>" if sys.platform == "darwin" else "<Button-3>"
        self.tree_library.bind(right_click_event, self._on_lib_tree_right_click)

        tree_scroll = ttk.Scrollbar(list_holder, orient="vertical", command=self.tree_library.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree_library.configure(yscrollcommand=tree_scroll.set)

        count_row = ttk.Frame(left)
        count_row.pack(fill="x", pady=(6, 0))
        self.lbl_lib_count = ttk.Label(count_row, text="0 entries", style="Dim.TLabel")
        self.lbl_lib_count.pack(side="left")
        ttk.Label(count_row, text="·  Right-click for folder options",
                  style="Dim.TLabel").pack(side="left", padx=(10, 0))
        # Requires a live ComfyUI connection — the check compares every
        # entry's bound LoRA against ComfyUI's own current LoRA list
        # (self._available_loras), the same source of truth the LoRA
        # Manager already validates against before a generation. Kept in
        # sync with that connection state by _refresh_lib_lora_visibility,
        # the same function that already toggles LoRA-related Library UI.
        self.btn_check_lora_deps = ttk.Button(count_row, text="🔍 Check LoRA dependencies",
                                               style="Ghost.TButton", state="disabled",
                                               command=self.check_library_lora_dependencies)
        self.btn_check_lora_deps.pack(side="right")

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

        self.combo_canon_char = AutocompleteCombobox(self.frame_canon_binding, state="disabled")
        self.combo_canon_char.pack(fill="x", pady=4)

        # "Force to start of prompt" block — shown ONLY for the "tools"
        # category. See _build_tools_block / load_library_meta's
        # force_first docstring for what this actually does once a tag
        # is set on a Tool entry.
        self.frame_tool_options = ttk.Frame(right)
        self.tool_force_first_var = tk.BooleanVar()
        self.chk_tool_force_first = ttk.Checkbutton(
            self.frame_tool_options,
            text="Force this tool's tag to the very start of the prompt (e.g. @fixedanatomy)",
            variable=self.tool_force_first_var)
        self.chk_tool_force_first.pack(anchor="w", pady=4)

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
        if cat == "tools":
            self.frame_tool_options.pack(fill="x", pady=(0, 10), before=self.ent_lib_name_label)
        else:
            self.tool_force_first_var.set(False)
            self.frame_tool_options.pack_forget()
        self._highlight_category_button(cat)
        self.refresh_library_list()

    def toggle_canon_char_selector(self):
        if self.is_canon_var.get():
            self.combo_canon_char.configure(state="normal")
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
        if hasattr(self, "btn_check_lora_deps"):
            self.btn_check_lora_deps.configure(state="normal" if self.comfy_connected else "disabled")

    def apply_lora_candidate(self, old_path, new_path, affected_entries):
        """Rewrites the 'lora' field in every affected entry's meta
        sidecar from old_path to new_path, leaving source_url/force_first
        on each entry exactly as they were — this only ever touches the
        one field, never anything else about the entry. affected_entries
        is the same [(category, name), ...] list the dependency scan
        already produced for old_path, so there's no need to re-derive
        which entries are involved. Returns how many entries were
        updated."""
        updated = 0
        for category, name in affected_entries:
            # Canon outfits are displayed as "Char — Canon N" but stored
            # on disk as "Char_Canon_N" — load_library_meta/
            # save_library_meta both key off the on-disk base name, so
            # the display form needs converting back before use here.
            if category == "outfits" and " — Canon " in name:
                char_name, num = name.split(" — Canon ")
                base = f"{char_name}_Canon_{num}"
            else:
                base = name
            meta = self.load_library_meta(category, base)
            if meta.get("lora") != old_path:
                continue  # already changed by something else since the scan ran
            self.save_library_meta(category, base, source_url=meta.get("source_url"),
                                    lora=new_path, force_first=meta.get("force_first", False))
            updated += 1
        return updated

    @staticmethod
    def _lora_path_basename(path):
        """Extracts the filename from a LoRA path, recognizing BOTH '\\'
        and '/' as separators regardless of which OS PromptForge itself
        is running on. LoRA paths in this app are always stored Windows-
        style (e.g. "PromptForgeLoras\\Anima\\Characters\\akane.
        safetensors" — see the README's models/lora folder structure),
        since that's what ComfyUI itself reports them as on a Windows
        host. os.path.basename is platform-dependent: it only splits on
        the separator of whatever OS Python is currently running on, so
        on Linux/macOS it would treat an entire backslash-separated
        Windows path as a single filename with no split at all — quietly
        breaking every candidate match. This always treats both
        separators as path boundaries, independent of the host OS."""
        return path.replace("\\", "/").rsplit("/", 1)[-1]

    def find_lora_candidates(self, missing_paths):
        """For each missing LoRA path, looks for files elsewhere in
        ComfyUI's current LoRA list (self._available_loras) whose
        FILENAME (not full path) matches exactly — i.e. the user has the
        right file, just under a different folder than the one the
        library entry was originally bound to (e.g. they didn't recreate
        the exact "PromptForgeLoras\\Anima\\Characters\\..." structure
        from the original library).

        Returns {missing_path: result} where result is one of:
          - a single candidate path (str) — exactly one other file shares
            this basename; safe to suggest as a one-click fix.
          - a list of 2+ candidate paths — a genuine name collision (two
            different LoRAs, e.g. for different base models, that happen
            to share a filename). Deliberately NOT auto-picked: per the
            original feature discussion, silently guessing wrong here
            means a generation runs with the wrong model's LoRA with no
            visible error — the only safe move is to show every option
            and let a person decide.
          - None — no other file with this basename exists anywhere;
            there's genuinely nothing to suggest.
        """
        by_basename = {}
        for path in self._available_loras:
            by_basename.setdefault(self._lora_path_basename(path), []).append(path)

        results = {}
        for missing_path in missing_paths:
            basename = self._lora_path_basename(missing_path)
            candidates = [p for p in by_basename.get(basename, []) if p != missing_path]
            if not candidates:
                results[missing_path] = None
            elif len(candidates) == 1:
                results[missing_path] = candidates[0]
            else:
                results[missing_path] = candidates
        return results

    def _scan_library_lora_dependencies(self):
        """Scans every entry in every Library category (plus canon
        outfits, scanned separately since get_file_list("outfits")
        deliberately excludes them) for a bound LoRA, and returns
        (entry_count, missing) where missing maps lora_path ->
        [(category, entry_name), ...] for every bound path NOT found in
        self._available_loras.

        Pulled out of check_library_lora_dependencies so the candidate-
        suggestion dialog (_show_lora_candidates_dialog) can run the
        exact same scan rather than duplicating it."""
        entry_count = 0
        missing = {}
        for category in self.CATEGORIES:
            for name in self.get_file_list(category):
                entry_count += 1
                lora = self.load_library_meta(category, name).get("lora")
                if lora and lora not in self._available_loras:
                    missing.setdefault(lora, []).append((category, name))

        canon_files = glob.glob(os.path.join(self.DATA_DIR, "outfits", "*_Canon_*.txt"))
        for f in canon_files:
            base = os.path.splitext(os.path.basename(f))[0]
            entry_count += 1
            lora = self.load_library_meta("outfits", base).get("lora")
            if lora and lora not in self._available_loras:
                char_name, num = base.split("_Canon_")
                missing.setdefault(lora, []).append(("outfits", f"{char_name} — Canon {num}"))

        return entry_count, missing

    def check_library_lora_dependencies(self):
        """'🔍 Check LoRA dependencies' — scans every entry in every
        Library category for a bound LoRA (Task 7.1's meta sidecar) and
        reports any that ComfyUI doesn't currently have, grouped by which
        entry(ies) reference each missing file.

        This is a deliberately separate, manually-triggered pass over the
        WHOLE library, distinct from the per-generation validation in
        on_generate_in_comfy_clicked (which only ever looks at whatever's
        active in the Builder right now). See the dependency-check
        feature discussion: someone who downloaded a 100-character
        library but only plans to use one of them shouldn't be forced
        through a check of the other 99; someone who just finished
        downloading everything wants exactly this, on demand.

        Requires comfy_connected (the button is disabled otherwise) since
        "what LoRAs does ComfyUI actually have" is the whole point of the
        comparison — there's nothing to check against without it."""
        if not self.comfy_connected:
            messagebox.showinfo("Check LoRA dependencies",
                                 "Connect to ComfyUI first — this check compares your library "
                                 "against ComfyUI's current LoRA list.")
            return
        if not self._available_loras:
            if not messagebox.askyesno(
                    "Check LoRA dependencies",
                    "ComfyUI's LoRA list hasn't loaded yet (or came back empty).\n\n"
                    "Run the check anyway? Every bound LoRA will show up as \"missing\" "
                    "until the list loads."):
                return

        entry_count, missing = self._scan_library_lora_dependencies()

        if not missing:
            messagebox.showinfo("Check LoRA dependencies",
                                 f"✓ All LoRAs bound across {entry_count} library entries "
                                 f"were found in ComfyUI. Nothing missing.")
            return

        lines = [f"{len(missing)} LoRA file(s) referenced by your library were NOT found in "
                 f"ComfyUI's current LoRA list:\n"]
        for lora_path in sorted(missing.keys(), key=natural_sort_key):
            lines.append(f"\n✗ {lora_path}")
            for category, name in missing[lora_path]:
                lines.append(f"    used by: [{CATEGORY_LABELS.get(category, category)}] {name}")
        lines.append(
            "\n\nDouble-check the file is actually present under ComfyUI's models/lora "
            "folder at that exact relative path, then reconnect (or just re-open this "
            "check) to refresh ComfyUI's LoRA list.")
        lines.append(
            "\n\nClick \"🔎 Find candidates\" below to search for files with a matching "
            "name elsewhere in ComfyUI's LoRA list (e.g. if you skipped recreating the "
            "exact folder structure) before manually re-pointing each entry.")
        self._show_lora_dependency_report(missing, "\n".join(lines))


    # ==========================================================
    #              LIBRARY EXPORT / IMPORT (backup/sharing)
    # ==========================================================
    def export_library(self):
        """'📦 Export library' — zips the whole prompt_forge_data/ tree
        (every category's .txt/.jpg/.meta.json triplets, _folders.json,
        templates, settings, history) EXCEPT _comfy_previews/, which is
        a disposable session-only cache (see init_folders/README's Data &
        storage section) that has no business in a library backup or a
        bundle meant to be shared with someone else.

        Relative paths inside the zip exactly mirror prompt_forge_data/'s
        own layout (e.g. "characters/Megumin.txt") — that's what lets
        import_library() below just walk the archive by category without
        any special-casing, and lets someone unzip it by hand and get
        back the exact folder structure if they ever need to."""
        default_name = f"promptforge_library_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        path = filedialog.asksaveasfilename(
            title="Export library", defaultextension=".zip",
            initialfile=default_name, filetypes=[("Zip archive", "*.zip")])
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(self.DATA_DIR):
                    dirs[:] = [d for d in dirs if d != "_comfy_previews" and not d.startswith("_import_tmp_")]
                    for fname in files:
                        full_path = os.path.join(root, fname)
                        rel_path = os.path.relpath(full_path, self.DATA_DIR)
                        zf.write(full_path, arcname=rel_path)
        except Exception as e:
            messagebox.showerror("Export library", f"Failed to create the zip file:\n{e}")
            return
        messagebox.showinfo("Export library", f"Library exported to:\n{path}")

    def import_library(self):
        """'📥 Import library' — merges another exported library zip
        into the current one. Strict skip-on-collision: if an entry name
        already exists in a given category, it is left completely
        untouched (not overwritten, not renamed, not merged) and the
        incoming one is skipped — see the import/export feature
        discussion: someone's own library must never be put at risk by
        an import, full stop. A final report lists exactly what was
        imported and what was skipped (and why), so nothing is silently
        dropped without the user finding out."""
        zip_path = filedialog.askopenfilename(
            title="Import library", filetypes=[("Zip archive", "*.zip")])
        if not zip_path:
            return

        tmp_dir = os.path.join(self.DATA_DIR, f"_import_tmp_{uuid.uuid4().hex[:8]}")
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Zip-slip guard: refuse any member whose path would
                # escape tmp_dir once extracted (e.g. "../../etc/passwd"
                # or an absolute path baked into the archive). A
                # malformed or hostile zip must never be able to write
                # outside the sandbox we just created for it.
                tmp_dir_real = os.path.realpath(tmp_dir)
                for member in zf.namelist():
                    member_path = os.path.realpath(os.path.join(tmp_dir, member))
                    if not (member_path == tmp_dir_real
                            or member_path.startswith(tmp_dir_real + os.sep)):
                        messagebox.showerror(
                            "Import library",
                            f"This zip file contains an unsafe path and was rejected:\n{member}")
                        return
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            messagebox.showerror("Import library", "That file isn't a valid zip archive.")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        except Exception as e:
            messagebox.showerror("Import library", f"Failed to read the zip file:\n{e}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        try:
            imported, skipped = self._merge_imported_library(tmp_dir)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        self.reload_all_lists()
        self.refresh_library_list()

        lines = [f"Imported {len(imported)} entr{'y' if len(imported) == 1 else 'ies'}."]
        if imported:
            lines.append("")
            for category, name in imported:
                lines.append(f"  + [{CATEGORY_LABELS.get(category, category)}] {name}")
        if skipped:
            lines.append("")
            lines.append(f"Skipped {len(skipped)} entr{'y' if len(skipped) == 1 else 'ies'} "
                          f"(already exist in your library — nothing was overwritten):")
            for category, name in skipped:
                lines.append(f"  · [{CATEGORY_LABELS.get(category, category)}] {name}")
        self._show_preview_dialog("Library import results", "\n".join(lines))

    def _merge_imported_library(self, extracted_dir):
        """Walks an already-extracted, already-zip-slip-checked library
        tree and copies in only the entries that don't already exist
        (by name) in the corresponding category — see import_library's
        docstring for the collision rule. Canon outfits ride along with
        their owning character's category scan automatically, since
        they're just .txt files in outfits/ with "_Canon_" in the name —
        no special-casing needed here, the same skip-on-collision rule
        protects them exactly like any other outfit entry.

        Returns (imported, skipped), each a list of (category, name)."""
        imported = []
        skipped = []
        for category in self.CATEGORIES:
            src_cat_dir = os.path.join(extracted_dir, category)
            if not os.path.isdir(src_cat_dir):
                continue
            dest_cat_dir = os.path.join(self.DATA_DIR, category)
            os.makedirs(dest_cat_dir, exist_ok=True)
            for fname in sorted(os.listdir(src_cat_dir), key=natural_sort_key):
                if not fname.endswith(".txt"):
                    continue  # the matching .jpg/.meta.json (if any) ride along below
                name = os.path.splitext(fname)[0]
                dest_txt = os.path.join(dest_cat_dir, fname)
                if os.path.exists(dest_txt):
                    skipped.append((category, name))
                    continue
                try:
                    shutil.copyfile(os.path.join(src_cat_dir, fname), dest_txt)
                    for ext in (".jpg", LIBRARY_META_EXT):
                        src_sidecar = os.path.join(src_cat_dir, f"{name}{ext}")
                        if os.path.exists(src_sidecar):
                            shutil.copyfile(src_sidecar, os.path.join(dest_cat_dir, f"{name}{ext}"))
                    imported.append((category, name))
                except Exception:
                    skipped.append((category, name))

        # _folders.json: merge per-category folder placement for whatever
        # just got imported, WITHOUT touching the placement of any entry
        # that already existed (those were never touched above either).
        src_folders_path = os.path.join(extracted_dir, LIBRARY_FOLDERS_FILE_NAME)
        if os.path.exists(src_folders_path):
            try:
                with open(src_folders_path, "r", encoding="utf-8") as f:
                    src_folder_maps = json.load(f)
                if isinstance(src_folder_maps, dict):
                    for category, name in imported:
                        folder_path = src_folder_maps.get(category, {}).get(name)
                        if folder_path:
                            self.set_entry_folder(category, name, folder_path)
            except Exception:
                pass  # folder placement is cosmetic — never worth failing the whole import over

        return imported, skipped

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
        self.save_library_meta(cat, name, source_url=self.lib_source_url, lora=self.lib_entry_lora,
                                force_first=self.tool_force_first_var.get())

    # ---- List / search ----
    # iid namespacing: folder rows use "folder::<path>" so they can never
    # collide with an entry row's iid (which is just the entry's plain
    # filename, exactly as before — Builder/history/LoRA code keeps using
    # that same bare name and never sees the "folder::" prefix).
    FOLDER_IID_PREFIX = "folder::"

    def _folder_iid(self, folder_path):
        return self.FOLDER_IID_PREFIX + folder_path

    def _is_folder_iid(self, iid):
        return isinstance(iid, str) and iid.startswith(self.FOLDER_IID_PREFIX)

    def _folder_path_from_iid(self, iid):
        return iid[len(self.FOLDER_IID_PREFIX):] if self._is_folder_iid(iid) else None

    def _compute_lora_status_for_category(self, category):
        """Returns {base_name: "ok"|"candidate"|"missing"} for every
        entry in `category` that has a LoRA bound to it — entries with
        no LoRA binding at all are simply absent from the dict (no
        status, no row coloring; see refresh_library_list's tags=()
        for the unbound case).

        "ok" (green): the bound path matches something in
        self._available_loras exactly.
        "candidate" (yellow): no exact match, but find_lora_candidates
        found at least one file elsewhere with the same filename — a
        likely fix, not a confirmed one (could even be a genuine name
        collision between two different LoRAs; either way it's not a
        clean "yes" so it's flagged, not colored green).
        "missing" (red): no exact match and no candidate either —
        nothing usable was found anywhere.

        Includes canon outfits via their own glob pass for the "outfits"
        category, same as get_file_list/_scan_library_lora_dependencies
        already do elsewhere — they're excluded from get_file_list
        itself but are still real entries with their own meta sidecar."""
        bases_and_loras = []
        for name in self.get_file_list(category):
            lora = self.load_library_meta(category, name).get("lora")
            if lora:
                bases_and_loras.append((name, lora))
        if category == "outfits":
            for f in glob.glob(os.path.join(self.DATA_DIR, "outfits", "*_Canon_*.txt")):
                base = os.path.splitext(os.path.basename(f))[0]
                lora = self.load_library_meta("outfits", base).get("lora")
                if lora:
                    bases_and_loras.append((base, lora))

        missing_paths = [lora for _, lora in bases_and_loras if lora not in self._available_loras]
        candidates = self.find_lora_candidates(missing_paths) if missing_paths else {}

        status = {}
        for base, lora in bases_and_loras:
            if lora in self._available_loras:
                status[base] = "ok"
            elif candidates.get(lora) is not None:
                status[base] = "candidate"
            else:
                status[base] = "missing"
        return status

    def refresh_library_list(self):
        for item in self.tree_library.get_children():
            self.tree_library.delete(item)

        cat = self.lib_current_category
        query = self.lib_search_var.get().strip().lower()
        searching = bool(query)
        cat_map = self._folder_maps.get(cat, {})
        path = os.path.join(self.DATA_DIR, cat)
        files = sorted(glob.glob(os.path.join(path, "*.txt")))

        # LoRA-status row coloring (Library tab only — see the feature
        # discussion: "intuitive at-a-glance dependency check, green
        # while in Library, gone the moment you switch to Builder").
        # Only computed when ComfyUI is actually connected; without that,
        # self._available_loras is empty/stale and "found" vs "missing"
        # wouldn't mean anything (every entry would show red, which is
        # noise, not signal). Built once per refresh, not per entry, so
        # find_lora_candidates' own basename-index isn't rebuilt 100
        # times for a 100-entry category.
        lora_status_by_base = {}
        if self.comfy_connected:
            lora_status_by_base = self._compute_lora_status_for_category(cat)
            self.tree_library.tag_configure("lora_ok", foreground=self.colors["success"])
            self.tree_library.tag_configure("lora_candidate", foreground=self.colors["warn"])
            self.tree_library.tag_configure("lora_missing", foreground=self.colors["danger"])

        # ---- Build an in-memory tree: {folder_path: {"entries": [...], "subfolders": {...}}} ----
        # root = folder_path "".
        root_node = {"entries": [], "subfolders": {}}

        def get_node(folder_path):
            """Walks/creates the chain of subfolder dicts for folder_path,
            so a deeply-nested entry (or an empty folder created via
            'New folder') always has a place to live in the tree."""
            if not folder_path:
                return root_node
            node = root_node
            for part in folder_path.split(FOLDER_PATH_SEP):
                node = node["subfolders"].setdefault(part, {"entries": [], "subfolders": {}})
            return node

        # Pre-register empty folders (created but nothing filed yet) and
        # every folder that appears anywhere in the manifest, so ancestors
        # of nested paths exist even if nothing lives directly in them.
        for folder_path in self.list_all_folders(cat):
            get_node(folder_path)

        count = 0
        matched_folder_paths = set()  # folders that contain a search match somewhere below them
        for f in files:
            base = os.path.splitext(os.path.basename(f))[0]
            if cat == "outfits" and self.is_canon_outfit_name(base):
                continue  # filed under Canonical Outfits below instead of the flat list
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read().strip()
            except Exception:
                content = ""
            if query and query not in base.lower() and query not in content.lower():
                continue
            folder_path = cat_map.get(base, "")
            node = get_node(folder_path)
            node["entries"].append((base, base, content))
            if folder_path:
                parts = folder_path.split(FOLDER_PATH_SEP)
                for depth in range(1, len(parts) + 1):
                    matched_folder_paths.add(FOLDER_PATH_SEP.join(parts[:depth]))
            count += 1

        # ---- Canon outfits: auto-filed under Canonical Outfits, with the
        # existing "{char_name} — Canon {num}" display name preserved. ----
        if cat == "outfits":
            canon_files = sorted(glob.glob(os.path.join(path, "*.txt")))
            for f in canon_files:
                base = os.path.splitext(os.path.basename(f))[0]
                if not self.is_canon_outfit_name(base):
                    continue
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        content = fh.read().strip()
                except Exception:
                    content = ""
                if query and query not in base.lower() and query not in content.lower():
                    continue
                char_name, num = base.split("_Canon_")
                display_name = f"{char_name} — Canon {num}"
                node = get_node(CANONICAL_OUTFITS_FOLDER)
                node["entries"].append((base, display_name, content))
                matched_folder_paths.add(CANONICAL_OUTFITS_FOLDER)
                count += 1

        # ---- Insert into the Treeview: folders (alphabetical) above
        # entries (alphabetical) at every level, recursively. ----
        cat_empty_folders = self._empty_folders.get(cat, set())

        def insert_node(parent_iid, parent_path, node):
            for folder_name in sorted(node["subfolders"].keys(), key=natural_sort_key):
                folder_path = f"{parent_path}{FOLDER_PATH_SEP}{folder_name}" if parent_path else folder_name
                child = node["subfolders"][folder_name]
                # Skip rendering a folder branch entirely while searching,
                # UNLESS something inside it (at any depth) matched, OR
                # it's a folder the user explicitly created and hasn't
                # filed anything into yet — an empty folder can't leak a
                # false match into the results, and hiding a folder the
                # user just made on purpose (e.g. to receive a batch of
                # "Casual" entries they're about to search for and move)
                # would be confusing, not helpful.
                if searching and folder_path not in matched_folder_paths and folder_path not in cat_empty_folders:
                    continue
                icon = "📁"
                fiid = self._folder_iid(folder_path)
                self.tree_library.insert(parent_iid, "end", iid=fiid, text=f"{icon} {folder_name}", values=("",))
                should_open = (folder_path in matched_folder_paths) if searching \
                    else self._is_folder_expanded(cat, folder_path)
                self.tree_library.item(fiid, open=should_open)
                insert_node(fiid, folder_path, child)
            for base, display_name, content in sorted(node["entries"], key=lambda e: natural_sort_key(e[1])):
                preview = content.replace("\n", " ")
                preview_short = (preview[:60] + "…") if len(preview) > 60 else preview
                status = lora_status_by_base.get(base)
                tags = (f"lora_{status}",) if status else ()
                self.tree_library.insert(parent_iid, "end", iid=base, text=display_name,
                                          values=(preview_short,), tags=tags)

        insert_node("", "", root_node)

        self.lbl_lib_count.configure(text=f"{count} {'entry' if count == 1 else 'entries'}")

    def _is_folder_expanded(self, category, folder_path):
        return folder_path in self._expanded_folders.setdefault(category, set())

    def _on_library_folder_toggled(self, event=None):
        """Persists manual expand/collapse so it survives a list refresh
        (e.g. after a save or a move) and the next time the category is
        opened — but only outside of an active search, where openness is
        instead driven entirely by which branches matched (see
        refresh_library_list).

        NOTE: tree.focus() is NOT a reliable source for "which row was
        just opened/closed" — Tk's <<TreeviewOpen>>/<<TreeviewClose>>
        fire with focus still pointing at whatever was focused/selected
        before the click in some cases, not necessarily the toggled row.
        We instead read the row directly under the last button-press
        (see _on_lib_tree_disclosure_press below) and use THAT, falling
        back to tree.focus() only if nothing was recorded.
        """
        iid = self._lib_last_toggled_iid or self.tree_library.focus()
        folder_path = self._folder_path_from_iid(iid)
        if folder_path is None:
            return
        if self.lib_search_var.get().strip():
            return  # don't let a search-driven auto-open pollute the persisted state
        cat = self.lib_current_category
        expanded = self._expanded_folders.setdefault(cat, set())
        if self.tree_library.item(iid, "open"):
            expanded.add(folder_path)
        else:
            expanded.discard(folder_path)

    def _on_lib_tree_disclosure_press(self, event):
        """Records exactly which row is under a click BEFORE Tk processes
        it, so the subsequent <<TreeviewOpen>>/<<TreeviewClose>> handler
        above can trust it instead of the unreliable tree.focus(). Always
        records the row under the cursor, folder or not — harmless for
        entry rows since _folder_path_from_iid() filters those out."""
        self._lib_last_toggled_iid = self.tree_library.identify_row(event.y)

    def expand_all_library_folders(self):
        cat = self.lib_current_category
        for folder_path in self.list_all_folders(cat):
            self._expanded_folders.setdefault(cat, set()).add(folder_path)
        self.refresh_library_list()

    def collapse_all_library_folders(self):
        cat = self.lib_current_category
        self._expanded_folders[cat] = set()
        self.refresh_library_list()

    def prompt_new_library_folder(self, parent_path=""):
        """Asks for a folder name and registers it (initially empty)
        under parent_path ("" = top level of the category)."""
        cat = self.lib_current_category
        if self._is_protected_folder(cat, parent_path):
            messagebox.showinfo("New folder", f"\"{CANONICAL_OUTFITS_FOLDER}\" is managed automatically.")
            return
        name = simpledialog.askstring("New folder", "Folder name:", parent=self.root)
        if not name:
            return
        full_path = self.create_new_folder(cat, parent_path, name)
        if full_path is None:
            messagebox.showwarning("New folder", "Folder name can't be empty or contain \"/\".")
            return
        self._expanded_folders.setdefault(cat, set()).add(full_path)
        self.refresh_library_list()

    def on_library_select(self, event=None):
        sel = self.tree_library.selection()
        entry_sel = [iid for iid in sel if not self._is_folder_iid(iid)]
        if not entry_sel:
            return
        if len(entry_sel) > 1:
            # Multi-selection is only meaningful for batch folder moves
            # (see _on_lib_tree_right_click). The single-entry editor below
            # stays on whatever was last opened rather than guessing.
            self.lbl_lib_status.configure(text=f"{len(entry_sel)} entries selected")
            return
        base = entry_sel[0]
        cat = self.lib_current_category
        content = self.read_file_content(cat, base)

        self.lib_selected_file = base
        self.txt_lib_tags.delete("1.0", tk.END)
        self.txt_lib_tags.insert("1.0", content)

        if cat == "outfits" and "_Canon_" in base:
            char_name, num = base.split("_Canon_")
            self.is_canon_var.set(True)
            self.combo_canon_char.configure(state="normal")
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
        self.tool_force_first_var.set(meta["force_first"])

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
        if hasattr(self, "tool_force_first_var"):
            self.tool_force_first_var.set(False)
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

        # Carry the source_url/lora/force_first metadata over to the copy too.
        old_meta = self.load_library_meta(cat, old_base)
        if old_meta["source_url"] or old_meta["lora"] or old_meta["force_first"]:
            self.save_library_meta(cat, new_name, source_url=old_meta["source_url"], lora=old_meta["lora"],
                                    force_first=old_meta["force_first"])

        # Carry the entry's virtual-folder placement over to the copy too.
        # Canon outfits are always auto-filed under Canonical Outfits
        # regardless of where the original lived (there's only ever one
        # such folder for the whole category — see _file_canon_outfit_into_folder).
        if cat == "outfits" and self.lib_editing_canon_owner:
            self._file_canon_outfit_into_folder(char_name, new_idx)
        else:
            old_folder = self.get_entry_folder(cat, old_base)
            if old_folder:
                self.set_entry_folder(cat, new_name, old_folder)

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
                    self.remove_entry_folder_entry("outfits", linked_base)
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
        self.remove_entry_folder_entry(cat, base)

        self.start_new_library_entry(keep_category=True)
        self.refresh_library_list()
        self.reload_all_lists()
        self.lbl_lib_status.configure(text=f"Deleted: {base}")

    # ---- Saving ----
    def save_to_library(self):
        cat = self.combo_lib_cat.get()
        tags = self.txt_lib_tags.get("1.0", tk.END).strip()

        # Tools are the one category where tags are genuinely optional —
        # a Tool entry might be nothing but a LoRA binding (e.g. an
        # anatomy-fix or hand-detailer LoRA with no text component at
        # all), unlike every other category where empty tags are almost
        # certainly a mistake, not a deliberate choice.
        if not tags and cat != "tools":
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
                self.rename_entry_folder_entry(cat, rename_from, os.path.splitext(filename)[0])
            if cat == "outfits" and self.is_canon_var.get():
                # Canon outfits are always auto-filed under the dedicated,
                # user-managed-nowhere-else Canonical Outfits folder —
                # never left wherever a same-named entry might have lived
                # before, and never something the user organizes by hand.
                canon_char, canon_num = (char_name, num) if is_editing_canon else (char_name, next_idx)
                self._file_canon_outfit_into_folder(canon_char, canon_num)
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
            self.save_library_meta(cat, saved_base, source_url=self.lib_source_url, lora=self.lib_entry_lora,
                                    force_first=self.tool_force_first_var.get())
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}")

    # ==========================================================
    #     LIBRARY FOLDERS — drag & drop + right-click "Move to..."
    # ==========================================================
    # Both interaction styles exist side by side on purpose: dragging a
    # single row onto a folder is the quickest path for a one-off move,
    # but it's easy to miss the drop target in a tree this dense, and it
    # doesn't cover multi-selection at all — so the context menu's
    # "Move to..." submenu is the reliable fallback for both cases, not
    # an alternative UI for the same thing.
    def _on_lib_tree_press(self, event):
        """Runs BEFORE ttk's native click handling (see the bindtags
        reorder in build_library_tab) so we can snapshot the selection
        the user actually made — Shift/Ctrl-clicked rows and all — before
        Tk's own class binding collapses a plain click on any one of
        those rows down to "just this row". If the click landed inside
        an existing multi-selection, we keep that whole selection and
        suppress the native collapse (return "break"); a click outside
        the current selection is left alone so normal single-click /
        Shift / Ctrl selection still works exactly as before."""
        iid = self.tree_library.identify_row(event.y)
        self._lib_drag_item = iid
        self._lib_drag_started = False
        current_sel = self.tree_library.selection()
        if iid and iid in current_sel and len(current_sel) > 1:
            # Multi-row press-to-drag: keep the existing selection intact
            # and don't let the native handler reduce it to one row.
            self._lib_drag_snapshot = current_sel
            return "break"
        self._lib_drag_snapshot = None
        return None

    def _on_lib_tree_drag(self, event):
        if not self._lib_drag_item:
            return
        self._lib_drag_started = True
        target = self.tree_library.identify_row(event.y)
        # Only ever highlight folders as drop targets — dropping an entry
        # "onto" another entry isn't a supported operation (no manual
        # ordering inside a folder, only alphabetical).
        if target and self._is_folder_iid(target):
            current = self._lib_drag_snapshot or self.tree_library.selection() or (self._lib_drag_item,)
            self.tree_library.selection_set(current)
            self.tree_library.see(target)

    def _on_lib_tree_drop(self, event):
        if not self._lib_drag_started:
            self._lib_drag_item = None
            self._lib_drag_snapshot = None
            return
        target = self.tree_library.identify_row(event.y)
        self._lib_drag_started = False
        self._lib_drag_item = None
        sel_source = self._lib_drag_snapshot or self.tree_library.selection()
        self._lib_drag_snapshot = None
        if not target or not self._is_folder_iid(target):
            return  # dropped on empty space or on another entry — no-op
        folder_path = self._folder_path_from_iid(target)
        sel = [iid for iid in sel_source if not self._is_folder_iid(iid)]
        if not sel:
            return
        self._move_selected_entries_to(folder_path, sel)

    def _move_selected_entries_to(self, folder_path, names):
        cat = self.lib_current_category
        if self._is_protected_folder(cat, folder_path):
            messagebox.showinfo("Move", f"\"{CANONICAL_OUTFITS_FOLDER}\" is managed automatically — "
                                         f"outfits are filed there only by marking them as canon.")
            return
        canon_in_selection = [n for n in names if cat == "outfits" and self.is_canon_outfit_name(n)]
        movable = [n for n in names if n not in canon_in_selection]
        moved = self.move_entries_to_folder(cat, movable, folder_path)
        # The destination folder (and every ancestor of it, for nested
        # paths) MUST stay open after a successful move — the user just
        # watched their entries land inside it, so collapsing it out from
        # under them would look like the move silently failed. This is
        # independent of whatever _on_library_folder_toggled happened to
        # record beforehand; a move always wins over prior click state.
        if moved and folder_path:
            expanded = self._expanded_folders.setdefault(cat, set())
            parts = folder_path.split(FOLDER_PATH_SEP)
            for depth in range(1, len(parts) + 1):
                expanded.add(FOLDER_PATH_SEP.join(parts[:depth]))
        self.refresh_library_list()
        # Keep the moved entries visibly selected so the user can see
        # exactly what just moved, instead of losing the selection the
        # instant the tree rebuilds.
        if movable:
            existing = [n for n in movable if self.tree_library.exists(n)]
            if existing:
                self.tree_library.selection_set(existing)
                self.tree_library.see(existing[0])
        label = folder_path if folder_path else "the category root"
        msg = f"Moved {moved} entr{'y' if moved == 1 else 'ies'} to {label}"
        if canon_in_selection:
            msg += f" ({len(canon_in_selection)} canon outfit(s) skipped — moved automatically only)"
        self.lbl_lib_status.configure(text=msg)

    def _on_lib_tree_right_click(self, event):
        iid = self.tree_library.identify_row(event.y)
        cat = self.lib_current_category
        menu = tk.Menu(self.root, tearoff=0)

        if iid and self._is_folder_iid(iid):
            folder_path = self._folder_path_from_iid(iid)
            protected = self._is_protected_folder(cat, folder_path)
            menu.add_command(label="📁＋ New subfolder here",
                              command=lambda: self.prompt_new_library_folder(folder_path))
            menu.add_separator()
            menu.add_command(label="✏ Rename folder", state="disabled" if protected else "normal",
                              command=lambda: self._rename_library_folder(folder_path))
            menu.add_command(label="🗑 Delete folder (move contents to root)",
                              state="disabled" if protected else "normal",
                              command=lambda: self._delete_library_folder(folder_path))
        else:
            # Right-clicking an entry (or empty space) operates on whatever
            # is currently selected, falling back to just this row if it
            # wasn't already part of the selection.
            sel = [i for i in self.tree_library.selection() if not self._is_folder_iid(i)]
            if iid and iid not in sel:
                self.tree_library.selection_set(iid)
                sel = [iid]
            # "New folder..." is always offered, even on empty space with
            # nothing selected — only "Move to..." actually needs entries.
            menu.add_command(label="📁＋ New folder…", command=self.prompt_new_library_folder)
            if sel:
                menu.add_separator()
                move_menu = tk.Menu(menu, tearoff=0)
                move_menu.add_command(label="(Category root)", command=lambda: self._move_selected_entries_to("", sel))
                existing_folders = [f for f in self.list_all_folders(cat) if not self._is_protected_folder(cat, f)]
                if existing_folders:
                    move_menu.add_separator()
                    for folder_path in existing_folders:
                        indent = "  " * folder_path.count(FOLDER_PATH_SEP)
                        label = indent + folder_path.split(FOLDER_PATH_SEP)[-1]
                        move_menu.add_command(label=label,
                                               command=lambda fp=folder_path: self._move_selected_entries_to(fp, sel))
                menu.add_cascade(label=f"📂 Move to… ({len(sel)} selected)" if len(sel) > 1 else "📂 Move to…",
                                  menu=move_menu)

        menu.tk_popup(event.x_root, event.y_root)

    def _rename_library_folder(self, folder_path):
        cat = self.lib_current_category
        old_name = folder_path.split(FOLDER_PATH_SEP)[-1]
        new_name = simpledialog.askstring("Rename folder", "Folder name:", initialvalue=old_name, parent=self.root)
        if not new_name or new_name == old_name:
            return
        if FOLDER_PATH_SEP in new_name:
            messagebox.showwarning("Rename folder", "Folder name can't contain \"/\".")
            return
        parent = FOLDER_PATH_SEP.join(folder_path.split(FOLDER_PATH_SEP)[:-1])
        new_path = f"{parent}{FOLDER_PATH_SEP}{new_name}" if parent else new_name
        # Re-point every entry (and nested subfolder) whose path starts
        # with the old folder path onto the new one.
        cat_map = self._folder_maps.get(cat, {})
        for entry_name, entry_folder in list(cat_map.items()):
            if entry_folder == folder_path:
                cat_map[entry_name] = new_path
            elif entry_folder.startswith(folder_path + FOLDER_PATH_SEP):
                cat_map[entry_name] = new_path + entry_folder[len(folder_path):]
        empty_set = self._empty_folders.get(cat, set())
        for p in list(empty_set):
            if p == folder_path:
                empty_set.discard(p)
                empty_set.add(new_path)
            elif p.startswith(folder_path + FOLDER_PATH_SEP):
                empty_set.discard(p)
                empty_set.add(new_path + p[len(folder_path):])
        expanded = self._expanded_folders.get(cat, set())
        if folder_path in expanded:
            expanded.discard(folder_path)
            expanded.add(new_path)
        self.save_folder_map()
        self.refresh_library_list()

    def _delete_library_folder(self, folder_path):
        cat = self.lib_current_category
        if not messagebox.askyesno(
                "Delete folder",
                f"Delete folder \"{folder_path}\"?\n\nEntries inside it (and any subfolders) "
                f"will move to the category root — nothing is deleted."):
            return
        cat_map = self._folder_maps.get(cat, {})
        for entry_name, entry_folder in list(cat_map.items()):
            if entry_folder == folder_path or entry_folder.startswith(folder_path + FOLDER_PATH_SEP):
                del cat_map[entry_name]
        empty_set = self._empty_folders.get(cat, set())
        for p in list(empty_set):
            if p == folder_path or p.startswith(folder_path + FOLDER_PATH_SEP):
                empty_set.discard(p)
        self._expanded_folders.get(cat, set()).discard(folder_path)
        self.save_folder_map()
        self.refresh_library_list()

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
        return sorted(result, key=natural_sort_key)

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

        for slot in self.active_tools:
            cur_tool = slot["tool_var"].get()
            tool_values = ["None"] + self.get_file_list("tools")
            slot["tool_combo"]["values"] = tool_values
            if cur_tool in tool_values:
                slot["tool_var"].set(cur_tool)
            else:
                slot["tool_var"].set("None")

        for slot in self.custom_active_tools:
            cur_tool = slot["tool_var"].get()
            tool_values = ["None"] + self.get_file_list("tools")
            slot["tool_combo"]["values"] = tool_values
            if cur_tool in tool_values:
                slot["tool_var"].set(cur_tool)
            else:
                slot["tool_var"].set("None")

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

        # ComfyUI generation details (Task: ComfyUI-aware history) — only
        # ever populated for entries created via add_comfy_history_entry()
        # (i.e. "Generate in ComfyUI" while connected). Packed in/out of
        # existence per-selection rather than just emptied, so a plain
        # text-only entry (comfy_connected=False at the time, or any
        # history predating this feature) looks exactly like it always
        # did — no empty "LoRA used:" label sitting there for nothing.
        self.frame_hist_comfy_details = ttk.Frame(right)
        self.lbl_hist_lora_used = ttk.Label(self.frame_hist_comfy_details, text="", style="Dim.TLabel",
                                             justify="left", anchor="w", wraplength=360)
        self.lbl_hist_lora_used.pack(fill="x", anchor="w")
        self.btn_hist_open_image = ttk.Button(self.frame_hist_comfy_details, text="🔍 Open image",
                                               command=self.open_selected_history_image)
        self.btn_hist_open_image.pack(fill="x", pady=(6, 0))

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
        self._refresh_history_comfy_details(entry)

    def _refresh_history_comfy_details(self, entry):
        """Shows/hides the LoRA-used label and Open image button for the
        currently selected entry. Both are entirely absent (not just
        empty) for a plain text-only entry, so the History tab looks
        identical to its pre-ComfyUI-aware-history appearance whenever
        there's nothing ComfyUI-specific to show."""
        lora_used = entry.get("lora_used")
        image_ref = entry.get("image_ref")
        if not lora_used and not image_ref:
            self.frame_hist_comfy_details.pack_forget()
            return

        if lora_used:
            parts = []
            for lora in lora_used:
                tag = "[A]" if lora.get("auto") else "[M]"
                parts.append(f"{tag} {lora.get('name', '?')} ({lora.get('strength', 1.0):g})")
            self.lbl_hist_lora_used.configure(text="LoRA used: " + ", ".join(parts))
            self.lbl_hist_lora_used.pack(fill="x", anchor="w")
        else:
            self.lbl_hist_lora_used.pack_forget()

        if image_ref:
            self.btn_hist_open_image.configure(state="normal", text="🔍 Open image")
            self.btn_hist_open_image.pack(fill="x", pady=(6, 0))
        else:
            # A LoRA-only entry (job failed/was stopped before an image
            # existed — see _on_comfy_generation_failed's comment) still
            # shows the LoRA line above, but there's nothing to open.
            self.btn_hist_open_image.pack_forget()

        self.frame_hist_comfy_details.pack(fill="x", pady=(8, 0), before=self.btn_hist_fav.master)

    def open_selected_history_image(self):
        """'🔍 Open image' — same logic as the Gallery's magnifier/click-
        to-open (_gallery_open_full_view), reused as-is via the shared
        (local_path, remote_filename, remote_subfolder) entry shape, so
        "last known good link" resolution behaves identically in both
        places. If the file's gone (deleted/renamed in ComfyUI's output,
        or the session-only local cache was wiped by a restart), this
        just reports that — there's no thumbnail to fall back to, by
        design (see the feature discussion: a missing image here is the
        user's own bookkeeping problem, not something to preview around)."""
        res = self._get_selected_history_entry()
        if not res:
            return
        _, entry = res
        image_ref = entry.get("image_ref")
        if not image_ref:
            return
        self._gallery_open_full_view(image_ref)

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
        self.frame_hist_comfy_details.pack_forget()

    def add_to_history(self, text, favorite=False, lora_used=None, image_ref=None):
        """Creates a new history entry.

        lora_used / image_ref are populated only by the ComfyUI-submission
        path (see add_comfy_history_entry / _attach_image_to_history_entry
        below) — plain "Generate prompt and copy" entries never set them,
        so existing history files and the disconnected-ComfyUI flow are
        unaffected. Returns the new entry's id, so a caller that needs to
        update it later (attaching the image once generation finishes)
        doesn't have to fall back to fragile text matching."""
        entry = {
            "id": str(uuid.uuid4()),
            "text": text,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
            "favorite": favorite,
        }
        if lora_used:
            entry["lora_used"] = lora_used
        if image_ref:
            entry["image_ref"] = image_ref
        self.history.insert(0, entry)
        # cap history at a reasonable size
        self.history = self.history[:200]
        self.save_json(self.HISTORY_FILE, self.history)
        self.refresh_history_list()
        return entry["id"]

    def add_comfy_history_entry(self, prompt_text, lora_slots_snapshot):
        """Creates the ComfyUI-connected history entry for a generation
        that has just been added to the local queue (see
        on_generate_in_comfy_clicked — called once per click, at enqueue
        time, not once per "this is now the active job").

        Builds lora_used from lora_slots_snapshot — the exact snapshot
        taken on the main thread at the moment of the click, frozen into
        this queue item — so it can never drift from what will actually
        be patched into the graph even if the user nudges a strength
        slider for some OTHER, later click while this one is still
        waiting its turn. Only slots with a real LoRA selected are kept;
        empty (LORA_NONE_VALUE) slots add nothing worth showing in history.

        Returns the new entry's id WITHOUT touching
        self._comfy_current_history_id — that attribute tracks "the
        history entry for whichever job is currently in flight with
        ComfyUI", which is a different thing from "the entry just
        created for a click that might still be sitting in the queue
        behind others". Setting it here would mean queuing several items
        in a row leaves it pointing at the LAST one clicked rather than
        the FIRST one actually running, silently misattaching the
        eventual image. The caller (on_generate_in_comfy_clicked) stores
        this id in the queue item itself; _start_comfy_generation is the
        only place that later copies it into _comfy_current_history_id,
        exactly when that specific item's turn comes up."""
        lora_used = [
            {"name": slot["name"], "strength": slot.get("strength", 1.0), "auto": bool(slot.get("auto"))}
            for slot in lora_slots_snapshot
            if (slot.get("name") or LORA_NONE_VALUE) != LORA_NONE_VALUE
        ]
        return self.add_to_history(prompt_text, lora_used=lora_used or None)

    def _attach_image_to_history_entry(self, local_path, remote_filename, remote_subfolder):
        """Patches image_ref into the history entry created by
        add_comfy_history_entry() for the job that just finished,
        matched by id (self._comfy_current_history_id) — set to None
        whenever there's no such entry (ComfyUI wasn't connected at
        submit time, or the entry was somehow not created), in which
        case this is a no-op rather than guessing at a fallback target."""
        if not self._comfy_current_history_id:
            return
        for entry in self.history:
            if entry.get("id") == self._comfy_current_history_id:
                entry["image_ref"] = {
                    "local_path": local_path,
                    "remote_filename": remote_filename,
                    "remote_subfolder": remote_subfolder or "",
                }
                self.save_json(self.HISTORY_FILE, self.history)
                self.refresh_history_list()
                break

    def favorite_last(self):
        if not self._last_generated:
            messagebox.showinfo("Favorite", "First generate a prompt.")
            return
        # When ComfyUI is connected, _finalize_generated_prompt() no longer
        # writes a history entry at all (see its docstring) — so history[0]
        # routinely won't match _last_generated here, and the else branch
        # below (a fresh text-only entry, no LoRA/image data yet) is the
        # expected path, not a rare edge case. That's fine: favoriting a
        # prompt before submitting it to ComfyUI is a deliberate "Generate
        # prompt and copy" + "Favorite" combo that was never going to have
        # LoRA/image data anyway (that only exists once a generation has
        # actually run — see add_comfy_history_entry()).
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

        def _on_gallery_mousewheel(event):
            # Robust to both a regular mouse wheel (delta in multiples of
            # 120) and a trackpad (much smaller, more frequent delta
            # values) — int(-delta/120) would silently round down to 0
            # for small trackpad deltas and do nothing, so this guarantees
            # at least 1 unit of scroll in the right direction whenever
            # delta is nonzero, while still scaling up for a real wheel's
            # bigger jumps.
            units = max(1, abs(event.delta) // 120) if abs(event.delta) >= 120 else 1
            direction = -1 if event.delta > 0 else 1
            self.gallery_canvas.yview_scroll(direction * units, "units")

        # Scoped to the canvas via Enter/Leave, not bind_all, so it can't
        # fight with any other scroll area on screen.
        self.gallery_canvas.bind("<Enter>", lambda e: self.gallery_canvas.bind_all(
            "<MouseWheel>", _on_gallery_mousewheel))
        self.gallery_canvas.bind("<Leave>", lambda e: self.gallery_canvas.unbind_all("<MouseWheel>"))

        self.gallery_cells = []  # ttk.Frame widgets, kept 1:1 with self.gallery_entries
        self._gallery_relayout_pending = None  # after_idle id for the debounced relayout below

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
        # Tracked explicitly rather than via winfo_ismapped() later (see
        # _gallery_add_cell) — that call can report False for a widget
        # that's logically still showing via grid() but has never been
        # physically mapped on screen yet (e.g. the very first image
        # generated before the Gallery tab was ever clicked into), which
        # silently skipped hiding it.
        self._gallery_placeholder_hidden = False

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
        if not self._gallery_placeholder_hidden:
            self.gallery_placeholder.grid_forget()
            self._gallery_placeholder_hidden = True
        cell = self._gallery_build_cell(self.gallery_scroll_frame, entry)
        self.gallery_cells.append(cell)
        self._gallery_relayout()
        self._gallery_update_count_label()

    def _gallery_relayout(self, event=None):
        """Debounced entry point — schedules _gallery_relayout_now() on
        the next idle pass instead of running it synchronously here.

        Without this, a burst of rapid <Configure> events on the canvas
        (window resize, sash drag, or several cells being added back to
        back via _gallery_add_cell) each triggered an *immediate*
        re-grid of every cell plus a full update_idletasks() + bbox("all")
        scan, synchronously, inside whatever Tk callback produced the
        event. On a tightly-constrained window (smaller/non-native DPI
        scaling, less slack to settle into) that's the same
        geometry-calculation bottleneck _suspend_left_scrollregion_updates()
        already guards against for the Builder's left column (see that
        method's docstring) — this mirrors the same debounce-and-coalesce
        pattern here for the Gallery/Library grid. Cancelling any pending
        call before scheduling a new one means a rapid burst collapses
        into exactly one real relayout once things settle, instead of
        running once per event.
        """
        if self._gallery_relayout_pending is not None:
            self.root.after_cancel(self._gallery_relayout_pending)
        self._gallery_relayout_pending = self.root.after_idle(self._gallery_relayout_now)

    def _gallery_relayout_now(self):
        """Recomputes how many columns fit in the canvas's current width
        and re-grids every existing cell — cells themselves are never
        rebuilt, just moved, so this is cheap enough to call on every
        resize.

        Explicitly recalculates the canvas's scrollregion at the end,
        rather than relying solely on gallery_scroll_frame's own
        <Configure> binding to catch up — that binding's event can fire
        with the frame's PRE-relayout size if Tk hasn't fully finished
        recomputing geometry for every just-re-gridded cell yet, which
        is exactly what made scrolling down stop reaching newer rows
        once there were enough images to span multiple screens' worth:
        the scrollregion silently stayed pinned to an earlier, smaller
        height. update_idletasks() forces Tk to finish that geometry
        pass before bbox("all") is read, so the number is always
        accurate for what was actually just laid out."""
        self._gallery_relayout_pending = None
        if not getattr(self, "gallery_cells", None):
            return
        canvas_w = self.gallery_canvas.winfo_width()
        cols = max(1, canvas_w // GALLERY_CELL_OUTER_WIDTH)
        for i, cell in enumerate(self.gallery_cells):
            r, col = divmod(i, cols)
            cell.grid(row=r, column=col, padx=10, pady=10, sticky="n")
        self.gallery_canvas.update_idletasks()
        self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all"))

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

    def _build_tools_block(self, active_tools):
        """Returns (force_first_text, regular_text) for the active Tools
        slots. Tools marked "force to start of prompt" in the Library
        (see load_library_meta's force_first) are pulled out into their
        own string, joined and returned separately so generate_standard_
        prompt can place them at the very front of the assembled prompt,
        ahead of block_order entirely — a tag like "@fixedanatomy" needs
        to reach the model before anything else, regardless of whatever
        order the user has Style/Characters/Scenario in. Every other
        active Tool's tags go into regular_text instead, which slots into
        block_order exactly like Style/Characters/Scenario do.

        A Tool entry with empty tags (pure LoRA binding, no text
        component at all — see the Tools feature discussion) contributes
        an empty string to whichever bucket it would have landed in,
        which simply drops out when the pieces are joined — its LoRA
        still gets pulled in separately via the existing library-LoRA
        auto-fill machinery, this function only ever deals with prompt
        text."""
        force_first_parts = []
        regular_parts = []
        for slot in active_tools:
            tool_name = slot["tool_var"].get()
            if not tool_name or tool_name == "None":
                continue
            tags = self.read_file_content("tools", tool_name)
            if not tags:
                continue
            if self.load_library_meta("tools", tool_name)["force_first"]:
                force_first_parts.append(tags)
            else:
                regular_parts.append(tags)
        return ", ".join(force_first_parts), ", ".join(regular_parts)

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

        force_first_tools, regular_tools = self._build_tools_block(self.active_tools)

        blocks = {}
        blocks["style"] = self._build_style_block(valid_chars_count)
        blocks["characters"] = self._build_characters_block(valid_chars)
        blocks["scenario"] = self._build_scenario_block()
        blocks["tools"] = regular_tools

        paragraphs = [blocks[key] for key in self.block_order if blocks.get(key, "").strip()]
        # force_first_tools bypasses block_order entirely — see
        # _build_tools_block's docstring. Always the very first paragraph
        # of the assembled prompt, no matter how Style/Characters/
        # Scenario/Tools are ordered, since a tag like "@fixedanatomy"
        # needs to reach the model before anything else does.
        if force_first_tools.strip():
            paragraphs.insert(0, force_first_tools)
        final_prompt = "\n\n".join(paragraphs)

        if not final_prompt.strip():
            messagebox.showinfo("Empty prompt", "Select at least one style, character, scenario, or tool.")
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
        text.

        History recording (Task: ComfyUI-aware history):
        when ComfyUI is connected, this step intentionally does NOT write
        a history entry. With LoRA Manager active, "Generate prompt and
        copy" is typically just an intermediate step before the user
        fine-tunes LoRA strengths and clicks "Generate in ComfyUI" —
        writing history here would either miss the LoRA/image data
        entirely or require matching this entry up with a later one by
        text, which breaks the moment the user hand-edits txt_output
        in between (a case the rest of the app explicitly supports).
        Instead, the ComfyUI-connected history entry is created fresh,
        complete with its LoRA snapshot, at the moment of the click —
        see add_comfy_history_entry(), called from
        on_generate_in_comfy_clicked() right when the item is queued, not
        when it's actually submitted to ComfyUI (which may happen much
        later if other items are ahead of it in the queue).
        When ComfyUI is NOT connected, there is no later submission step
        to defer to, so history is recorded right here, exactly as before."""
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", final_prompt)
        self._last_generated = final_prompt
        if not self.comfy_connected:
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
            # Custom Templates' own Tools slots (only present if the
            # template text actually uses [Tool] — see
            # build_custom_template_form). This was the gap from the
            # Custom-templates-forgot-Tools report: a Tool entry's whole
            # reason for existing is often its bound LoRA, with no text
            # at all, so without this it would never get picked up here.
            for slot in self.custom_active_tools:
                add("tools", slot["tool_var"].get())
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
            for slot in self.active_tools:
                add("tools", slot["tool_var"].get())

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
        added/removed via _lora_add_slot()/_lora_remove_slot().

        Wrapped in _suspend_left_scrollregion_updates(): destroying and
        recreating every slot frame in one go is exactly the kind of
        pack_forget()/pack() burst that method exists to coalesce (see
        its docstring) — each destroy()/pack() fires its own <Configure>
        on left_content, and without suspending, that burst gets fully
        dispatched (even though the expensive bbox("all") recalculation
        itself is debounced) before settling. On a tightly-constrained
        window (smaller/non-native DPI scaling, less slack to settle
        into) this is the same geometry-calculation bottleneck that
        _on_comfy_check_done already guards against — _build_lora_slots
        runs just as often (every "Generate" while connected, via
        _lora_autofill_from_library) and was missing the same guard.
        """
        with self._suspend_left_scrollregion_updates():
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
        # Recomputes the Library tab's green/yellow/red LoRA-status row
        # coloring now that there's an actual list to compare against —
        # see refresh_library_list/_compute_lora_status_for_category.
        if hasattr(self, "tree_library"):
            self.refresh_library_list()

    def on_comfy_toggle(self):
        """Handles the "ComfyUI connected?" checkbox. Runs the health
        check off the main thread so a dead/unreachable ComfyUI doesn't
        freeze the UI for COMFY_HTTP_TIMEOUT seconds."""
        if not self.comfy_enabled.get():
            self.comfy_connected = False
            with self._suspend_left_scrollregion_updates():
                self.frame_comfy_options.pack_forget()
                self.frame_comfy_result.pack_forget()
                self.frame_lora.pack_forget()
                self.btn_generate_comfy.pack_forget()
                self.btn_comfy_stop.pack_forget()
                self.frame_comfy_queue_row.pack_forget()
                self.frame_neg_prompt.pack_forget()
            self.lbl_comfy_status.configure(text="")
            self._refresh_lib_lora_visibility()
            if hasattr(self, "tree_library"):
                self.refresh_library_list()
            # Explicitly disconnecting ComfyUI also drops any PENDING
            # queue items — leaving them sitting around would mean they
            # could silently resume the moment the user reconnects, which
            # isn't what "turn ComfyUI off" means to someone clicking that
            # checkbox. Whatever's already in flight isn't touched here
            # (its worker thread keeps running either way, same as
            # before this feature existed); this only clears what hadn't
            # started yet.
            if self._comfy_queue:
                self._comfy_queue.clear()
                self._refresh_comfy_queue_label()
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
            with self._suspend_left_scrollregion_updates():
                self.frame_comfy_options.pack_forget()
                self.frame_comfy_result.pack_forget()
                self.frame_lora.pack_forget()
                self.btn_generate_comfy.pack_forget()
                self.btn_comfy_stop.pack_forget()
                self.frame_comfy_queue_row.pack_forget()
                self.frame_neg_prompt.pack_forget()
            self.lbl_comfy_status.configure(text=f"✗ {error_msg}")
            self._refresh_lib_lora_visibility()
            if hasattr(self, "tree_library"):
                self.refresh_library_list()
            if self._comfy_queue:
                self._comfy_queue.clear()
                self._refresh_comfy_queue_label()
            messagebox.showerror("ComfyUI", f"Could not connect to ComfyUI:\n{error_msg}")
            return

        self.comfy_connected = True
        self.comfy_output_dir = out_dir
        self._refresh_lib_lora_visibility()
        with self._suspend_left_scrollregion_updates():
            self.frame_comfy_options.pack(fill="x")
            self.frame_comfy_result.pack(fill="x", pady=(10, 0))
            # Deferred (not called synchronously here): lets Tk finish its
            # own pending geometry pass for the widgets just packed above
            # before we go measuring/resizing them on top of that —
            # forcing it all through immediately via update_idletasks() in
            # the same callback is exactly the kind of thing that can
            # misbehave on a tightly-constrained (small) window where
            # there's little slack to settle into.
            self.root.after_idle(self._resize_comfy_result_zone)

            if workflow_ok:
                self.lbl_comfy_status.configure(text="✓ Connected — graph ready")
                self.btn_generate_comfy.pack(side="left", fill="x", expand=True, padx=(8, 0))
                # Show LoRA section between frame_comfy and actions_frame.
                # Re-pack in correct order to ensure LoRA sits right below ComfyUI block.
                self.frame_neg_prompt.pack_forget()
                self.frame_lora.pack_forget()
                self.actions_frame.pack_forget()
                self.frame_comfy_queue_row.pack_forget()
                self.frame_neg_prompt.pack(fill="x", padx=(0, 10), pady=6)
                self.frame_lora.pack(fill="x", padx=(0, 10), pady=6)
                self.actions_frame.pack(fill="x", padx=(0, 10), pady=(10, 0))
                self.frame_comfy_queue_row.pack(fill="x", padx=(0, 10), pady=(4, 0))
                self._refresh_comfy_queue_label()
                # Kick off background fetch of available LoRAs
                self._fetch_available_loras()
            else:
                self.lbl_comfy_status.configure(
                    text="⚠ Connected — open ComfyUI in browser with the node in your graph")
                self.btn_generate_comfy.pack_forget()
                self.btn_comfy_stop.pack_forget()
                self.frame_comfy_queue_row.pack_forget()
                self.frame_neg_prompt.pack_forget()
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
        edited after generating) and submits exactly that.

        Task: generation queue. This click ALWAYS succeeds (appends to
        self._comfy_queue) rather than refusing when comfy_busy is True —
        comfy_busy is now purely a status flag ("ComfyUI is generating
        something right now"), not a gate on accepting new requests. Every
        parameter this generation will need is snapshotted right here, on
        the main thread, at the moment of the click — seed, resolution,
        negative prompt, and the LoRA Manager's current slot values — so
        a later click that changes a LoRA strength can never retroactively
        affect a generation that's already sitting in the queue (see the
        queue feature discussion: "if LoRA/strength change between queue
        entries, each entry keeps its own values").

        A new history entry is also created right here, at click time —
        not when this item's turn comes up to actually be submitted to
        ComfyUI. That keeps the queue item and its history entry tied
        together by a single id from the moment both are created, with
        nothing left to match up (by text or otherwise) once the queue
        actually gets around to running it."""
        now = time.time()
        if now < self._comfy_queue_debounce_until:
            return  # absorbs a panicked double/triple-click on the same press
        self._comfy_queue_debounce_until = now + (COMFY_QUEUE_DEBOUNCE_MS / 1000.0)

        prompt_text = self.txt_output.get("1.0", tk.END).strip()
        if not prompt_text:
            messagebox.showinfo(
                "Empty prompt",
                "Generate a prompt first (or type one into the result box).")
            return

        # Seed (resolve now — a "random" mode pick is frozen into this
        # queue item, not re-rolled later when it's actually submitted).
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
            width = int(self.comfy_width_var.get().strip())
            height = int(self.comfy_height_var.get().strip())
            if width <= 0 or height <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid resolution",
                                    "Width and height must be positive whole numbers.")
            return

        # Validate LoRA Manager slots before queueing. Only meaningful
        # here — "Generate prompt and copy" never touches ComfyUI.
        missing_loras = [
            entry["name"] for entry in self._lora_slots_data
            if entry.get("name", LORA_NONE_VALUE) != LORA_NONE_VALUE
            and entry["name"] not in self._available_loras
        ]
        if missing_loras:
            if not self._available_loras:
                self.lbl_comfy_result_status.configure(
                    text="⚠ LoRA list not loaded yet — skipping LoRA validation.")
            else:
                messagebox.showerror(
                    "Missing LoRA",
                    "Следующие LoRA не найдены в ComfyUI:\n"
                    + "\n".join(f"- {name}" for name in missing_loras))
                return

        # LoRA slots — this queue item's own permanent snapshot.
        lora_slots_snapshot = list(self._lora_slots_data)

        # Negative prompt
        if self.combo_template_category.get() == "Custom" and \
                hasattr(self, "txt_neg_prompt_custom") and \
                self.txt_neg_prompt_custom.winfo_exists():
            negative_text = self.txt_neg_prompt_custom.get("1.0", tk.END).strip()
        else:
            negative_text = self.txt_neg_prompt.get("1.0", tk.END).strip() \
                if hasattr(self, "txt_neg_prompt") else ""

        history_id = self.add_comfy_history_entry(prompt_text, lora_slots_snapshot)

        queue_item = {
            "prompt_text": prompt_text,
            "seed": seed,
            "width": width,
            "height": height,
            "negative_text": negative_text,
            "lora_slots_snapshot": lora_slots_snapshot,
            "history_id": history_id,
        }
        self._comfy_queue.append(queue_item)
        self._refresh_comfy_queue_label()
        self._maybe_start_next_queued_generation()

    def _refresh_comfy_queue_label(self):
        """Updates the small queue-count indicator next to the Generate
        button. Shown even at 0 so the control is never just absent —
        consistent visual feedback that the click landed, which matters
        most exactly when someone's clicking rapidly and unsure whether
        anything happened (see the queue feature discussion).

        Distinguishes "something is already generating, N more are
        queued behind it" from "nothing running, N waiting to start" —
        collapsing these into one plain count (e.g. always just "N
        queued") was misleading: clicking 3 times while a job was
        already mid-generation showed "3 queued", reading as if only 3
        generations total were pending, when really there are 4 (the
        one running plus the 3 behind it)."""
        n = len(self._comfy_queue)
        if hasattr(self, "lbl_comfy_queue_count"):
            if self.comfy_busy and n > 0:
                text = f"📋 generating + {n} queued"
            elif self.comfy_busy:
                text = "📋 generating"
            elif n > 0:
                text = f"📋 {n} queued"
            else:
                text = ""
            self.lbl_comfy_queue_count.configure(text=text)
        if hasattr(self, "btn_comfy_clear_queue"):
            self.btn_comfy_clear_queue.configure(state="normal" if n else "disabled")

    def clear_comfy_queue(self):
        """'🗑 Clear queue' — removes every PENDING item, matching native
        ComfyUI's own "Clear queue" behavior: it never touches whatever
        is currently sampling. To stop the active job too, Stop is a
        separate, deliberate action (see on_comfy_stop_clicked) — the two
        combine (Stop + Clear) rather than one button trying to mean
        both "cancel everything" at once."""
        n = len(self._comfy_queue)
        if n == 0:
            return
        if not messagebox.askyesno(
                "Clear queue",
                f"Remove {n} pending generation(s) from the queue?\n\n"
                f"The one currently generating (if any) keeps running — "
                f"use Stop for that."):
            return
        self._comfy_queue.clear()
        self._refresh_comfy_queue_label()
        self.lbl_comfy_result_status.configure(text="Queue cleared.")

    def _maybe_start_next_queued_generation(self):
        """Pops the next item off the local queue and submits it, but
        only if ComfyUI isn't already busy with a previous one — this is
        the one place that keeps exactly one job in flight with ComfyUI
        at a time (see the queue feature discussion on why a strictly
        sequential, app-managed queue was chosen over firing every queued
        item at ComfyUI's own server-side queue at once: it keeps the
        existing live-preview/progress pipeline meaningful — there's
        never any ambiguity about whose preview frame is currently
        streaming in). Called after every enqueue and after every
        completion/failure/stop, so the queue drains itself automatically."""
        if self.comfy_busy or not self._comfy_queue:
            return
        queue_item = self._comfy_queue.pop(0)
        self._start_comfy_generation(queue_item)
        self._refresh_comfy_queue_label()

    def _show_comfy_stop_button(self):
        """Packs the separate Stop button in next to btn_generate_comfy
        once ComfyUI has accepted the job (i.e. submit_prompt() returned
        a prompt_id). btn_generate_comfy itself is left completely
        alone — still saying "Generate in ComfyUI", still clickable —
        so the queue keeps accepting new items while this one runs."""
        if not self.comfy_busy:
            return  # job already finished/failed/was stopped before this fired
        self.btn_comfy_stop.configure(state="normal", text="⏹ Stop")
        self.btn_comfy_stop.pack(side="left", padx=(8, 0))

    def _restore_comfy_generate_button(self):
        """Hides the Stop button once a job has ended (success, failure,
        or user-initiated stop). btn_generate_comfy was never touched in
        the first place, so there's nothing to restore on it — this only
        existed historically from when Stop was a second state of that
        same button; kept as its own method since both completion
        handlers already call it by this name."""
        self.btn_comfy_stop.pack_forget()

    def on_comfy_stop_clicked(self):
        """Handler for "⏹ Stop". Sends a real POST /interrupt to ComfyUI
        so the GPU actually stops sampling — this is not just a local
        "give up waiting" cancel. Also tries to dequeue the same
        prompt_id in case it hadn't started executing yet (still queued
        behind another job), since /interrupt only ever affects whatever
        is currently running.

        Both calls are best-effort and run on a background thread (they're
        blocking HTTP calls) — wait_for_completion()'s should_cancel flag
        is set unconditionally afterwards regardless of whether the HTTP
        calls succeeded, so the UI always stops waiting even if ComfyUI
        is unreachable right at this moment."""
        if not self.comfy_busy or self._comfy_stopping:
            return
        self._comfy_stopping = True
        self.btn_comfy_stop.configure(state="disabled", text="Stopping…")
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
    def _start_comfy_generation(self, queue_item):
        """Submits one already-fully-snapshotted queue item to ComfyUI.
        Called only by _maybe_start_next_queued_generation, which is the
        sole gate ensuring exactly one of these runs at a time — by the
        time this method runs, comfy_busy is about to become True and
        every parameter below was already decided back when the user
        clicked "Generate in ComfyUI" (see on_generate_in_comfy_clicked),
        not re-read from the current UI state, which may have moved on
        to preparing a completely different queued item by now.

        The graph fetch is the only blocking network call that happens on
        the main thread here — it's fast (local HTTP), but we wrap it in
        the same background worker as the rest of the generation pipeline."""
        prompt_text = queue_item["prompt_text"]
        seed = queue_item["seed"]
        width = queue_item["width"]
        height = queue_item["height"]
        negative_text = queue_item["negative_text"]
        lora_slots_snapshot = queue_item["lora_slots_snapshot"]

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
        # The history entry for this generation was already created back
        # at enqueue time (on_generate_in_comfy_clicked) — its id travels
        # with the queue item itself, so there's nothing to look up here.
        self._comfy_current_history_id = queue_item["history_id"]
        self._comfy_stopping = False
        # btn_generate_comfy is deliberately left alone here (not
        # disabled) — it must stay clickable throughout so the queue
        # keeps accepting new items while this job submits/runs. Stop is
        # its own separate button (see _show_comfy_stop_button), shown
        # once submit_prompt() below actually returns a prompt_id —
        # there's nothing to interrupt before ComfyUI has accepted the job.
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
                # to gate on this side. Note this also naturally covers a
                # workflow with several samplers chained together (e.g. a
                # base pass, then an upscale pass, then a hand-detailer
                # pass): ComfyUI streams a preview frame for whichever
                # sampler is currently running, and this callback just
                # keeps showing whatever the most recent frame was —
                # there's nothing queue-specific to add for that, it was
                # already true before this feature and still is.
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

        # History (ComfyUI-aware entries only): attach this result to the
        # entry created in add_comfy_history_entry() back when this item
        # was added to the queue, by id — never by matching prompt text,
        # which would silently fail or mismatch the moment the user
        # hand-edits txt_output between generations, or queues several
        # generations with identical text but different LoRA strengths.
        # Stored as the same (local_path, remote_filename,
        # remote_subfolder) triple as the Gallery entry above, on purpose:
        # "Open image" in History and the magnifier in Gallery then both
        # resolve through the identical _gallery_resolve_target() logic,
        # with no separate path-resolution rule to maintain.
        self._attach_image_to_history_entry(
            local_path=image_path,
            remote_filename=self.comfy_last_remote_filename,
            remote_subfolder=self.comfy_last_remote_subfolder,
        )
        self._comfy_current_history_id = None

        # Hide progress bar, reset it
        self.frame_comfy_progress.pack_forget()
        self.comfy_progress_var.set(0.0)
        self.lbl_comfy_progress.configure(text="")
        self._resize_comfy_result_zone()

        # Show Open folder button now that there's something to open
        self.btn_comfy_open_folder.pack(side="right")

        # Task: generation queue. If there's a next item waiting, this is
        # the one place that starts it automatically — comfy_busy just
        # went False above, so the gate in
        # _maybe_start_next_queued_generation() will let it through.
        self._maybe_start_next_queued_generation()

    def _on_comfy_generation_failed(self, error_msg):
        was_user_stop = self._comfy_stopping
        self.comfy_busy = False
        self._comfy_current_prompt_id = None
        self._comfy_stopping = False
        # The history entry created in add_comfy_history_entry() back when
        # this item was queued is deliberately left as-is on Stop/failure —
        # text + LoRA snapshot, no image_ref — rather than deleted. It
        # still records what was attempted and with which LoRAs even
        # though nothing was produced; that's strictly more useful than
        # silently losing the record. Just stop tracking it as "the
        # in-flight job's entry".
        self._comfy_current_history_id = None
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

        # Task: generation queue. A stop or a failure only ever cancels
        # THIS position — exactly like clicking the ✕ on one item in
        # ComfyUI's own queue, or that item simply erroring out there.
        # Whatever's still queued behind it keeps going automatically,
        # the same way ComfyUI's own server-side queue doesn't halt just
        # because one job failed.
        self._maybe_start_next_queued_generation()

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


def _install_crash_logger(root):
    """Tkinter's default behavior for an exception raised inside any
    callback (button command, event binding, after() callback, etc.) is
    to print the traceback to stderr and otherwise keep running — but
    when the app is launched without a console attached (pythonw.exe,
    a packaged --windowed .exe), stderr goes nowhere and the failure is
    completely invisible: the UI can freeze or visibly misbehave with
    zero diagnostic output anywhere. This installs a replacement that
    also appends the full traceback, with a timestamp, to
    prompt_forge_crash.log next to the program — so a crash that's hard
    to pin down from reproduction steps alone (e.g. only at certain
    window widths) leaves an exact file/line to look at instead."""
    import traceback as _traceback

    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_forge_crash.log")

    def _handler(exc_type, exc_value, exc_tb):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 70}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                _traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass  # logging must never itself crash the app
        # Still print to stderr too, for anyone running from a console.
        _traceback.print_exception(exc_type, exc_value, exc_tb)

    root.report_callback_exception = _handler


if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    _install_crash_logger(root)
    app = PromptForgeApp(root)
    root.mainloop()

