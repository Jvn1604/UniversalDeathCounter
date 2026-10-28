<p align="center">
  <img src="assets/icons/readme_banner.png" alt="DePhantom Universal Death Counter (DUDC)" width="760">
</p>

<p align="center">
  <b>A free, lightweight death counter for Soulslike games and any PC game: it counts your deaths <i>automatically</i>, and it's built for streaming.</b>
</p>

<p align="center">
  <a href="https://github.com/Jvn1604/UniversalDeathCounter/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/Jvn1604/UniversalDeathCounter?color=ff4d4d&label=download"></a>
  <a href="https://github.com/Jvn1604/UniversalDeathCounter/actions/workflows/build-windows.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/Jvn1604/UniversalDeathCounter/build-windows.yml?branch=main"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-b56cff">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-43b581"></a>
</p>

---

## Download

**[⬇ Download the latest release](https://github.com/Jvn1604/UniversalDeathCounter/releases/latest)**

| File | What it is |
|---|---|
| `UniversalDeathCounterSetup.exe` | **Installer (recommended).** Start Menu and desktop shortcuts, plus an uninstaller. |
| `UniversalDeathCounter-<version>-portable.zip` | **Portable.** Unzip anywhere and run `UniversalDeathCounter.exe`. Data is stored next to it. |

> **"Windows protected your PC"?** The app isn't code-signed yet, so Windows SmartScreen warns about unknown publishers. Click **More info → Run anyway**. The full source is here and every release is built by GitHub Actions from this repository.

No Python or anything else needed. Windows 10 or 11.

## Screenshots

<p align="center">
  <img src="docs/screenshots/main-window.png" alt="Main window" width="420">
  &nbsp;
  <img src="docs/screenshots/overlay-dark.png" alt="Stream overlay" width="380">
</p>

| Auto death detection | Keyboard & controller bindings |
|---|---|
| <img src="docs/screenshots/auto-detect.png" alt="Auto death detection setup" width="420"> | <img src="docs/screenshots/controls.png" alt="Controls editor" width="420"> |
| **Statistics & graphs** | **Built-in OBS guide** |
| <img src="docs/screenshots/statistics.png" alt="Statistics" width="420"> | <img src="docs/screenshots/obs-guide.png" alt="OBS setup guide" width="420"> |

## Features

### 💀 Automatic death detection
- **Add a game straight from its `.exe`.** The app watches that game's window and counts a death whenever the death screen appears.
- **Works with any game.** Teach it the death screen once, either by pressing `F8` on the death screen or afterwards with **📷 Death Screen…**, which lets you pick the frame from the last few seconds.
- **Zero setup for Souls games.** The built-in preset recognizes Elden Ring, Dark Souls I–III and Sekiro.
- **No death screen? Use the health bar.** Mark your health bar once at full health, and a death counts when it empties.
- **Or the game's log file.** For games that log deaths, such as Minecraft, it counts every new line that matches your text. This mode doesn't capture the screen at all.
- **Missed a death?** Add another death screen in two clicks. Any saved one counts.
- **Switches to the right game** when you launch it, and starts a fresh session.
- **Screen capture only:** no memory reading and no injection, so it's safe with anti-cheat.

### 🎮 Controls, your way
- Global hotkeys work while the game is focused (defaults below).
- **Xbox, PlayStation (DualShock 4 / DualSense) and most other controllers.** Bind a button combo such as *View/Share + D-pad Up*. One binding works on both kinds of pad.
- **Keybind editor with live conflict detection.** It flags duplicates, keys that would block typing, keys another program already took, and overlapping combos.

### 📺 Made for streaming
- **OBS-ready overlay:** a translucent card, or green-screen mode for OBS's Chroma Key. Pick which number it shows, plus its color, font size and lines.
- **`deaths.txt`** for OBS Text sources, with your own template, e.g. `{game} - {boss}: {deaths}`.
- **Help → Set Up OBS Overlay** walks you through both methods, with one-click setup buttons.
- **Multi-monitor:** move the overlay to any display. Windows come back on-screen if a monitor is unplugged.

### 📊 Tracking & stats
- Session, boss and lifetime counts, all at once. **Set Exact Count** and **Undo** are always available.
- Mark bosses **Defeated ✓** to keep your "deaths until victory" forever.
- Notes on individual deaths, session history, and graphs: per boss, over time, and per session.
- Ready-made boss lists for Elden Ring, Dark Souls III, Sekiro, Bloodborne, Hollow Knight and Cuphead.
- **Multiple profiles**, JSON backup and restore, and CSV export.

### 🪶 Lightweight
- The whole app is ~100 MB installed and adds **no** background services.
- Detection checks the game window 5 times a second and stops when the game isn't running.
- Controller polling only runs while a pad is connected.
- Your data is a local SQLite file, and nothing is uploaded. The only network request is an optional update check against GitHub Releases.

## Quick start

1. Install and open **DUDC**.
2. In the **Game** dropdown, choose **+ Add game from .exe…** and pick your game's `.exe` (for example `eldenring.exe`).
3. Launch the game in **borderless or windowed** mode.
4. Die. 💀
   - **Souls games** are counted automatically.
   - **Any other game:** the first time, press `F8` on the death screen and drag a box around the death text. From then on deaths are counted automatically.
5. Streaming? Open **Help → Set Up OBS Overlay…**.

You can always count by hand too: **+1 Death** (`F9`), **-1** (`F10`), **Undo** (`F11`).

## Default controls

| Action | Keyboard | Controller |
|---|---|---|
| +1 Death | `F9` | not set |
| -1 Death | `F10` | not set |
| Undo | `F11` | not set |
| Toggle overlay | `Ctrl+F12` | not set |
| Calibrate death screen | `F8` | not set |
| Pause / resume auto-detect | `Ctrl+F8` | not set |

To change any of them, go to **Settings → Preferences… → Controls**:
- **Keyboard:** click a field and press a key.
- **Controller:** click **Record**, then hold a button combo and release it.

Controller presses also reach the game, so use a combo, not a single button.

## Auto death detection: how it works

Pick a method per game in **Manage → Auto Death Detection…**:

| Method | Best for | Setup |
|---|---|---|
| **Calibrated death screen** | Any game with a death screen | Press `F8` on the death screen and box the death text |
| **Souls preset** | Elden Ring, Dark Souls I–III, Sekiro | None |
| **Health bar empties** | Games without a death screen | At full health, press `F8` and box your health bar |
| **Game log file** | Games that write deaths to a log (e.g. Minecraft) | Choose the log file and the death text, then click **Test** |

**Death screens:** DUDC grabs the game's window a few times per second. It compares the area where the death text appears with the death screens you've saved, using a contrast-independent image match, so fade-ins and brightness changes don't matter.

**Health bar:** a death counts when the bar stays empty for a second *after your health was already below about 60%*. That's why opening a menu or map, which hides the HUD at full health, never counts. The catch: a one-hit kill from high health is missed, so press `F9` for those. Death screens you add still count in this mode too.

**Log file:** each new line matching your text is one death. Lines already in the file when detection starts are skipped, and a new log from the next game launch is followed automatically. The text is a case-insensitive regular expression, so `|` separates alternatives. In Minecraft, for example, use `latest.log` in `%APPDATA%\.minecraft\logs` with `YourName (was slain|died|fell|drowned|burned|blew up)`. In multiplayer, include your name so other players' deaths don't count.

To keep the count accurate:
- **No double counting:** a death needs about half a second of death screen, and a long death screen counts once.
- **Cooldown:** a short gap between deaths is enforced (8 s by default, adjustable).
- **Pause** with `Ctrl+F8` for cutscenes, co-op, or watching someone else play.
- **Calibrate tightly:** box just the death text (like "YOU DIED"), not the game world behind it.

**Supported:** any game with a consistent death screen, a visible health bar, or a log that records deaths. Elden Ring, Dark Souls I–III and Sekiro work with no setup.

**Limitations:**
- Exclusive-fullscreen games may capture as black. Switch to borderless or windowed mode; the app tells you if this happens.
- Games with no death screen, no health bar and no death log can't be detected. Use the hotkeys there.
- The Souls preset is a color heuristic. If it ever misfires, calibrate that game instead.

## Troubleshooting

**A hotkey doesn't work / "Hotkey unavailable"**
Another program has already registered that key. On many PCs plain `F12` is taken. Pick another key in **Settings → Controls**; the editor warns you as you type.

**Deaths aren't detected**
1. Check the status line under the game selector. It should say *"Watching <game>.exe for deaths"*.
2. If it says the capture is **black**, switch the game to borderless or windowed mode.
3. If it's watching but misses deaths, use **📷 Death Screen…** right after a death to add that screen.

**The overlay shows a green box in OBS**
Add a **Chroma Key** filter to the source (Key Color Type: Green). See **Help → Set Up OBS Overlay**.

**My antivirus complains**
False positives happen with unsigned apps. DUDC uses Windows' own hotkey API (no keyboard hook) and ships as a normal folder build to keep this to a minimum. You can check every build's source and logs under [Actions](https://github.com/Jvn1604/UniversalDeathCounter/actions).

**Where is my data?**
- **Installer:** `%APPDATA%\UniversalDeathCounter\saves\`
- **Portable:** the `saves` folder next to the exe.

**File → Export Backup** saves everything to one JSON file.

## Build from source

Requires Windows and Python 3.12+.

```powershell
git clone https://github.com/Jvn1604/UniversalDeathCounter.git
cd UniversalDeathCounter
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python -m src.app
```

| Task | Command |
|---|---|
| Run tests | `.\venv\Scripts\python -m pytest` |
| Lint and conflict-marker checks | `.\venv\Scripts\pre-commit run --all-files` (or `pre-commit install` once to run them on every commit) |
| Build the app folder | `.\venv\Scripts\pyinstaller packaging\UniversalDeathCounter.spec` → `dist\UniversalDeathCounter\` |
| Build the installer | `iscc packaging\installer.iss` ([Inno Setup 6](https://jrsoftware.org/isinfo.php)) |
| Regenerate icons / screenshots | `python packaging\make_icons.py` / `python packaging\make_screenshots.py` |

**Releasing:**
1. Bump `APP_VERSION` in `src/utils/constants.py`.
2. Merge to `main`.
3. Push a matching tag such as `v2.0.0`.

GitHub Actions then tests, builds the installer and portable zip, and publishes the release. If the repository secrets are set, it also code-signs them; see [docs/code-signing.md](docs/code-signing.md).

<details>
<summary><b>Project structure</b></summary>

```
src/
├── app.py            # Entry point
├── core/             # Counter, session and statistics logic
├── database/         # SQLite layer (the only module with SQL)
├── detection/        # Window capture, death-screen matchers, watcher thread
├── hotkeys/          # Windows hotkeys, controllers, conflict detection
├── overlay/          # OBS overlay window
├── ui/               # Main window and dialogs
├── themes/           # Dark / light stylesheets
└── utils/            # Constants, logging, profiles, startup, screens, exporters
packaging/            # PyInstaller spec, Inno Setup script, signing, icon/screenshot tools
tests/                # pytest suite (130+ tests)
```

Design notes:
- **Event-sourced counting:** every +1 and -1 is a row with a signed `delta`, so undo, history and graphs come for free.
- **Detection only reads the screen** through pure-numpy matchers, so it's unit tested without a game.
- **No heavy dependencies:** PySide6, numpy, mss and psutil. Windows APIs (hotkeys, controllers, window lookup) are called directly through `ctypes`.

</details>

## Roadmap

- [x] Automatic death detection with per-game calibration and a Souls preset
- [x] Xbox and PlayStation controller bindings, plus a keybind editor with conflict detection
- [x] Multi-monitor support, and an OBS setup guide
- [ ] More presets (Hollow Knight / Silksong, Lies of P, Cuphead) and shareable preset files
- [ ] Live detection score and sensitivity slider
- [ ] Fullscreen capture via Windows Graphics Capture
- [ ] Play time per session and personal-best attempts

Ideas and bug reports are welcome in [Issues](https://github.com/Jvn1604/UniversalDeathCounter/issues).

## Contributing

1. Fork the repo and create a branch.
2. Run `pre-commit install` once so commits are checked for lint errors and leftover merge-conflict markers.
3. Add tests for logic changes and make sure `pytest` passes.
4. Open a pull request explaining what changed and why.

## License

[MIT](LICENSE) © Jeeventhiran Sivanantham
