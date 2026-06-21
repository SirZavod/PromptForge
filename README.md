# ⚡ Prompt Forge

A lightweight desktop app for building AI image-generation prompts out of reusable building blocks — **styles**, **characters**, **outfits**, and **scenarios** — instead of retyping the same tags every time.

![Prompt Forge — Builder tab](screenshots/01-builder.png)

## Features

- **Standard builder** — pick a style, add any number of characters with their outfits, pick a scenario, and generate a ready-to-paste prompt with one click. Reorder the assembled blocks (style / characters / scenario) however you like, and save your favorite orderings as reusable templates.
- **Custom templates** — write your own prompt skeleton with placeholders like `[Name 1]`, `[Description 1]`, `[Outfit 1]`, `[Style]`, `[Scenario]`, and fill them in from dropdowns each time you generate.
- **Library manager** — a built-in editor for your styles, scenarios, characters, and outfits, with search and per-character "canon" outfits.
- **Reference images** — attach a preview image to any library entry (style, scenario, character, or outfit) by dragging a file onto the editor or clicking to browse. Images are auto-converted, resized, and saved next to their entry. The preview size is adjustable with a slider and remembered between sessions.
- **History** — every generated prompt is saved automatically, with favorites and one-click restore back into the builder.
- **Light / dark theme** toggle.
- All data is stored locally in plain `.txt` / `.json` / `.jpg` files — easy to back up, sync, or edit by hand.

## Screenshots

| Builder | Custom templates |
|---|---|
| ![Builder](screenshots/01-builder.png) | ![Custom template editor](screenshots/02-custom-template.png) |

| Library | History |
|---|---|
| ![Library](screenshots/03-library.png) | ![History](screenshots/04-history.png) |

## Getting started

### Requirements

- Python 3.9+ (Windows, macOS, or Linux)
- [`Pillow`](https://pypi.org/project/pillow/) — image conversion, resizing, and previews for library reference images
- [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/) — native drag-and-drop support for attaching images
- `tkinter` is required and ships with most standard Python installs (on some Linux distros it's a separate package, e.g. `sudo apt install python3-tk`)

### Run from source

```bash
pip install pillow tkinterdnd2
python prompt_forge.py
```

If `tkinterdnd2` isn't installed, the app still runs — drag-and-drop is simply disabled and you can still attach images via the click-to-browse picker. If `Pillow` isn't installed, image attachment is disabled entirely (everything else works as normal).


On first launch, a `prompt_forge_data/` folder is created next to the script, containing your styles, scenarios, characters, outfits, and saved history/templates.

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
2. Place `icon.ico` in the same folder as `promptforge.py`. The app picks it up automatically at startup (window/taskbar icon) — no code changes needed.
3. Install PyInstaller and the app's runtime dependencies, then build:
   ```bash
   pip install pyinstaller pillow tkinterdnd2
   pyinstaller --onefile --windowed --icon=icon.ico --name "PromptForge" --collect-all tkinterdnd2 promptforge.py
   ```
   The `--collect-all tkinterdnd2` flag is required — PyInstaller doesn't automatically bundle that package's bundled Tcl/Tk drag-and-drop library, and the .exe will fail to launch without it.
4. Grab the result from `dist/PromptForge.exe`, and copy `icon.ico` into that same `dist/` folder (the app looks for it next to the executable at runtime).
5. Run `PromptForge.exe` — it will create its own `prompt_forge_data/` folder right beside it on first launch, same as running from source.

## Data & storage

Everything lives in `prompt_forge_data/` next to the program:

```
prompt_forge_data/
├── styles/
│   ├── cityStyle.txt
│   └── cityStyle.jpg        # optional reference image, same name as the entry
├── scenarios/
├── characters/
│   ├── konYunyun.txt
│   └── konYunyun.jpg
├── outfits/
├── _templates.json          # saved block-order templates
├── _custom_templates.json   # custom text templates
├── _history.json            # generated-prompt history
└── _settings.json           # theme, image-preview size, and other UI preferences
```

Each library entry's image (if any) is a `.jpg` saved right next to its `.txt` file under the same name, so renaming, duplicating, or deleting an entry in the app keeps the image in sync automatically.

This folder is fully portable — copy it to another machine (or back it up) to bring your whole library, history, and reference images with you.

## Changelog

### v1.2.0 (Current)
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
