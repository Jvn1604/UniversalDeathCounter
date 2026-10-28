"""
Non-blocking update check against GitHub Releases.

On startup and every few hours (if enabled in settings), or when the player
clicks Check, a background thread asks GitHub for the latest release and
compares it to the running version. The GitHub API allows only 60 requests
an hour per internet connection, so when it refuses, the version is read from
the public "latest release" page instead. Qt signals hop back to the main
thread; a failed check is only reported, never raised.
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
# Redirects to .../releases/tag/<latest tag>; not limited like the API.
_LATEST_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
_DOWNLOAD_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{{tag}}/{INSTALLER_NAME}"
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
            newer version exists.
        up_to_date: Emitted with the latest version when this one is current.
        check_failed: Emitted when GitHub couldn't be reached at all.
    """

    update_available = Signal(str, str)
    up_to_date = Signal(str)
    check_failed = Signal()

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
            tag, release_url = self._from_api()
        except Exception:  # noqa: BLE001 - network failures are expected/benign
            logger.debug("Update check via the API failed; trying the releases page", exc_info=True)
            try:
                tag, release_url = self._from_release_page()
            except Exception:  # noqa: BLE001
                logger.debug("Update check failed (offline or repo unavailable)", exc_info=True)
                self.check_failed.emit()
                return
        if _parse_version(tag) > _parse_version(APP_VERSION):
            logger.info("Update available: %s (current %s)", tag, APP_VERSION)
            # Cross-thread signal emission is safe: Qt queues it to the
            # receiver's (main) thread automatically.
            self.update_available.emit(tag, release_url)
        else:
            self.up_to_date.emit(tag)

    def _from_api(self) -> tuple[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        request = urllib.request.Request(_API_URL, headers=headers)
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        tag = str(payload.get("tag_name", ""))
        if not tag:
            raise ValueError("no tag in the API answer")
        for asset in payload.get("assets") or []:
            if asset.get("name") == INSTALLER_NAME:
                self.installer_url = str(asset.get("browser_download_url", ""))
                self.installer_size = int(asset.get("size") or 0)
        return tag, str(payload.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"))

    def _from_release_page(self) -> tuple[str, str]:
        """The latest tag from where the releases page redirects, plus the installer's size."""
        request = urllib.request.Request(_LATEST_PAGE, method="HEAD")
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            release_url = response.geturl()
        marker = f"/{GITHUB_REPO}/releases/tag/"
        if marker not in release_url:
            raise ValueError(f"unexpected release page: {release_url}")
        tag = release_url.split(marker, 1)[1].strip("/")
        try:
            url = _DOWNLOAD_URL.format(tag=tag)
            head = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(head, timeout=_TIMEOUT_SECONDS) as response:
                size = int(response.headers.get("Content-Length") or 0)
            if size > 0:  # the updater insists on knowing the size
                self.installer_url, self.installer_size = url, size
        except Exception:  # noqa: BLE001 - no installer: the release page opens instead
            logger.debug("Couldn't find the installer of %s", tag, exc_info=True)
        return tag, release_url
