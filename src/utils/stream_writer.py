"""
deaths.txt output for OBS Text Sources.

Many streamers use OBS's *Text (GDI+/FreeType2) → Read from file* feature
instead of window-capturing an overlay. This module renders a user-defined
template (e.g. ``"{game} - {boss}: {deaths}"``) and writes it to a text
file on every counter change, so the on-stream number updates instantly.

Supported placeholders:
    {game}         current game name (or "No Game")
    {boss}         current boss name (or empty)
    {deaths}       the number from the user's chosen counter source
                   (session / boss / total — same as the overlay setting)
    {session}      session death count
    {boss_deaths}  current boss's death count
    {total}        game total death count
"""

from __future__ import annotations

from pathlib import Path

from src.core.counter_manager import CounterSnapshot
from src.utils.logger import get_logger

logger = get_logger(__name__)


def render_template(template: str, snapshot: CounterSnapshot, counter_source: str) -> str:
    """
    Render a deaths.txt template against a counter snapshot.

    Placeholder substitution is done with plain string replacement (not
    ``str.format``) so stray braces in a user's template can never raise.

    Args:
        template: The user-defined template string.
        snapshot: The current counter state.
        counter_source: "session", "boss", "total" or "run" — which number the
            generic ``{deaths}`` placeholder resolves to.

    Returns:
        The rendered single-line (or multi-line) text.
    """
    source_values = {
        "session": snapshot.session_deaths,
        "boss": snapshot.boss_deaths,
        "total": snapshot.total_deaths,
        "run": snapshot.run_deaths,
    }
    deaths = source_values.get(counter_source, snapshot.session_deaths)

    replacements = {
        "{game}": snapshot.game_name or "No Game",
        "{boss}": snapshot.boss_name or "",
        "{deaths}": str(deaths),
        "{session}": str(snapshot.session_deaths),
        "{boss_deaths}": str(snapshot.boss_deaths),
        "{total}": str(snapshot.total_deaths),
    }
    result = template
    for token, value in replacements.items():
        result = result.replace(token, value)
    return result


def write_deaths_file(path: Path, content: str) -> bool:
    """
    Write rendered text to the deaths file.

    Args:
        path: Destination file path.
        content: Rendered text to write.

    Returns:
        ``True`` on success, ``False`` if the write failed (logged, never
        raised — a broken stream file must not crash the counter).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        logger.exception("Failed to write deaths file at %s", path)
        return False
