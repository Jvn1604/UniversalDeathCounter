"""
Profile management: multiple independent databases.

A "profile" is simply a separate SQLite database file, letting players keep
e.g. "Main Runs" and "Co-op Nights" completely isolated. The registry lives
in ``saves/profiles.json``; the legacy pre-profiles database is preserved
as the built-in "Default" profile so upgrading users lose nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.utils.constants import DATABASE_PATH, SAVES_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PROFILE_NAME = "Default"
_PROFILES_SUBDIR = "profiles"


class ProfileManager:
    """Reads/writes the profile registry and resolves database paths."""

    def __init__(self, saves_dir: Path = SAVES_DIR) -> None:
        """
        Args:
            saves_dir: Directory holding profiles.json and profile DB files.
        """
        self._saves_dir = saves_dir
        self._registry_path = saves_dir / "profiles.json"
        self._registry: dict = self._load_registry()

    # ----------------------------------------------------------------
    # Registry persistence
    # ----------------------------------------------------------------
    def _load_registry(self) -> dict:
        if self._registry_path.exists():
            try:
                data = json.loads(self._registry_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "profiles" in data and "active" in data:
                    return data
            except (OSError, json.JSONDecodeError):
                logger.exception("Could not read profiles.json; recreating registry")
        # Fresh registry: Default profile maps to the legacy database path so
        # existing users keep their data after upgrading.
        return {
            "active": DEFAULT_PROFILE_NAME,
            "profiles": {DEFAULT_PROFILE_NAME: DATABASE_PATH.name},
        }

    def _save_registry(self) -> None:
        self._saves_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path.write_text(
            json.dumps(self._registry, indent=2), encoding="utf-8"
        )

    # ----------------------------------------------------------------
    # Queries
    # ----------------------------------------------------------------
    def list_profiles(self) -> list[str]:
        """Return all profile names, Default first, rest alphabetical."""
        names = sorted(self._registry["profiles"].keys())
        if DEFAULT_PROFILE_NAME in names:
            names.remove(DEFAULT_PROFILE_NAME)
            names.insert(0, DEFAULT_PROFILE_NAME)
        return names

    @property
    def active_profile(self) -> str:
        """The currently active profile's name."""
        active = self._registry.get("active", DEFAULT_PROFILE_NAME)
        if active not in self._registry["profiles"]:
            active = DEFAULT_PROFILE_NAME
        return active

    def active_db_path(self) -> Path:
        """Absolute path of the active profile's database file."""
        relative = self._registry["profiles"][self.active_profile]
        return self._saves_dir / relative

    # ----------------------------------------------------------------
    # Mutations
    # ----------------------------------------------------------------
    def create_profile(self, name: str) -> None:
        """
        Register a new, empty profile.

        Args:
            name: Human-readable profile name (must be unique).

        Raises:
            ValueError: If the name is empty or already exists.
        """
        name = name.strip()
        if not name:
            raise ValueError("Profile name cannot be empty.")
        if name in self._registry["profiles"]:
            raise ValueError(f"A profile named '{name}' already exists.")

        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower() or "profile"
        filename = f"{_PROFILES_SUBDIR}/{slug}.db"
        counter = 2
        existing_files = set(self._registry["profiles"].values())
        while filename in existing_files:
            filename = f"{_PROFILES_SUBDIR}/{slug}_{counter}.db"
            counter += 1

        (self._saves_dir / _PROFILES_SUBDIR).mkdir(parents=True, exist_ok=True)
        self._registry["profiles"][name] = filename
        self._save_registry()
        logger.info("Created profile '%s' -> %s", name, filename)

    def set_active(self, name: str) -> None:
        """Switch the active profile. Raises ``ValueError`` if unknown."""
        if name not in self._registry["profiles"]:
            raise ValueError(f"Unknown profile: {name}")
        self._registry["active"] = name
        self._save_registry()
        logger.info("Active profile set to '%s'", name)

    def delete_profile(self, name: str, delete_file: bool = True) -> None:
        """
        Remove a profile from the registry (optionally deleting its DB file).

        The Default profile cannot be deleted. If the deleted profile was
        active, Default becomes active.

        Raises:
            ValueError: If attempting to delete the Default profile or an
                unknown profile.
        """
        if name == DEFAULT_PROFILE_NAME:
            raise ValueError("The Default profile cannot be deleted.")
        if name not in self._registry["profiles"]:
            raise ValueError(f"Unknown profile: {name}")

        relative = self._registry["profiles"].pop(name)
        if self._registry.get("active") == name:
            self._registry["active"] = DEFAULT_PROFILE_NAME
        self._save_registry()

        if delete_file:
            db_file = self._saves_dir / relative
            try:
                db_file.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not delete profile database %s", db_file)
        logger.info("Deleted profile '%s'", name)
