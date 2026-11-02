"""
After an in-app update the installer reopened the app as administrator; it
could then write next to its .exe in Program Files and started a new, empty
database there (count 0, no sessions) until the next normal start.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import constants  # noqa: E402


@pytest.fixture()
def frozen(tmp_path, monkeypatch):
    """A frozen Windows build whose .exe can be placed anywhere under ``tmp_path``."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(constants, "IS_WINDOWS", True)
    appdata = tmp_path / "AppData"
    monkeypatch.setattr(constants, "user_data_dir", lambda org: appdata / org)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))
    monkeypatch.delenv("ProgramW6432", raising=False)

    def place(folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sys, "executable", str(folder / "UniversalDeathCounter.exe"))
        return constants._resolve_persistent_data_dir()

    return place, appdata


def test_installed_in_program_files_always_uses_appdata(frozen, tmp_path) -> None:
    place, appdata = frozen
    # Writable here (as when run as administrator), but still the player's folder.
    folder = tmp_path / "Program Files" / "DePhantom Universal Death Counter"
    assert place(folder) == appdata / constants.APP_ORG / "saves"
    assert not (folder / "saves").exists()  # no empty database left in Program Files
    x86 = tmp_path / "Program Files (x86)" / "DUDC"
    assert place(x86) == appdata / constants.APP_ORG / "saves"


def test_portable_and_custom_folders_keep_their_data_next_to_the_exe(frozen, tmp_path) -> None:
    place, _appdata = frozen
    portable = tmp_path / "Games" / "DUDC"
    assert place(portable) == portable / "saves"
    # A folder merely named like Program Files elsewhere is not Program Files.
    lookalike = tmp_path / "Program Files Backup" / "DUDC"
    assert place(lookalike) == lookalike / "saves"


def test_the_installer_reopens_the_app_as_the_player() -> None:
    script = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text()
    silent = [line for line in script.splitlines() if "skipifnotsilent" in line]
    assert silent and all("runasoriginaluser" in line for line in silent)
