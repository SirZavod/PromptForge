# ⚡ PromptForge

A desktop app for building AI image-generation prompts out of reusable
building blocks — **styles**, **characters**, **outfits**, **scenarios**,
and **tools** — instead of retyping the same tags every time, and for
driving those prompts straight into a running **ComfyUI** instance with
a generation queue, live preview, LoRA management, and a results gallery.

![PromptForge — Builder tab](screenshots/01-builder.png)

## Features

- **Standard builder** — pick a style, add any number of characters with their outfits, pick a scenario, and optionally add tools (anatomy fixers, detailers, or anything that's mostly a bound LoRA with little or no prompt text), then generate a ready-to-paste prompt with one click. Reorder the assembled blocks (style / characters / scenario / tools) however you like, and save your favorite orderings as reusable templates.
- **Tools** — a library category for entries that are mostly (or entirely) about a bound LoRA rather than prompt text — anatomy fixers, hand detailers, sharpness boosts, anything Stable Diffusion effectively needs a helper LoRA for. Unlike every other category, a Tool can be saved with completely empty tags. A Tool's tag can optionally be marked "force to the very start of the prompt", for tools that trigger specific behavior (e.g. `@fixedanatomy`) and need to land ahead of everything else regardless of how the rest of the prompt is ordered. Available in both the Standard builder and Custom templates (via the `[Tool]` variable).
- **Custom templates** — write your own prompt skeleton with placeholders like `[Name 1]`, `[Description 1]`, `[Outfit 1]`, `[Style]`, `[Scenario]`, `[Tool]`, and fill them in from dropdowns each time you generate.
- **Direct ComfyUI generation with a queue** — connect to a running ComfyUI instance (via the companion custom node) and send your assembled prompt straight to it with **🎨 Generate in ComfyUI**, no copy-pasting. Every click queues a generation (with its own frozen snapshot of LoRAs/strengths/seed) rather than refusing while something's already running — a separate **⏹ Stop** button cancels only the one currently in progress, and **🗑 Clear queue** drops everything still waiting (never the one already generating, matching ComfyUI's own queue UI). Watch live preview frames while it samples, and get the finished image back in the Builder tab and the Gallery. Prefer to just build the text? **⚡ Generate prompt and copy** still does that, with or without ComfyUI connected. See [Connecting to ComfyUI](#connecting-to-comfyui) below.
- **LoRA Manager** — attach LoRAs to a generation either manually or automatically (pulled from whichever library entries — characters, outfits, styles, tools — are bound to one), tagged `[M]`(manual lora)/`[A]`(automatical lora) so you always know which is which. Validated against ComfyUI's live LoRA list before every submit, so a missing file is caught up front instead of silently skipping. Collapsible, and your slots/strengths persist between sessions.
- **Library manager** — a built-in editor for your styles, scenarios, characters, outfits, and tools, with search, per-character "canon" outfits, an optional source URL per entry (for crediting/finding the original model or reference), and an optional bound LoRA (used by the LoRA Manager's auto slots). While connected to ComfyUI, entries with a bound LoRA are color-coded right in the list — green if it's found, yellow if a same-named file was found elsewhere (worth double-checking), red if nothing matching exists at all.
- **LoRA dependency checking** — a one-click scan of your whole library against ComfyUI's current LoRA list, so you can confirm everything a downloaded library expects is actually in place before generating dozens of characters, not after a confusing result on one of them. If something's missing, it can search for a same-named file elsewhere and offer it as a candidate — applied one at a time with your confirmation, or all at once if every candidate is an unambiguous single match. A genuine name collision (two different LoRAs sharing a filename, e.g. for different base models) is always shown as a real choice, never auto-picked.
- **Library export / import** — back up or share your whole library as a single zip (everything except the disposable ComfyUI preview cache). Importing merges new entries in by name and never overwrites, modifies, or even touches anything that already exists in your library.
- **Library subfolders** — organize entries within each category into folders (and nested subfolders) purely for browsing: drag an entry onto a folder, or right-click → **Move to…** for one-off or multi-select moves. Folders sort alphabetically above entries at every level (numbers sort numerically — "Outfit 2" before "Outfit 10" — not character-by-character), expand/collapse individually or all at once, and have zero effect on the Builder, search, or LoRA bindings — an entry's name stays the single thing that identifies it everywhere else. Canon outfits are filed automatically into an always-present **Canonical Outfits** folder so they don't clutter the regular outfit list. See [Library subfolders](#library-subfolders) below.
- **Reference images** — attach a preview image to any library entry by dragging a file onto the editor or clicking to browse. Images are auto-converted, resized, and saved next to their entry. The preview size is adjustable with a slider and remembered between sessions.
- **History** — every generated prompt is saved automatically, with favorites and one-click restore back into the builder. While connected to ComfyUI, a history entry also records which LoRAs (and at what strength) were active for that specific generation, plus a one-click "Open image" that resolves to the same result the Gallery shows.
- **Gallery** — every image generated through ComfyUI this session shows up as a thumbnail, with hover-to-reveal-in-explorer and click-to-open-full-size.
- **In-app guide** — press **F1** or click **❓ Guide** anywhere in the app for a built-in walkthrough: first-run order of operations, how subfolders/Tools/LoRA Manager/the queue actually work, and the ComfyUI "last active workflow tab" behavior below. Multi-language from the start (English, Russian, Mandarin Chinese and Japanese guide's variations are avaivable).
- **Light / dark theme** toggle.
- All data is stored locally in plain `.txt` / `.json` / `.jpg` files — easy to back up, sync, or edit by hand.

## Screenshots

| Builder | Custom templates |
|---|---|
| ![Builder](screenshots/01-builder.png) | ![Custom template editor](screenshots/02-custom-template.png) |

| Library |
|---|
| ![Library](screenshots/03-library.png)|

## Getting started

### Requirements

- Python 3.9+ (Windows, macOS, or Linux)
- [`Pillow`](https://pypi.org/project/pillow/) — image conversion, resizing, and previews for library reference images and the Gallery
- [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/) — native drag-and-drop support for attaching images
- `tkinter` is required and ships with most standard Python installs (on some Linux distros it's a separate package, e.g. `sudo apt install python3-tk`)
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance with the **PromptForge Connection** custom node package installed — only if you want direct ComfyUI generation. Everything else works fully without it.

### Run from source

```bash
pip install pillow tkinterdnd2
python promptforgeint.py
```

If `tkinterdnd2` isn't installed, the app still runs — drag-and-drop is simply disabled and you can still attach images via the click-to-browse picker. If `Pillow` isn't installed, image attachment and the Gallery are disabled entirely (everything else works as normal).

On first launch, a `prompt_forge_data/` folder is created right next to the program — see [Data & storage](#data--storage).

## Sample library

A small starter library ships in this repo — 4 styles, 2 characters, 2
scenarios, 4 outfits, all plain text descriptions with **no LoRA
bindings**, just so there's something to look at and generate from
immediately instead of staring at an empty Library tab. Built around a
realism-leaning DiT model (Kontext/Z-Image-class), but the styles are
written so a prompt alone can push the same character toward an
illustrated/drawn look instead of photoreal.

To use it: **Library tab → 📥 Import library** and pick the zip from
this repo. Since it's a clean import into an empty library, everything
in it will be added (see [Library export / import](#library-export--import)
for what happens on a name clash, if you're merging it into a library
you've already started building).

## Building a standalone Windows .exe (with a custom icon)

1. Convert your icon artwork to a `.ico` file (multi-resolution: 16–256px). Either:
   - use a free online converter (e.g. [icoconvert.com](https://icoconvert.com), [convertio.co](https://convertio.co/png-ico/)), or
   - locally with Pillow:
     ```bash
     pip install pillow
     ```
     ```python
     from PIL import Image
     Image.open("icon_1080.png").save(
         "icon.ico", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
     )
     ```
2. Place `icon.ico` in the same folder as `promptforgeint.py`. The app picks it up automatically at startup (window/taskbar icon) — no code changes needed.
3. Install PyInstaller and the app's runtime dependencies, then build:
   ```bash
   pip install pyinstaller pillow tkinterdnd2
   pyinstaller --onefile --windowed --icon=icon.ico --name "PromptForge" --collect-all tkinterdnd2 promptforgeint.py
   ```
   The `--collect-all tkinterdnd2` flag is required — PyInstaller doesn't automatically bundle that package's bundled Tcl/Tk drag-and-drop library, and the .exe will fail to launch without it.
4. Grab the result from `dist/PromptForge.exe`, and copy `icon.ico` into that same `dist/` folder (the app looks for it next to the executable at runtime).
5. Run `PromptForge.exe` — it will create its own `prompt_forge_data/` folder right beside it on first launch, same as running from source.

## Connecting to ComfyUI

Direct generation requires the companion [**PromptForge Connection**](https://github.com/SirZavod/PromptForge-Nodes/tree/main)
custom node package installed in `ComfyUI/custom_nodes/` (separate
install — see that package's own repository).

1. Place a **PromptForge Connector** node in your ComfyUI graph (and,
   optionally, a **PromptForge Multi Lora Loader**), wired up per the
   node package's README.
2. In PromptForge's Builder tab, open the **ComfyUI** panel and tick
   **"ComfyUI connected?"**.
3. Build your prompt as usual, then either:
   - **⚡ Generate prompt and copy** — assembles the prompt and copies it
     to the clipboard, same as always, ComfyUI untouched.
   - **🎨 Generate in ComfyUI** — patches your prompt/negative
     prompt/seed/resolution (and LoRA Manager selections, if any) into
     the live graph and submits it. The **"Latest ComfyUI image"** panel
     shows live preview frames while it samples, then the finished
     result — which also lands in the **Gallery** tab.

Live preview depends entirely on ComfyUI's own **Settings → Comfy →
Execution → Live preview method**. If it's set to `none`, no frames
arrive — that's ComfyUI's setting, not a PromptForge toggle.

> **Live preview stopped working after a ComfyUI update?** A few users
> have reported live preview silently breaking after updating to the
> latest ComfyUI, even with the setting above configured correctly. This
> isn't a PromptForge issue — it's been resolved for them by launching
> ComfyUI with an explicit preview method flag, e.g.
> `--preview-method latent2rgb` (or another supported method). Worth
> trying if preview frames stopped arriving right after an update.

### ⚠️ Generation always targets the *last active* workflow in the browser

PromptForge has no concept of "which workflow you meant" — it asks the
bridge for whatever graph was most recently active in the ComfyUI
browser tab, and submits to that. Concretely:

- If you have two workflows open — say **Anima** and **Klein**, each
  with a Connector node — and **Klein** was the last tab you clicked on
  (even just to glance at it, no editing required), your next
  **🎨 Generate in ComfyUI** goes to Klein. You can close that tab
  immediately afterward; the generation still runs.
- Click over to the Anima tab and back, and the next generation goes to
  Anima instead — LoRAs included.
- This holds even if you close the browser tab, close the browser
  entirely, or kill the browser process afterward — ComfyUI keeps using
  whichever workflow was last active. That also means you can free up
  the RAM a browser tab uses once you've confirmed the right workflow is
  active, without affecting generation at all.
- Example workflow JSONs (Anima, Klein, Qwen Image), pre-wired with the
  Connector node, are included to make this concrete rather than just
  read about.

**Rule of thumb:** whichever ComfyUI workflow tab was open last is where
the job is going.

## Library subfolders

Each category in the Library tab (styles, scenarios, characters, outfits)
can be organized into folders and nested subfolders — purely as a
browsing aid. Folders are never part of an entry's identity: an entry's
name is still the one thing the Builder, search, history, and LoRA
bindings care about, exactly as before. You can rename a folder, move
its contents around, or delete it entirely without touching a single
`.txt`/`.jpg`/`.meta.json` file on disk.

- **Creating a folder** — right-click anywhere in the list (an entry, a
  folder, or empty space) → **New folder…**. Right-click a folder →
  **New subfolder here** to nest one inside it.
- **Moving entries in** — either drag an entry (or a multi-selection made
  with Shift/Ctrl) onto a folder, or right-click → **Move to…** and pick
  a destination, including back to the category root. The context menu
  is the more reliable option for large batches.
- **Expand / collapse** — click a folder's disclosure arrow to open or
  close it, or use the **▾ Expand all** / **▸ Collapse all** buttons
  above the list to do it for the whole category at once. A freshly
  opened category starts fully collapsed.
- **Sorting** — folders always sort above entries, alphabetically, at
  every level of nesting. Sorting is "natural" — embedded numbers compare
  numerically, so "Outfit 2" comes before "Outfit 10" rather than after
  "Outfit 1" and before "Outfit 11" the way plain character-by-character
  sorting would put them.
- **Search** — typing in the search box filters by entry name/content
  only, the same as before subfolders existed; a folder's own name is
  never part of the match. Folders containing a match auto-expand for
  the duration of the search, and empty folders you've created stay
  visible too (they can't hide a false match, so there's no reason to
  collapse them out of the way).
- **Canon outfits** — automatically filed into a dedicated **Canonical
  Outfits** folder the moment an outfit is marked as a character's canon
  outfit, keeping them out of your hand-organized folders. That folder
  is system-managed: it can't be renamed or deleted, and ordinary outfits
  can't be dropped into it by hand.

Folder placement is saved per category in `_folders.json` (see
[Data & storage](#data--storage)) and has no effect whatsoever on the
Builder's dropdowns, autocomplete, or generated prompts.

## Tools

Tools are library entries (their own category, alongside styles,
scenarios, characters, and outfits) for things that are mostly — or
entirely — about a **bound LoRA** rather than prompt text: anatomy
fixers, hand detailers, sharpness boosts, anything Stable Diffusion
effectively can't do without a helper LoRA. Unlike every other category,
a Tool can be saved with **completely empty tags** — its only job might
be feeding the LoRA Manager's auto slots.

If a Tool *does* have a short tag (some workflows trigger specific
behavior with something like `@fixedanatomy`), check **"Force this
tool's tag to the very start of the prompt"** in the Library editor.
That tag then always lands as the very first thing in the assembled
prompt — ahead of Style/Characters/Scenario — no matter how you've
reordered everything else via **Block order…**. Tools without that flag
just sit wherever "Tools" falls in your block order, like any other
section.

Tools work in both the Standard builder (its own collapsible "▸ Tools"
section, collapsed by default) and Custom templates, via the `[Tool]`
variable — every active Tool slot's tag joins together (comma-separated)
into wherever you place that one tag in your template text.

## Generation queue

Clicking **🎨 Generate in ComfyUI** always succeeds immediately — it
adds your current prompt, seed, resolution, and LoRA snapshot to a
queue rather than refusing if something is already generating.
Everything about that click (including which LoRAs and strengths are
active right then) is frozen into that queue entry; changing a LoRA
strength afterward only affects *future* clicks, never one already
queued.

Exactly one job runs with ComfyUI at a time; queued items wait their
turn and start automatically as each one finishes. **⏹ Stop** cancels
only the one currently running, then the next queued item starts
automatically — it never touches anything still waiting. **🗑 Clear
queue** removes everything still *waiting*, but never the one already
generating (matching how ComfyUI's own built-in queue UI behaves) — use
Stop for that one specifically. The small counter next to Generate
("📋 generating + *N* queued") distinguishes "something's already
running, *N* more behind it" from "nothing running, *N* waiting to
start" — clicking three times while a job was already mid-generation
used to just read as "3 queued", which looked like only 3 existed in
total rather than 4.

## LoRA dependency checking & auto-link

**🔍 Check LoRA dependencies** (Library tab, requires a ComfyUI
connection) scans every entry in every category — including canon
outfits — for a bound LoRA, and reports anything ComfyUI's current LoRA
list doesn't actually have, grouped by which entry(ies) use it. Built
for the "I just downloaded a 100-character library, did I actually grab
every LoRA, or can I close Civitai now?" moment — a single pass over the
whole library instead of finding out one character at a time mid-session.

If something's missing, **🔎 Find candidates** searches ComfyUI's LoRA
list for files with the same *filename* under a different folder (e.g.
you didn't recreate the exact folder structure a downloaded library
expected). A single match can be applied with one click — or all
single-match candidates at once, if there's more than one — but a
**name collision** (two or more files sharing a filename, e.g. for two
different base models) is always shown as a real choice between every
option, never auto-picked; guessing wrong there means a generation
silently runs with the wrong model's LoRA.

While connected to ComfyUI, this same check also drives small color
indicators directly in the Library list: green for an exact match,
yellow for "a candidate exists but isn't a confirmed match" (including
collisions), red for "nothing found at all". The colors disappear the
moment you leave the Library tab or disconnect ComfyUI — they're a live
status, not a permanent label.

## Library export / import

**📦 Export library** zips your whole `prompt_forge_data/` folder
(everything except the disposable `_comfy_previews/` cache) for backing
up or sharing. **📥 Import library** merges another exported zip into
your current library, category by category — strictly by name: if an
entry already exists, the incoming one is skipped and your existing
entry is left completely untouched (not overwritten, not renamed, not
merged). A report afterward lists exactly what was imported and what
was skipped.

## In-app guide

Press **F1**, or click **❓ Guide** in the top bar, anywhere in the app
for a built-in walkthrough — the actual order to do things in on first
launch, how subfolders/Tools/the LoRA Manager/the generation queue work,
and the ComfyUI "last active workflow tab" behavior from above. English
is fully written; other languages are switchable from the same window
and explicitly marked if a section is still pending translation, rather
than silently falling back to English without saying so.

## Known issues

- **Theme toggle doesn't fully recolor every widget.** Switching between
  light and dark theme can leave a few widgets with their old colors
  until the app is restarted. This is a Tkinter rendering quirk, not a
  data issue — nothing is lost, it's purely cosmetic. A proper fix is
  planned alongside a future migration of the UI to PyQt6 or PySide6;
  until then, restart the app after a theme switch if it looks off.
- ~~Crash when enabling ComfyUI integration in windowed mode~~ — **fixed.**
  Toggling the ComfyUI connection used to occasionally freeze or crash on
  small/non-maximized windows, depending on display resolution. The root
  cause (a burst of layout changes triggering repeated geometry
  recalculation in the same moment) has been addressed; maximizing the
  window before connecting is no longer necessary.

## Data & storage

`prompt_forge_data/` always appears **right next to the program itself**
— the `.py` file when run from source, or the `.exe` when run compiled —
regardless of which folder you happened to launch it from (double-click,
shortcut, terminal in another directory, etc. all resolve to the same
place):

```
prompt_forge_data/
├── styles/
│   ├── cityStyle.txt
│   ├── cityStyle.jpg          # optional reference image, same name as the entry
│   └── cityStyle.meta.json    # optional: source URL / bound LoRA / force-to-start flag for this entry
├── scenarios/
├── characters/
│   ├── konYunyun.txt
│   ├── konYunyun.jpg
│   └── konYunyun.meta.json
├── outfits/
├── tools/
│   └── fixedAnatomy.meta.json  # tags (.txt) are optional here — see Tools above
├── _templates.json            # saved block-order templates
├── _custom_templates.json     # custom text templates
├── _history.json               # generated-prompt history (LoRA usage + image link, if ComfyUI was connected)
├── _settings.json              # theme, image-preview size, and other UI preferences
├── _folders.json                # per-category library subfolder placement (UI only — see Library subfolders)
└── _comfy_previews/            # session-only cache of images pulled from ComfyUI
                                 # (Builder's "Latest image" + Gallery thumbnails);
                                 # wiped on every app restart, never holds your only copy
```

Each library entry's image and metadata (if any) sit right next to its
`.txt` file under the same base name, so renaming, duplicating, or
deleting an entry in the app keeps them in sync automatically.

The `prompt_forge_data/` folder (everything *except* `_comfy_previews/`,
which is just a disposable cache) is fully portable — copy it to another
machine, or back it up, to bring your whole library, history, and
reference images with you.

## Changelog

### v3.0.0 (Current)
- **Tools:** a new library category for entries that are mostly (or
  entirely) about a bound LoRA rather than prompt text — the only
  category where tags can be left completely empty. An optional
  "force to start of prompt" flag pulls a Tool's tag ahead of everything
  else, regardless of block order. Works in both the Standard builder
  and Custom templates (`[Tool]` variable).
- **Generation queue:** "🎨 Generate in ComfyUI" now always queues
  rather than refusing while something's already running, with each
  queued item keeping its own frozen LoRA/seed/strength snapshot.
  **⏹ Stop** is now a separate button from Generate (cancels only the
  active job) instead of Generate itself swapping into a Stop state,
  which used to make it impossible to queue anything new while a job
  was in flight. **🗑 Clear queue** drops everything still waiting.
- **LoRA dependency checking & auto-link:** one-click scan of the whole
  library against ComfyUI's live LoRA list; missing LoRAs can search for
  a same-named file elsewhere and offer it as a candidate (applied
  individually or all at once for unambiguous matches — a real name
  collision is always a manual choice, never auto-picked). Library rows
  are also color-coded live (green/yellow/red) while connected.
- **Library export / import:** back up or share a whole library as a
  zip; importing never overwrites or touches anything that already
  exists, only adds new entries by name.
- **History now tracks LoRA usage and the result image** (when ComfyUI
  is connected) — which LoRAs and strengths were active for that
  specific generation, plus a one-click "Open image".
- **In-app guide:** press F1 or click "❓ Guide" for a built-in,
  multi-language walkthrough of the whole app.
- **Natural sort everywhere a library/folder/LoRA-path name is
  displayed** — "Outfit 2" now sorts before "Outfit 10", not after
  "Outfit 19".
- **Fixed:** the ComfyUI-connection crash/freeze on small windows
  (previously listed under Known issues) — root cause was a burst of
  layout changes triggering repeated geometry recalculation in the same
  moment; no longer requires maximizing the window first.

### v2.1.0
- **Library subfolders:** organize entries in any category (styles,
  scenarios, characters, outfits) into folders and nested subfolders,
  purely as a browsing aid — entry names stay the single identifier the
  Builder, search, history, and LoRA bindings rely on, untouched.
  - Drag-and-drop (including multi-selection via Shift/Ctrl) or
    right-click → **Move to…** to file entries into folders; right-click
    → **New folder…** / **New subfolder here** to create them.
  - Folders sort alphabetically above entries at every nesting level;
    **▾ Expand all** / **▸ Collapse all** buttons sit above the list,
    alongside per-folder click-to-toggle.
  - Search matches entry name/content only — never a folder's own name —
    and auto-expands any branch containing a match.
  - Canon outfits are filed automatically into a system-managed
    **Canonical Outfits** folder, keeping them separate from your own
    organization.

### v2.0.0
- **Direct ComfyUI generation:** a new companion custom node package
  (PromptForge Connection) plus an in-app ComfyUI panel let you
  submit your built prompt straight to a running ComfyUI instance and
  watch it generate, without leaving PromptForge.
  - **🎨 Generate in ComfyUI** patches prompt / negative prompt / seed /
    width / height (and LoRA Manager selections) into whichever workflow
    is currently active in the ComfyUI browser tab, and submits it.
  - Live preview frames stream into the Builder tab's "Latest ComfyUI
    image" panel while sampling runs, honoring ComfyUI's own Live
    preview method setting.
  - The finished result is downloaded, shown in the Builder tab, and
    added to the new **Gallery** tab.
- **LoRA Manager:** manual and auto (library-bound, tagged `[A]`)
  LoRA slots, validated against ComfyUI's live LoRA list before
  submitting so a missing file is caught immediately instead of
  silently being skipped mid-generation.
- **Library entries gained two optional fields:** a source URL (to credit
  or relocate the original model/reference) and a bound LoRA (feeds the
  LoRA Manager's auto slots).
- **Gallery tab:** every image generated through ComfyUI this session
  appears as a thumbnail, with hover-to-reveal-in-explorer and
  click-to-open-full-size.
- Renamed the entry-point script to `promptforgeint.py`.

### v1.2.0
- **Reference images for library entries:** Every style, scenario, character, and outfit can now have a reference image attached, right inside the Library tab's Entry Editor.
  - Drag a file in or click the preview zone to browse — both save through the same pipeline.
  - Images are automatically converted to optimized `.jpg`, proportionally resized so their longest side is 1024px (never upscaled, aspect ratio always preserved), and saved next to the entry's `.txt` file under the same name.
  - The preview scales to a percentage of the Entry Editor panel's height rather than a fixed pixel size, so it looks proportioned on anything from a 1080p laptop to a 4K monitor.
  - A size slider lets you resize the preview to taste; the value applies to all four categories and is remembered across restarts.
  - Renaming, duplicating, or deleting a library entry keeps its image file in sync automatically — no orphaned images left behind.
  - Falls back gracefully if `Pillow` or `tkinterdnd2` aren't installed (see Requirements below).

### v1.1.0
- **Inline Search in Builder:** Upgraded standard dropdowns (`Who:` and `Outfit:`) to custom autocomplete fields. You can now type directly on the keyboard to filter library elements on the fly.
- **Default Template Refinements:** Fixed text-formatting edge cases in the standard prompt builder:
  - If exactly **1 character** is selected, the redundant `, a scene of 1 characters` prefix is now completely omitted from the final prompt.
  - Automatically appends a trailing period (`.`) to the end of each character's tag block for cleaner prompt structuring and better compatibility with Diffusion models.

## License

This project is released into the public domain under [The Unlicense](https://unlicense.org/).

```
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute
this software, either in source code form or as a compiled binary, for any
purpose, commercial or non-commercial, and by any means.

In jurisdictions that recognize copyright laws, the author or authors of
this software dedicate any and all copyright interest in the software to
the public domain. We make this dedication for the benefit of the public
at large and to the detriment of our heirs and successors. We intend this
dedication to be an overt act of relinquishment in perpetuity of all
present and future rights to this software under copyright law.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

For more information, please refer to <https://unlicense.org/>
```
