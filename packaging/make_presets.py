"""
Rebuild the online library's list (``presets/index.json``) from the setup
files in ``presets/``. Checks each file as the app does. Run after adding or
changing a preset:

    python packaging/make_presets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.presets import PRESET_SUFFIX, library_index, preset_file_name, read_preset  # noqa: E402


def main() -> None:
    folder = ROOT / "presets"
    presets = []
    for path in sorted(folder.glob(f"*{PRESET_SUFFIX}")):
        preset = read_preset(path)  # raises on a damaged or unsafe file
        if path.name != preset_file_name(preset):
            raise SystemExit(f"{path.name}: should be named {preset_file_name(preset)}")
        presets.append(preset)
    index = library_index(presets)
    (folder / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    print(f"presets/index.json: {len(presets)} setups")


if __name__ == "__main__":
    main()
