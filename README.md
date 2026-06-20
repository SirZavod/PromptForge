# ⚡ Prompt Forge

A lightweight desktop app for building AI image-generation prompts out of reusable building blocks — **styles**, **characters**, **outfits**, and **scenarios** — instead of retyping the same tags every time.

![Prompt Forge — Builder tab](screenshots/01-builder.png)

## Features

- **Standard builder** — pick a style, add any number of characters with their outfits, pick a scenario, and generate a ready-to-paste prompt with one click. Reorder the assembled blocks (style / characters / scenario) however you like, and save your favorite orderings as reusable templates.
- **Custom templates** — write your own prompt skeleton with placeholders like `[Name 1]`, `[Description 1]`, `[Outfit 1]`, `[Style]`, `[Scenario]`, and fill them in from dropdowns each time you generate.
- **Library manager** — a built-in editor for your styles, scenarios, characters, and outfits, with search and per-character "canon" outfits.
- **History** — every generated prompt is saved automatically, with favorites and one-click restore back into the builder.
- **Light / dark theme** toggle.
- **No external dependencies** — runs on the Python standard library alone (just `tkinter`).
- All data is stored locally in plain `.txt` / `.json` files — easy to back up, sync, or edit by hand.

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
- That's it — no `pip install` needed to run from source.

### Run from source

```bash
python prompt_forge.py
```


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
3. Install PyInstaller and build:
   ```bash
   pip install pyinstaller
   pyinstaller --onefile --windowed --icon=icon.ico --name "PromptForge" promptforge.py
   ```
4. Grab the result from `dist/PromptForge.exe`, and copy `icon.ico` into that same `dist/` folder (the app looks for it next to the executable at runtime).
5. Run `PromptForge.exe` — it will create its own `prompt_forge_data/` folder right beside it on first launch, same as running from source.

## Data & storage

Everything lives in `prompt_forge_data/` next to the program:

```
prompt_forge_data/
├── styles/
├── scenarios/
├── characters/
├── outfits/
├── _templates.json          # saved block-order templates
├── _custom_templates.json   # custom text templates
├── _history.json            # generated-prompt history
└── _settings.json           # theme preference
```

This folder is fully portable — copy it to another machine (or back it up) to bring your whole library and history with you.

## License

Add a license of your choice here (e.g. MIT) before publishing publicly — none is included by default.
