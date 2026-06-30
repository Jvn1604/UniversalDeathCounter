<<<<<<< HEAD
# UniversalDeathCounter
a simple manual death counter
=======
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
- **Games & Bosses manager** — organize counters per game, per boss/segment
- **Global hotkeys** — `F9` (+1), `F10` (-1), `F11` (Undo), `F12` (Toggle Overlay) work even while your game is focused
- **OBS-ready overlay** — transparent, frameless, resizable, movable window for Window Capture
- **Statistics** — most/least deaths per boss, average deaths per boss, most played game, total sessions
- **Dark & Light themes** — modern Steam/Discord/Windows 11–inspired UI, easy to extend with more themes
- **Autosave** — every action is written to SQLite immediately, no save button needed
- **Fully local** — your data lives in a local SQLite file, nothing is sent anywhere

## Screenshots

> _Add screenshots of the main window, overlay, and statistics dialog here once available._

| Main Window | OBS Overlay |
|---|---|
| `docs/screenshot-main.png` | `docs/screenshot-overlay.png` |

## Installation

### Requirements

- Python 3.12+
- Windows, macOS, or Linux (global hotkeys require elevated/root permissions on Linux — see [Known Limitations](#known-limitations))

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

## Project Structure

```
UniversalDeathCounter/
├── src/
│   ├── app.py                  # Entry point
│   ├── core/                   # Counter, session, and statistics logic
│   ├── database/                # SQLite access layer (single source of SQL)
│   ├── models/                  # Game / Boss dataclasses
│   ├── ui/                      # Main window, settings, boss manager, about
│   ├── overlay/                  # OBS-ready transparent overlay
│   ├── hotkeys/                 # Global hotkey listener
│   ├── themes/                   # Dark/Light QSS stylesheets + loader
│   └── utils/                    # Constants, logging
├── assets/                      # Icons, fonts
├── saves/                       # SQLite DB + logs (gitignored)
├── tests/                       # pytest unit tests
├── docs/                        # Screenshots, extra docs
├── requirements.txt
└── LICENSE
```

### Architecture notes

- **Event-sourced death counting.** Rather than storing a single mutable counter, every `+1`/`-1` is appended to a `death_events` table with a signed `delta`. Totals, session counts, and undo are all derived by aggregating this log. This gives accurate undo, a full audit trail, and makes future CSV/JSON export trivial — no schema changes needed.
- **Single SQL boundary.** `src/database/database.py` is the only module that writes raw SQL. `CounterManager`, `SessionManager`, and `StatisticsService` build on top of it, so the data layer can be swapped (e.g. for PostgreSQL in a future sync feature) without touching business logic.
- **Hotkeys are decoupled from the UI.** `HotkeyManager` emits Qt signals; both the on-screen buttons and global hotkeys call the exact same `CounterManager` methods, so behavior is always consistent.
- **Plugin-ready by design.** v1.0 is 100% manual input, but the manager classes (`CounterManager`, `Database`) expose everything a future automatic-detection plugin (OCR, memory reading, Steam/Discord integration) would need to call into — without changing this code.

## Roadmap

### v1.0 (current)
- [x] Manual counter (+1 / -1 / Undo)
- [x] Games & Bosses management
- [x] OBS overlay
- [x] Global hotkeys
- [x] Statistics
- [x] SQLite persistence

### v1.5
- [ ] CSV / JSON import & export
- [ ] Additional themes
- [ ] Death-over-time graphs

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
>>>>>>> e2fc41f (Initial project structure)
