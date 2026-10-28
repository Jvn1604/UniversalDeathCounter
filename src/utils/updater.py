"""
In-place updates for installed copies.

The update checker finds the new release's installer on GitHub. This module
downloads it (only from this project's own GitHub releases, and only if its
size matches what GitHub reports), then starts it silently and lets the app
quit; the installer replaces the files and reopens the app. Portable copies
can't update themselves, so they get the release page instead.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path

from src.utils.constants import GITHUB_REPO
from src.utils.logger import get_logger

logger = get_logger(__name__)

INSTALLER_NAME = "UniversalDeathCounterSetup.exe"
_ALLOWED_PREFIX = f"https://github.com/{GITHUB_REPO}/releases/download/"
_CHUNK = 256 * 1024
_TIMEOUT_SECONDS = 20
# Inno Setup: no wizard pages, no message boxes, close the old copy if it's
# still running. installer.iss reopens the app after a silent install.
INSTALLER_ARGS = ("/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/CLOSEAPPLICATIONS")


class UpdateError(Exception):
    """The update couldn't be downloaded or started."""


def is_installed_copy(executable: Path | None = None) -> bool:
    """Whether this is the installed app (which has an uninstaller), not portable or source."""
    if executable is None:
        if not getattr(sys, "frozen", False):
            return False
        executable = Path(sys.executable)
    return any(executable.parent.glob("unins*.exe"))


def download_installer(
    url: str,
    destination: Path,
    expected_size: int,
    progress: Callable[[int, int], None] | None = None,
    cancelled: threading.Event | None = None,
) -> Path:
    """
    Download the installer to ``destination``.

    Args:
        url: Must be one of this project's GitHub release downloads.
        expected_size: The size GitHub reports; a different size is rejected.
        progress: Called with (bytes so far, total bytes).
        cancelled: Set it to stop the download.

    Raises:
        UpdateError: Wrong source, network failure, cancelled, or size mismatch.
    """
    if not url.startswith(_ALLOWED_PREFIX) or not url.endswith(INSTALLER_NAME):
        raise UpdateError(f"Refusing to download an update from {url}")
    if expected_size <= 0:
        raise UpdateError("The release doesn't say how big the installer is.")
    partial = destination.with_suffix(".part")
    received = 0
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response,
            open(partial, "wb") as file,
        ):
            while chunk := response.read(_CHUNK):
                if cancelled is not None and cancelled.is_set():
                    raise UpdateError("Download cancelled.")
                file.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, expected_size)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    if received != expected_size:
        partial.unlink(missing_ok=True)
        raise UpdateError(
            f"The download is {received} bytes instead of {expected_size}; not installing it."
        )
    partial.replace(destination)
    logger.info("Downloaded update installer to %s", destination)
    return destination


def launch_installer(installer: Path) -> None:
    """Start the installer silently, detached, so the app can quit right after."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(  # noqa: S603 - our own downloaded, size-checked installer
        [str(installer), *INSTALLER_ARGS], creationflags=flags, close_fds=True
    )
    logger.info("Started the update installer: %s", installer)
