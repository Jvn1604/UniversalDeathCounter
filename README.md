<<<<<<< HEAD
=======
<<<<<<< HEAD
# UniversalDeathCounter
a simple manual death counter
=======
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02
# Universal Death Counter

![Universal Death Counter](assets/icons/readme_banner.png)

A free, open-source death counter for Soulslike games, challenge runs, speedruns, and literally any PC game. Built for streamers, challenge runners, and masochists who need to know exactly how many times Malenia has humbled them.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![PySide6](https://img.shields.io/badge/UI-PySide6-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Manual death counting** — works with *any* game, no memory reading or injection required
- **Session + Total counters** — track a single run and your all-time total separately
<<<<<<< HEAD
- **Full CRUD freedom** — create, rename, and delete any game or boss at any time; nothing is locked in
- **Quick-Add templates** — one click adds a popular game (Elden Ring, Dark Souls III, Sekiro, Bloodborne, Hollow Knight, Cuphead) with its full boss list pre-filled — then edit/rename/delete freely
- **Set an exact count** — correct the session or total death count directly instead of clicking +1 dozens of times
- **Session history** — review every past run per game, with per-session death counts and one-click delete
- **Backup & restore** — export all your data to a single JSON file and import it back (or onto another PC) anytime
- **Clear all data** — full reset in one confirmed action, with settings preserved
- **Global hotkeys** — `F9` (+1), `F10` (-1), `F11` (Undo), `F12` (Toggle Overlay) work even while your game is focused
- **OBS-ready overlay** — transparent, frameless, resizable, movable window for Window Capture — **plus a chroma-key green mode** for color-key filters
- **Overlay customization** — pick the counter color, font size, which number the big counter shows (session / boss / total), and toggle each line (game, boss, stats) on or off
- **deaths.txt for OBS Text Sources** — writes a fully customizable template like `{game} - {boss}: {deaths}` to a text file on every change, so streamers can skip window capture entirely
- **Boss victories** — mark any boss as Defeated ✓ and the app records your "deaths until victory" forever
- **Death notes** — attach a note to any individual death ("fell off cliff", "phase 2 grab") via the Death Log
- **Statistics & graphs** — most/least deaths per boss, average deaths per boss, victories, plus **Qt Charts graphs**: deaths per boss, cumulative deaths over time, and per-session trend
- **CSV export** — spreadsheet-friendly summary of every boss and game total
- **Multiple profiles** — completely separate databases (e.g. "Main Runs" vs "Co-op Nights"), switchable live from the Profile menu
- **System tray** — minimize to tray with quick actions (+1, -1, Undo, Toggle Overlay) one right-click away
- **Update check** — quietly checks GitHub Releases on startup and notifies you when a new version is out (can be disabled)
- **Dark & Light themes** — modern Steam/Discord/Windows 11–inspired UI, easy to extend with more themes
- **Autosave** — every action is written to SQLite immediately, no save button needed
- **Fully local** — your data lives in a local SQLite file, nothing is sent anywhere
- **Windows installer** — auto-built by CI into a real `Setup.exe`, no Python required to run it
=======
- **Games & Bosses manager** — organize counters per game, per boss/segment
- **Global hotkeys** — `F9` (+1), `F10` (-1), `F11` (Undo), `F12` (Toggle Overlay) work even while your game is focused
- **OBS-ready overlay** — transparent, frameless, resizable, movable window for Window Capture
- **Statistics** — most/least deaths per boss, average deaths per boss, most played game, total sessions
- **Dark & Light themes** — modern Steam/Discord/Windows 11–inspired UI, easy to extend with more themes
- **Autosave** — every action is written to SQLite immediately, no save button needed
- **Fully local** — your data lives in a local SQLite file, nothing is sent anywhere
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02

## Screenshots

> _Add screenshots of the main window, overlay, and statistics dialog here once available._

| Main Window | OBS Overlay |
|---|---|
| `docs/screenshot-main.png` | `docs/screenshot-overlay.png` |

## Installation

<<<<<<< HEAD
### Option 1 — Download the Windows installer (easiest)

Every push to `main` automatically builds a Windows installer via GitHub Actions.

1. Go to the repo's **Actions** tab → latest successful **Build Windows Executable** run → download the `UniversalDeathCounter-Setup` artifact (or, for tagged versions, grab `UniversalDeathCounterSetup.exe` from the **Releases** page).
2. Run `UniversalDeathCounterSetup.exe` and follow the wizard.
3. Launch **Universal Death Counter** from the Start Menu or desktop shortcut, like any other installed app.

No Python required — this is a fully self-contained installer.

### Option 2 — Build the .exe yourself (on Windows)

```bash
git clone https://github.com/<your-username>/UniversalDeathCounter.git
cd UniversalDeathCounter
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Build the standalone .exe
pyinstaller packaging\UniversalDeathCounter.spec
# -> dist\UniversalDeathCounter.exe

# Optional: build the full installer too (requires Inno Setup 6: https://jrsoftware.org/isinfo.php)
iscc packaging\installer.iss
# -> dist_installer\UniversalDeathCounterSetup.exe
```

### Option 3 — Run from source (any OS)

#### Requirements
=======
### Requirements
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02

- Python 3.12+
- Windows, macOS, or Linux (global hotkeys require elevated/root permissions on Linux — see [Known Limitations](#known-limitations))

<<<<<<< HEAD
```bash
git clone https://github.com/<your-username>/UniversalDeathCounter.git
cd UniversalDeathCounter
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m src.app
```

## Usage

1. Open **Manage → Games & Bosses…** to create your first game — type a name, or hit **Quick-Add Template** for an instant Elden Ring / Dark Souls III / Sekiro / Bloodborne / Hollow Knight / Cuphead setup.
2. Double-click any game or boss in that dialog to rename it; delete buttons remove it (and its history) entirely. Nothing is permanent until you want it to be.
3. Select your game/boss from the dropdowns on the main window.
4. Hit **+1 Death** (or `F9`) every time you die. `F10` decrements, `F11` undoes the last action, and **Set Exact Count…** lets you jump straight to a specific number.
5. Beat a boss? Select it in **Manage → Games & Bosses…** and hit **Toggle Defeated ✓** — your "deaths until victory" number is captured permanently.
6. Open **Manage → Games & Bosses… → Session History** to review or delete individual past runs for a game.
7. Open **View → Toggle Overlay** (or `F12`) and add it as a **Window Capture** source in OBS — or switch the overlay to **chroma** mode in Settings and use a Color Key filter. Prefer text? Enable **deaths.txt** in Settings and point an OBS **Text Source** at the file, with your own `{game} - {boss}: {deaths}` template.
8. Check **View → Statistics & Graphs…** for your per-boss breakdown, victories, and three charts (deaths per boss, deaths over time, per-session trend). **View → Death Log…** lets you attach a note to any individual death.
9. Use the **Profile** menu to create fully separate databases (e.g. a co-op profile) and switch between them instantly.
10. Use **File → Export Backup (JSON)** to save all your data, **File → Import Backup (JSON)** to restore it, and **File → Export CSV Summary…** for a spreadsheet-friendly report. **File → Clear All Data** wipes the current profile if you want a fresh start.
11. Customize hotkeys, theme, tray behavior, and every overlay/streaming option under **Settings → Preferences…**. Enable *Minimize to system tray* to keep counting via hotkeys with the window hidden.
=======
### Steps

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/UniversalDeathCounter.git
cd UniversalDeathCounter

# 2. (Recommended) create a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python -m src.app
```

### Building a standalone executable

```bash
pyinstaller --noconsole --onefile --name "UniversalDeathCounter" src/app.py
```

The compiled binary will be in `dist/`.

## Usage

1. Open **Manage → Games & Bosses…** to create your first game and (optionally) bosses within it.
2. Select your game/boss from the dropdowns on the main window.
3. Hit **+1 Death** (or `F9`) every time you die. `F10` decrements, `F11` undoes the last action.
4. Open **View → Toggle Overlay** (or `F12`) and add it as a **Window Capture** source in OBS.
5. Check **View → Show Statistics** any time to see your per-boss and per-game breakdown.
6. Customize hotkeys, theme, and overlay appearance under **Settings → Preferences…**.
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02

## Project Structure

```
UniversalDeathCounter/
├── src/
│   ├── app.py                  # Entry point
│   ├── core/                   # Counter, session, and statistics logic
│   ├── database/                # SQLite access layer (single source of SQL)
│   ├── models/                  # Game / Boss dataclasses
<<<<<<< HEAD
│   ├── ui/                      # Main window, settings, boss manager, session history, about
│   ├── overlay/                  # OBS-ready transparent overlay
│   ├── hotkeys/                 # Global hotkey listener
│   ├── themes/                   # Dark/Light QSS stylesheets + loader
│   └── utils/                    # Constants, logging, game templates
├── packaging/                    # PyInstaller spec + Inno Setup installer script
├── .github/workflows/            # CI: auto-builds the Windows .exe/installer
=======
│   ├── ui/                      # Main window, settings, boss manager, about
│   ├── overlay/                  # OBS-ready transparent overlay
│   ├── hotkeys/                 # Global hotkey listener
│   ├── themes/                   # Dark/Light QSS stylesheets + loader
│   └── utils/                    # Constants, logging
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02
├── assets/                      # Icons, fonts
├── saves/                       # SQLite DB + logs (gitignored)
├── tests/                       # pytest unit tests
├── docs/                        # Screenshots, extra docs
├── requirements.txt
└── LICENSE
```

### Architecture notes

<<<<<<< HEAD
- **Event-sourced death counting.** Rather than storing a single mutable counter, every `+1`/`-1` — and every "set exact count" correction — is appended to a `death_events` table with a signed `delta`. Totals, session counts, and undo are all derived by aggregating this log. This gives accurate undo, a full audit trail, and makes backup/export trivial — no schema changes needed.
- **Single SQL boundary.** `src/database/database.py` is the only module that writes raw SQL. `CounterManager`, `SessionManager`, and `StatisticsService` build on top of it, so the data layer can be swapped (e.g. for PostgreSQL in a future sync feature) without touching business logic.
- **Hotkeys are decoupled from the UI.** `HotkeyManager` emits Qt signals; both the on-screen buttons and global hotkeys call the exact same `CounterManager` methods, so behavior is always consistent.
- **Persistent data survives packaging.** When run as a frozen PyInstaller executable, the SQLite database and logs are stored next to the `.exe` (or in the OS's per-user app-data folder if that location isn't writable) rather than in PyInstaller's temporary extraction directory — otherwise every session would lose its history on exit.
=======
- **Event-sourced death counting.** Rather than storing a single mutable counter, every `+1`/`-1` is appended to a `death_events` table with a signed `delta`. Totals, session counts, and undo are all derived by aggregating this log. This gives accurate undo, a full audit trail, and makes future CSV/JSON export trivial — no schema changes needed.
- **Single SQL boundary.** `src/database/database.py` is the only module that writes raw SQL. `CounterManager`, `SessionManager`, and `StatisticsService` build on top of it, so the data layer can be swapped (e.g. for PostgreSQL in a future sync feature) without touching business logic.
- **Hotkeys are decoupled from the UI.** `HotkeyManager` emits Qt signals; both the on-screen buttons and global hotkeys call the exact same `CounterManager` methods, so behavior is always consistent.
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02
- **Plugin-ready by design.** v1.0 is 100% manual input, but the manager classes (`CounterManager`, `Database`) expose everything a future automatic-detection plugin (OCR, memory reading, Steam/Discord integration) would need to call into — without changing this code.

## Roadmap

<<<<<<< HEAD
### v1.0
=======
### v1.0 (current)
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02
- [x] Manual counter (+1 / -1 / Undo)
- [x] Games & Bosses management
- [x] OBS overlay
- [x] Global hotkeys
- [x] Statistics
- [x] SQLite persistence

<<<<<<< HEAD
### v1.1
- [x] Rename any game or boss at any time
- [x] Quick-Add game/boss templates (Elden Ring, Dark Souls III, Sekiro, Bloodborne, Hollow Knight, Cuphead)
- [x] Set an exact session/total death count
- [x] Session history viewer with per-session delete
- [x] JSON backup export / import (merge or replace)
- [x] Clear-all-data reset
- [x] Windows installer via PyInstaller + Inno Setup, auto-built by CI

### v1.5 (current)
- [x] Chroma-key green overlay mode for OBS color-key filters
- [x] Overlay customization: counter color, counter source (session/boss/total), show/hide lines
- [x] deaths.txt output with customizable template for OBS Text Sources
- [x] Boss Defeated ✓ tracking with "deaths until victory"
- [x] Notes on individual deaths (Death Log)
- [x] Graphs: deaths per boss, cumulative deaths over time, per-session trend (Qt Charts)
- [x] CSV summary export
- [x] Multiple profiles (separate databases)
- [x] System tray with quick actions + minimize-to-tray
- [x] Startup update check via GitHub Releases

### Future
- [ ] Additional themes
=======
### v1.5
- [ ] CSV / JSON import & export
- [ ] Additional themes
- [ ] Death-over-time graphs
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02

### v2.0
- [ ] OCR-based automatic detection ("YOU DIED", "DEMISE", "DEFEAT")
- [ ] Formal plugin API for memory reading, Steam, and Discord Rich Presence integrations

## Contributing

Contributions are very welcome!

1. Fork the repo and create a feature branch (`git checkout -b feature/my-feature`)
2. Keep changes modular — one concern per module, matching the existing structure
3. Add or update tests in `tests/` for any logic changes (`pytest tests/`)
4. Follow PEP 8, use type hints and docstrings (see existing modules for the expected style)
5. Open a pull request describing your change and why it's useful

Bug reports and feature requests are just as valuable as code — please open an issue.

## Known Limitations

- Global hotkeys (via the `keyboard` library) require **administrator/root privileges on Linux** to read raw input devices. On Windows they work for the current user out of the box. If hotkeys silently fail to register, the in-app buttons remain fully functional.
- v1.0 is manual-only by design; see the Roadmap for planned automatic detection.

## License

This project is licensed under the [MIT License](LICENSE).
<<<<<<< HEAD
=======
>>>>>>> e2fc41f (Initial project structure)
>>>>>>> 87d3c43bd4a8cfe2e09f744eb9c535cdd5c0fb02
