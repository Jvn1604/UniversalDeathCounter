"""
Speedrun timer: splits, comparisons, personal records, and deaths per run.

Everything here is plain Python (no Qt) and takes an injectable clock, so the
timing logic is unit tested without waiting. The UI polls
:meth:`SpeedrunController.view` while a run is going and renders the result.

Terms, as in LiveSplit:

* **split** — one checkpoint of a run (e.g. a boss); its time is cumulative.
* **segment** — the time between two consecutive splits.
* **PB** — personal best: the fastest finished run with the same splits.
* **gold** — a segment faster than that segment has ever been.
* **sum of best** — all best segments added up: the theoretical best run.
* **real time** — wall-clock time; only a manual pause stops it.
* **game time** — real time minus loads, pause screens and other moments the
  game isn't being played (detected automatically; see ``set_game_paused``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
FINISHED = "finished"

REAL = "real"
GAME = "game"

COMPARE_PB = "pb"
COMPARE_PREVIOUS = "previous"
COMPARE_BEST = "best"
COMPARISON_LABELS = {
    COMPARE_PB: "Personal Best",
    COMPARE_PREVIOUS: "Previous Run",
    COMPARE_BEST: "Best Segments",
}

# A run with no splits set up still has one: reaching the end.
DEFAULT_SPLIT_NAME = "Finish"


# ----------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------
def format_time(ms: int | None, digits: int = 2) -> str:
    """
    ``1:02:03.45``, ``2:03.45`` or ``0:03.45``; ``-`` for no time.

    Args:
        digits: Decimals after the seconds: 0, 1, 2 (default) or 3 (milliseconds).
    """
    if ms is None:
        return "-"
    ms = max(ms, 0)
    digits = min(max(digits, 0), 3)
    seconds = (ms // 1000) % 60
    minutes = (ms // 60_000) % 60
    hours = ms // 3_600_000
    text = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
    if digits:
        fraction = (ms % 1000) // (10 ** (3 - digits))
        text += f".{fraction:0{digits}d}"
    return text


def format_delta(ms: int) -> str:
    """Signed difference to the comparison: ``-12.42``, ``+5.31``, ``+1:05.31``."""
    sign = "-" if ms < 0 else "+"
    ms = abs(ms)
    hundredths = (ms // 10) % 100
    seconds = ms // 1000
    if seconds < 60:
        return f"{sign}{seconds}.{hundredths:02d}"
    return f"{sign}{seconds // 60}:{seconds % 60:02d}.{hundredths:02d}"


# ----------------------------------------------------------------
# Runs and comparisons
# ----------------------------------------------------------------
@dataclass(slots=True)
class RunRecord:
    """One attempt: cumulative split times (None = skipped / not reached)."""

    split_names: list[str]
    split_times: list[int | None]  # real time
    finished: bool
    deaths: int = 0
    started_at: str = ""
    ended_at: str = ""
    game_times: list[int | None] = field(default_factory=list)
    run_id: int | None = None

    def times(self, method: str = REAL) -> list[int | None]:
        """Cumulative times by timing method (runs saved before game time: all None)."""
        if method != GAME:
            return self.split_times
        padded = list(self.game_times[: len(self.split_times)])
        return padded + [None] * (len(self.split_times) - len(padded))

    def total(self, method: str = REAL) -> int | None:
        times = self.times(method)
        return times[-1] if self.finished and times else None

    @property
    def total_ms(self) -> int | None:
        return self.total(REAL)


def segment_times(times: list[int | None]) -> list[int | None]:
    """Per-split segment durations; None where a split or the one before is missing."""
    segments: list[int | None] = []
    previous: int | None = 0
    for cumulative in times:
        if cumulative is None or previous is None:
            segments.append(None)
        else:
            segments.append(cumulative - previous)
        previous = cumulative
    return segments


def personal_best(runs: list[RunRecord], method: str = REAL) -> RunRecord | None:
    """The fastest finished run, if any."""
    timed = [run for run in runs if run.total(method) is not None]
    return min(timed, key=lambda run: run.total(method) or 0, default=None)


def best_segments(runs: list[RunRecord], count: int, method: str = REAL) -> list[int | None]:
    """The fastest time ever recorded for each of ``count`` segments."""
    best: list[int | None] = [None] * count
    for run in runs:
        for index, segment in enumerate(segment_times(run.times(method)[:count])):
            if segment is not None and (best[index] is None or segment < best[index]):
                best[index] = segment
    return best


def sum_of_best(best: list[int | None]) -> int | None:
    """All best segments added up, or None until every segment has one."""
    if not best or any(segment is None for segment in best):
        return None
    return sum(segment for segment in best if segment is not None)


def cumulative(segments: list[int | None]) -> list[int | None]:
    """Running totals of segments (None from the first missing one on)."""
    totals: list[int | None] = []
    running: int | None = 0
    for segment in segments:
        running = None if running is None or segment is None else running + segment
        totals.append(running)
    return totals


@dataclass(slots=True)
class Records:
    """Personal records for one game's splits."""

    attempts: int = 0
    finished: int = 0
    pb: RunRecord | None = None
    fewest_deaths: RunRecord | None = None  # among finished runs
    sum_of_best: int | None = None
    best_segments: list[tuple[str, int | None]] = field(default_factory=list)


def compute_records(
    runs: list[RunRecord], split_names: list[str], attempts: int, method: str = REAL
) -> Records:
    finished = [run for run in runs if run.finished]
    best = best_segments(runs, len(split_names), method)
    return Records(
        attempts=attempts,
        finished=len(finished),
        pb=personal_best(runs, method),
        fewest_deaths=min(
            finished, key=lambda run: (run.deaths, run.total(method) or 0), default=None
        ),
        sum_of_best=sum_of_best(best),
        best_segments=list(zip(split_names, best, strict=False)),
    )


# ----------------------------------------------------------------
# The timer itself
# ----------------------------------------------------------------
class SpeedrunTimer:
    """
    Start / split / pause / undo / skip / reset, with real and game time.

    States: idle → running ⇄ paused → finished. Splitting while idle starts
    the run, like LiveSplit's single start/split key. A manual pause stops
    both clocks; :meth:`set_game_paused` (loads, pause screens…) stops only
    game time.
    """

    def __init__(
        self, split_names: list[str], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.split_names = list(split_names) or [DEFAULT_SPLIT_NAME]
        self._clock = clock
        self.state = IDLE
        self.split_times: list[int | None] = []
        self.game_times: list[int | None] = []
        self.deaths = 0
        self.started_at = ""
        self.game_paused = False
        self._real_acc = 0.0
        self._game_acc = 0.0
        self._real_since: float | None = None
        self._game_since: float | None = None

    # Clocks ---------------------------------------------------------------
    def _sync(self) -> None:
        """Fold running time into the totals and restart each clock as appropriate."""
        now = self._clock()
        if self._real_since is not None:
            self._real_acc += now - self._real_since
        if self._game_since is not None:
            self._game_acc += now - self._game_since
        # Finished keeps counting underneath so an undo continues seamlessly.
        counting = self.state in (RUNNING, FINISHED)
        self._real_since = now if counting else None
        self._game_since = now if counting and not self.game_paused else None

    def _live_ms(self, method: str) -> int:
        now = self._clock()
        if method == GAME:
            since, total = self._game_since, self._game_acc
        else:
            since, total = self._real_since, self._real_acc
        if since is not None:
            total += now - since
        return int(total * 1000)

    @property
    def current_index(self) -> int:
        """Index of the split being run (== len(splits) once finished)."""
        return len(self.split_times)

    def elapsed_ms(self, method: str = REAL) -> int:
        if self.state == IDLE:
            return 0
        if self.state == FINISHED:
            times = self.game_times if method == GAME else self.split_times
            return next((t for t in reversed(times) if t is not None), 0)
        return self._live_ms(method)

    # Actions ----------------------------------------------------------------
    def start(self) -> None:
        if self.state != IDLE:
            return
        self.split_times, self.game_times = [], []
        self.deaths = 0
        self._real_acc = self._game_acc = 0.0
        self._real_since = self._game_since = None
        self.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.state = RUNNING
        self._sync()

    def split(self) -> None:
        """Start the run, or record the current split (finishing on the last one)."""
        if self.state == IDLE:
            self.start()
            return
        if self.state != RUNNING:
            return
        self.split_times.append(self._live_ms(REAL))
        self.game_times.append(self._live_ms(GAME))
        if len(self.split_times) == len(self.split_names):
            self.state = FINISHED

    def skip_split(self) -> None:
        """Move past the current split without a time (not allowed on the last one)."""
        if self.state == RUNNING and self.current_index < len(self.split_names) - 1:
            self.split_times.append(None)
            self.game_times.append(None)

    def undo_split(self) -> None:
        """Take back the latest split (also un-finishes a finished run)."""
        if self.state == IDLE or not self.split_times:
            return
        self.split_times.pop()
        self.game_times.pop()
        if self.state == FINISHED:
            self.state = RUNNING  # the clocks kept going underneath

    def toggle_pause(self) -> None:
        if self.state == RUNNING:
            self.state = PAUSED
        elif self.state == PAUSED:
            self.state = RUNNING
        else:
            return
        self._sync()

    def set_game_paused(self, paused: bool) -> None:
        """Stop or restart game time only (loading, pause screen, game frozen…)."""
        if paused != self.game_paused:
            self.game_paused = paused
            self._sync()

    def add_deaths(self, delta: int) -> None:
        if self.state in (RUNNING, PAUSED):
            self.deaths = max(0, self.deaths + delta)

    def reset(self) -> RunRecord | None:
        """Stop and return the attempt to store (None if it never started)."""
        if self.state == IDLE:
            return None
        record = RunRecord(
            split_names=list(self.split_names),
            split_times=list(self.split_times),
            finished=self.state == FINISHED,
            deaths=self.deaths,
            started_at=self.started_at,
            ended_at=datetime.now(UTC).isoformat(timespec="seconds"),
            game_times=list(self.game_times),
        )
        self.state = IDLE
        self.split_times, self.game_times = [], []
        self.deaths = 0
        self.game_paused = False
        self._real_since = self._game_since = None
        return record

    # Crash recovery ---------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Everything needed to rebuild this run after a crash (JSON-friendly)."""
        return {
            "split_names": self.split_names,
            "split_times": self.split_times,
            "game_times": self.game_times,
            "deaths": self.deaths,
            "started_at": self.started_at,
            "real_ms": self.elapsed_ms(REAL),
            "game_ms": self.elapsed_ms(GAME),
            "finished": self.state == FINISHED,
        }

    @classmethod
    def restore(
        cls, data: dict[str, Any], clock: Callable[[], float] = time.monotonic
    ) -> SpeedrunTimer:
        """Rebuild a run from :meth:`snapshot`, paused at the saved time."""
        timer = cls(list(data["split_names"]), clock)
        timer.split_times = list(data.get("split_times", []))
        timer.game_times = list(data.get("game_times", []))
        timer.game_times += [None] * (len(timer.split_times) - len(timer.game_times))
        timer.deaths = int(data.get("deaths", 0))
        timer.started_at = str(data.get("started_at", ""))
        timer._real_acc = int(data.get("real_ms", 0)) / 1000
        timer._game_acc = int(data.get("game_ms", 0)) / 1000
        finished = data.get("finished") and len(timer.split_times) == len(timer.split_names)
        timer.state = FINISHED if finished else PAUSED
        timer._sync()
        return timer


# ----------------------------------------------------------------
# What the timer window shows
# ----------------------------------------------------------------
AHEAD = "ahead"
BEHIND = "behind"
GOLD = "gold"
NEUTRAL = "neutral"


@dataclass(slots=True)
class SplitRow:
    name: str
    time: str  # this run's time, or the comparison's for splits not reached yet
    delta: str = ""
    delta_status: str = NEUTRAL
    current: bool = False


@dataclass(slots=True)
class TimerView:
    game_name: str
    attempts: int
    state: str
    time: str
    time_status: str
    rows: list[SplitRow] = field(default_factory=list)
    deaths: int = 0
    pb: str = "-"
    sum_of_best: str = "-"
    pb_deaths: int | None = None
    other_time: str = ""  # e.g. "Real 12:03.45" while showing game time
    paused_reason: str = ""  # e.g. "Paused", "Loading", "Game closed"
    previous_segment: str = ""
    previous_segment_status: str = NEUTRAL
    comparison: str = COMPARISON_LABELS[COMPARE_PB]


class SpeedrunController:
    """
    Ties a :class:`SpeedrunTimer` to one game's splits and stored attempts.

    ``store`` persists finished and reset attempts; ``runs`` are the earlier
    attempts with the same split names (what PB, golds and the previous-run
    comparison use).
    """

    def __init__(
        self,
        game_id: int | None,
        game_name: str,
        split_names: list[str],
        runs: list[RunRecord],
        attempts: int,
        store: Callable[[int, RunRecord], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.game_id = game_id
        self.game_name = game_name
        self.timer = SpeedrunTimer(split_names, clock)
        self._runs = list(runs)
        self._attempts = attempts
        self._store = store
        self.method = REAL
        self.comparison = COMPARE_PB
        self.digits = 2
        self.game_pause_reason = ""
        self.last_reset_was_pb = False
        self._refresh_comparisons()

    def set_options(self, method: str, comparison: str, digits: int) -> None:
        self.method = GAME if method == GAME else REAL
        self.comparison = comparison if comparison in COMPARISON_LABELS else COMPARE_PB
        self.digits = min(max(digits, 0), 3)
        self._refresh_comparisons()

    def set_runs(self, runs: list[RunRecord]) -> None:
        """Replace the earlier attempts that comparisons use."""
        self._runs = list(runs)
        self._refresh_comparisons()

    def restore_timer(self, timer: SpeedrunTimer) -> None:
        """Continue a run recovered after a crash (it comes back paused)."""
        self.timer = timer
        self._refresh_comparisons()

    def _refresh_comparisons(self) -> None:
        count = len(self.timer.split_names)
        self._pb = personal_best(self._runs, self.method)
        self._best = best_segments(self._runs, count, self.method)
        if self.comparison == COMPARE_PREVIOUS and self._runs:
            times = self._runs[-1].times(self.method)
        elif self.comparison == COMPARE_BEST:
            times = cumulative(self._best)
        else:
            times = self._pb.times(self.method) if self._pb else []
        self._compare = (list(times) + [None] * count)[:count]

    @property
    def running(self) -> bool:
        return self.timer.state in (RUNNING, PAUSED)

    @property
    def runs(self) -> list[RunRecord]:
        return list(self._runs)

    @property
    def attempts(self) -> int:
        return self._attempts

    # Actions -----------------------------------------------------------
    def split(self) -> None:
        if self.game_id is None:
            return
        if self.timer.state == IDLE:
            self._attempts += 1
        self.timer.split()

    def is_new_pb(self) -> bool:
        """A finished run faster than every earlier one (by the timing method)."""
        if self.timer.state != FINISHED:
            return False
        total = self.timer.elapsed_ms(self.method)
        best = self._pb.total(self.method) if self._pb else None
        return best is None or total < best

    def reset(self) -> RunRecord | None:
        """End the attempt (saving it) and get ready for the next one."""
        self.last_reset_was_pb = self.is_new_pb()
        record = self.timer.reset()
        self.game_pause_reason = ""
        if record is not None and self.game_id is not None:
            self._store(self.game_id, record)
            self._runs.append(record)
            self._refresh_comparisons()
        return record

    def add_deaths(self, game_id: int | None, delta: int) -> None:
        if game_id == self.game_id:
            self.timer.add_deaths(delta)

    def set_game_paused(self, reason: str) -> None:
        """Pause game time for ``reason`` (e.g. "Loading"); "" resumes it."""
        self.game_pause_reason = reason if self.running else ""
        self.timer.set_game_paused(bool(self.game_pause_reason))

    def records(self) -> Records:
        return compute_records(self._runs, self.timer.split_names, self._attempts, self.method)

    # View --------------------------------------------------------------
    def view(self, max_rows: int = 8) -> TimerView:
        timer, method, digits = self.timer, self.method, self.digits
        names = timer.split_names
        compare = self._compare
        current = timer.current_index
        elapsed = timer.elapsed_ms(method)
        mine_times = timer.game_times if method == GAME else timer.split_times
        run_segments = segment_times(mine_times)
        compare_segments = segment_times(compare)

        rows: list[SplitRow] = []
        for index, name in enumerate(names):
            target = compare[index]
            row = SplitRow(name=name, time=format_time(target, digits))
            if index < len(mine_times):
                mine = mine_times[index]
                row.time = format_time(mine, digits)
                if mine is not None and target is not None:
                    row.delta = format_delta(mine - target)
                    row.delta_status = AHEAD if mine < target else BEHIND
                segment, best = run_segments[index], self._best[index]
                if segment is not None and (best is None or segment < best):
                    row.delta_status = GOLD
                    row.delta = row.delta or format_time(segment, digits)
            elif index == current and timer.state in (RUNNING, PAUSED):
                row.current = True
                if target is not None and elapsed > target:
                    row.delta = format_delta(elapsed - target)  # live: losing time
                    row.delta_status = BEHIND
            rows.append(row)

        # Keep the current split in view: a little history, mostly what's next.
        start = max(0, min(current - 2, len(rows) - max_rows))
        rows = rows[start : start + max_rows]

        time_status = NEUTRAL
        if timer.state == FINISHED:
            time_status = GOLD if self.is_new_pb() else BEHIND
        elif timer.state == RUNNING and current < len(compare):
            target = compare[current]
            if target is not None:
                time_status = AHEAD if elapsed <= target else BEHIND

        # How the last completed segment went against the comparison's.
        previous_segment, previous_status = "", NEUTRAL
        last = len(mine_times) - 1
        if last >= 0 and run_segments[last] is not None:
            segment = run_segments[last]
            target_segment = compare_segments[last] if last < len(compare_segments) else None
            if target_segment is not None:
                previous_segment = format_delta(segment - target_segment)
                previous_status = AHEAD if segment < target_segment else BEHIND
            else:
                previous_segment = format_time(segment, digits)
            best = self._best[last]
            if best is None or segment < best:
                previous_status = GOLD

        other = GAME if method == REAL else REAL
        other_ms = timer.elapsed_ms(other)
        other_time = ""
        if abs(other_ms - elapsed) >= 100:  # only when loads etc. made them differ
            other_time = f"{'Game' if other == GAME else 'Real'} {format_time(other_ms, digits)}"

        paused_reason = ""
        if timer.state == PAUSED:
            paused_reason = "Paused"
        elif timer.state == RUNNING and self.game_pause_reason and method == GAME:
            paused_reason = self.game_pause_reason

        pb_total = self._pb.total(method) if self._pb else None
        return TimerView(
            game_name=self.game_name,
            attempts=self._attempts,
            state=timer.state,
            time=format_time(elapsed, digits),
            time_status=time_status,
            rows=rows,
            deaths=timer.deaths,
            pb=format_time(pb_total, digits),
            sum_of_best=format_time(sum_of_best(self._best), digits),
            pb_deaths=self._pb.deaths if self._pb else None,
            other_time=other_time,
            paused_reason=paused_reason,
            previous_segment=previous_segment,
            previous_segment_status=previous_status,
            comparison=COMPARISON_LABELS[self.comparison],
        )
