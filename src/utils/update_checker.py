"""
Non-blocking update check against GitHub Releases.

On startup (if enabled in settings), a background thread queries the
GitHub API for the latest release tag and compares it to the running
version. Qt signals are used to hop back to the main thread; network
failures are silently ignored — an update check must never disturb or
crash the app.
"""

from __future__ import annotations

import json
import threading
import urllib.request

from PySide6.QtCore import QObject, Signal

from src.utils.constants import APP_VERSION, GITHUB_REPO
from src.utils.logger import get_logger
from src.utils.updater import INSTALLER_NAME

logger = get_logger(__name__)

_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_TIMEOUT_SECONDS = 6


def _parse_version(text: str) -> tuple[int, ...]:
    """Parse 'v1.5.0' / '1.5.0' into a comparable tuple, ignoring junk."""
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else (0,)


class UpdateChecker(QObject):
    """
    Checks GitHub for a newer release in a daemon thread.

    Signals:
        update_available: Emitted with (latest_version, release_url) when a
            newer version exists. Never emitted on failure or when current.
    """

    update_available = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # The new release's installer, for in-place updates (set before the
        # signal fires; empty if the release has none).
        self.installer_url = ""
        self.installer_size = 0

    def check_async(self) -> None:
        """Start the check in a background daemon thread and return."""
        thread = threading.Thread(target=self._check, daemon=True)
        thread.start()

    def _check(self) -> None:
        try:
            request = urllib.request.Request(
                _API_URL, headers={"Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - network failures are expected/benign
            logger.debug("Update check failed (offline or repo unavailable)", exc_info=True)
            return

        latest_tag = str(payload.get("tag_name", ""))
        release_url = str(payload.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"))
        if not latest_tag:
            return

        for asset in payload.get("assets") or []:
            if asset.get("name") == INSTALLER_NAME:
                self.installer_url = str(asset.get("browser_download_url", ""))
                self.installer_size = int(asset.get("size") or 0)
        if _parse_version(latest_tag) > _parse_version(APP_VERSION):
            logger.info("Update available: %s (current %s)", latest_tag, APP_VERSION)
            # Cross-thread signal emission is safe: Qt queues it to the
            # receiver's (main) thread automatically.
            self.update_available.emit(latest_tag, release_url)
