# Auto-detect setups library

Ready-made auto-detect setups that DUDC players can download in the app
(**Detection → Setups Library**). Each `*.dudc.json` file is one game's
setup:
- the detection mode
- the captured death, boss-victory and pause screens, as small grey patches
  placed by fractions of the window, so they work at any resolution
- the game's boss list.

Nothing tied to one PC is included (no install paths, user names, OBS sources
or display numbers).

## Adding a game

1. In DUDC, set up auto-detect for the game and check that it counts your
   deaths.
2. On the Detection page, choose **Share Setup…** and save the file.
3. Send it in, either way:
   - open an issue and attach the file
   - make a pull request that adds it here and runs
     `python packaging/make_presets.py` to update `index.json`
