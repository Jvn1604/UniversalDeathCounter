# Changelog

What changed in each version of DePhantom Universal Death Counter (DUDC),
newest first. Downloads are on the
[Releases page](https://github.com/Jvn1604/UniversalDeathCounter/releases).

## [Unreleased]

### New
- **Every game has its own profile.** The box at the top right is now the game
  you're playing (*GAME · Elden Ring*). Adding a game creates its profile and
  switches to it, loading a save does the same for its game, and launching a
  game switches to its profile by itself. Your keys, theme and overlay look are
  the same in every profile.
- On the first start after updating, games that shared a profile (and any in
  Default) move to their own profiles, with everything they have: deaths,
  bosses, sessions, death screens, speedrun splits and runs, the boss you had
  picked, and a run in progress. A backup is saved in Saved Progress first,
  and a game only leaves its old profile once the new one has every death.
- All profiles share one Saved Progress folder; saves made in a profile before
  are moved there (never over a file of the same name).
- Clear All Data saves a copy in Saved Progress first, so Load Progress can
  bring it back.
- **What's New** inside the app (menu, top right, or About): every version's
  changes. It opens by itself once after an update, showing what it brought.

### Fixed
- **Loading a save no longer doubles your deaths.** *Add Alongside* with a game
  you already have combines it: sessions, deaths, bosses, screens and runs that
  are already there are skipped.
- **Autosave keeps up.** The quick save no longer waits for a pause in deaths,
  Windows shutting down or logging off saves first, a save file held by
  OneDrive or an antivirus is written once it's free, and a failed save says so
  instead of showing an old time.
- **Auto-detect no longer stops for good** when Windows refuses a screen capture
  for a moment (lock screen, admin prompt, display change). It waits two
  seconds and carries on.
- **F9 / F10 / F11 with no game picked** now say the death wasn't counted and how
  to pick or add a game, instead of doing nothing.

### Changed
- The save-file death count is marked **Experimental**: some save formats can't
  be read yet.

## [2.19.0] - 2026-11-07

### New
- **Choose what to install:** everything, the death counter only, or the
  speedrun timer only. Change it later in Settings → General → Features.
- **Roll back to an earlier version** from the menu (top right, the three dots), if an update causes
  trouble. Your games, deaths and settings stay.
- **Overlay designs can be coloured:** accent, number and word colours and the
  font, for Kanji Seal, Neon Sign, Tombstone and Death Banner, on the overlay
  and the OBS page.
- **Black outline for overlay text** (the new default), so light text stays
  readable on bright scenes; the soft shadow is still a choice.
- **Keep counting in the background:** closing the window offers to keep F9 /
  F10, the overlay and auto-detect running in the tray.
- **Key check** in Settings → Controls: press a key anywhere, even in a game,
  and it shows when the app receives it. It also explains Fn on laptops.
- The Detection page names the next of three setup steps.

### Fixed
- **Death screens taught from an uploaded screenshot count again,** even when
  the screenshot is framed a little differently from the game (whole monitor,
  a title bar, another resolution).
- **F9 / F10 with the window closed, minimised or behind another app:** the keys
  are registered again after sleep, retried when Windows is slow to free them,
  and picked up as soon as another program that held them lets go.
- **Two monitors:** F8 (teach the death screen) watches the display the game is
  on.
- **The overlay and timer remember their place and size** between starts, even
  when a second monitor is off for a while.
- Save, Apply and Discard only light up once something changed.
- Labels no longer stay grey after a button becomes usable.

### Changed
- Clearer F9 / F10 / F11 key badges.
- The Controls page is laid out more cleanly.
- Lighter: drawn overlay designs are painted once per change, auto-detect holds
  one screen frame less, the controller check rests when no buttons are bound,
  and a tall death-text area costs about a fifth of what it did.

## [2.17.0] - 2026-11-06

### New
- **The game's own death count from its save file**, including deaths from
  before you installed DUDC and from earlier NG+ cycles (with a *this cycle
  only* option).
- **Exclusive-fullscreen games** can be watched on Windows (Desktop
  Duplication).
- **Overlay designs:** Kanji Seal, Neon Sign, Tombstone and Death Banner, with a
  skull that evolves as deaths pile up.
- **Setups Library:** ready-made auto-detect setups, shared between players.
- **Switch off features you don't use** (timer, stats, console, mini mode).
- Home as a bento grid; a friendlier first start with an add-game menu.

### Fixed
- The count looked reset right after an in-app update.
- About a third less memory.

## [2.16.0] - 2026-11-01

### New
- A guide with a live checklist, bug reports from inside the app, an OBS
  Browser Source page for the overlay, and ways to write the count
  (*DEATH - 12*, *12 DEATHS*...).

### Changed
- Settings polish and fixes from the bug sheet.

## [2.15.0] - 2026-10-31

### New
- Real Glass and Clay themes, and optional game artwork.

## [2.14.0] - 2026-10-31

### New
- More overlay options, and auto-detect without the game's .exe (watch a whole
  display).

## [2.13.0] - 2026-10-31

### New
- A Home dashboard, a Death Counter page, and Settings inside the main window.

## [2.12.0] - 2026-10-30

### New
- Continue past sessions and speedrun runs, and count deaths per run.

## [2.11.1] - 2026-10-30

### Fixed
- The count is kept after an update or restart.

## [2.11.0] - 2026-10-30

### New
- **macOS and Linux** versions.
- A friendly Home dashboard, the evolving skull, and a Quick Start guide.

## [2.9.0] - 2026-10-29

### New
- **Console players:** a phone remote, and watching a capture-card window or an
  OBS source.

## [2.8.2] - 2026-10-29

### Changed
- An update card in the sidebar; update checks survive GitHub's rate limit.

## [2.8.1] - 2026-10-28

### Fixed
- Settings freezing.

### Changed
- Faster detection and a smaller install.

## [2.8.0] - 2026-10-28

### New
- Run-only timer keys, a welcome guide, mini mode and one-click updates.

## [2.7.1] - 2026-10-28

### New
- Boss-kill detection: bosses are marked defeated, the next boss is picked, and
  the timer can split by itself.
- A new look: a dark gaming dashboard with sidebar pages.

### Fixed
- Crash recovery, backups, memory, and a case of lost data found in testing.

## [2.5.0] - 2026-10-28

### New
- Health-bar and log-file death detection.
- Fonts, background images and overlay styling.
- A speedrun timer: splits, personal bests, golds, deaths per run, game time,
  auto-pause, crash recovery, run history and records.

### Fixed
- Tray notifications crashing; counters, OBS capture and the graph.

## [2.0.0] - 2026-10-28

### New
- **Automatic death detection** from the screen, controller support, and the
  DUDC name.

[Unreleased]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.19.0...HEAD
[2.19.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.17.0...v2.19.0
[2.17.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.16.0...v2.17.0
[2.16.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.15.0...v2.16.0
[2.15.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.14.0...v2.15.0
[2.14.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.13.0...v2.14.0
[2.13.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.12.0...v2.13.0
[2.12.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.11.1...v2.12.0
[2.11.1]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.11.0...v2.11.1
[2.11.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.9.0...v2.11.0
[2.9.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.8.2...v2.9.0
[2.8.2]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.8.1...v2.8.2
[2.8.1]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.8.0...v2.8.1
[2.8.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.7.1...v2.8.0
[2.7.1]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.5.0...v2.7.1
[2.5.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v2.0.0...v2.5.0
[2.0.0]: https://github.com/Jvn1604/UniversalDeathCounter/compare/v1.5.0...v2.0.0
