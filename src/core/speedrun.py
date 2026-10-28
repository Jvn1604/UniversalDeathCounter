"""
Speedrun timer: splits, personal best, best segments, and deaths per run.

Everything here is plain Python (no Qt) and takes an injectable clock, so the
timing logic is unit tested without waiting. The UI polls
:meth:`SpeedrunController.view` while a run is going and renders the result.

Terms, as in LiveSplit:

* **split** — one checkpoint of a run (e.g. a boss); its time is cumulative.
* **segment** — the time between two consecutive splits.
* **PB** — personal best: the fastest finished run with the same splits.
* **gold** — a segment faster than that segment has ever been.
* **sum of best** — all best segments added up: the theoretical best run.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

IDLE = "idle"
RUNNING = "running"
PAUSED = "paused"
FINISHED = "finished"

# A run with no splits set up still has one: reaching the end.
DEFAULT_SPLIT_NAME = "Finish"


# ----------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------
def format_time(ms: int | None) -> str:
    """``1:02:03.45``, ``2:03.45`` or ``0:03.45``; ``-`` for no time."""
    if ms is None:
        return "-"
    ms = max(ms, 0)
    hundredths = (ms // 10) % 100
    seconds = (ms // 1000) % 60
    minutes = (ms // 60_000) % 60
    hours = ms // 3_600_000
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"
    return f"{minutes}:{seconds:02d}.{hundredths:02d}"


def format_delta(ms: int) -> str:
    """Signed difference to the PB: ``-1.2``, ``+12.3``, ``+1:05.0``."""
    sign = "-" if ms < 0 else "+"
    ms = abs(ms)
    tenths = (ms // 100) % 10
    seconds = ms // 1000
    if seconds < 60:
        return f"{sign}{seconds}.{tenths}"
    return f"{sign}{seconds // 60}:{seconds % 60:02d}.{tenths}"


# ----------------------------------------------------------------
# Runs and comparisons
# ----------------------------------------------------------------
@dataclass(slots=True)
class RunRecord:
    """One attempt: cumulative split times (None = skipped / not reached)."""

    split_names: list[str]
    split_times: list[int | None]
    finished: bool
    deaths: int = 0
    started_at: str = ""
    ended_at: str = ""

    @property
    def total_ms(self) -> int | None:
        return self.split_times[-1] if self.finished and self.split_times else None


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


def personal_best(runs: list[RunRecord]) -> RunRecord | None:
    """The fastest finished run, if any."""
    finished = [run for run in runs if run.finished and run.total_ms is not None]
    return min(finished, key=lambda run: run.total_ms or 0, default=None)


def best_segments(runs: list[RunRecord], count: int) -> list[int | None]:
    """The fastest time ever recorded for each of ``count`` segments."""
    best: list[int | None] = [None] * count
    for run in runs:
        for index, segment in enumerate(segment_times(run.split_times[:count])):
            if segment is not None and (best[index] is None or segment < best[index]):
                best[index] = segment
    return best


def sum_of_best(best: list[int | None]) -> int | None:
    """All best segments added up, or None until every segment has one."""
    if not best or any(segment is None for segment in best):
        return None
    return sum(segment for segment in best if segment is not None)


# ----------------------------------------------------------------
# The timer itself
# ----------------------------------------------------------------
class SpeedrunTimer:
    """
    Start / split / pause / undo / skip / reset, timed with a monotonic clock.

    States: idle → running ⇄ paused → finished. Splitting while idle starts
    the run, like LiveSplit's single start/split key.
    """

    def __init__(
        self, split_names: list[str], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.split_names = list(split_names) or [DEFAULT_SPLIT_NAME]
        self._clock = clock
        self.state = IDLE
        self.split_times: list[int | None] = []
        self.deaths = 0
        self.started_at = ""
        self._start = 0.0  # clock value when the run (minus pauses) began
        self._paused_at = 0.0

    @property
    def current_index(self) -> int:
        """Index of the split being run (== len(splits) once finished)."""
        return len(self.split_times)

    def elapsed_ms(self) -> int:
        if self.state == IDLE:
            return 0
        if self.state == FINISHED:
            return self._last_time()
        now = self._paused_at if self.state == PAUSED else self._clock()
        return int((now - self._start) * 1000)

    def _last_time(self) -> int:
        return next((t for t in reversed(self.split_times) if t is not None), 0)

    def start(self) -> None:
        if self.state != IDLE:
            return
        self.state = RUNNING
        self._start = self._clock()
        self.split_times = []
        self.deaths = 0
        self.started_at = datetime.now(UTC).isoformat(timespec="seconds")

    def split(self) -> None:
        """Start the run, or record the current split (finishing on the last one)."""
        if self.state == IDLE:
            self.start()
            return
        if self.state != RUNNING:
            return
        self.split_times.append(self.elapsed_ms())
        if len(self.split_times) == len(self.split_names):
            self.state = FINISHED

    def skip_split(self) -> None:
        """Move past the current split without a time (not allowed on the last one)."""
        if self.state == RUNNING and self.current_index < len(self.split_names) - 1:
            self.split_times.append(None)

    def undo_split(self) -> None:
        """Take back the latest split (also un-finishes a finished run)."""
        if self.state not in (RUNNING, PAUSED, FINISHED) or not self.split_times:
            return
        self.split_times.pop()
        if self.state == FINISHED:
            # Resume as if the final split never happened: the clock kept going.
            self.state = RUNNING

    def toggle_pause(self) -> None:
        if self.state == RUNNING:
            self.state = PAUSED
            self._paused_at = self._clock()
        elif self.state == PAUSED:
            self._start += self._clock() - self._paused_at
            self.state = RUNNING

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
        )
        self.state = IDLE
        self.split_times = []
        self.deaths = 0
        return record


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
    time: str  # this run's time, or the PB's time for splits not reached yet
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


class SpeedrunController:
    """
    Ties a :class:`SpeedrunTimer` to one game's splits and stored attempts.

    ``store`` persists finished and reset attempts; ``runs`` are the earlier
    attempts with the same split names (what PB and golds compare against).
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
        self._runs = runs
        self._attempts = attempts
        self._store = store
        self._refresh_comparisons()

    def _refresh_comparisons(self) -> None:
        count = len(self.timer.split_names)
        self._pb = personal_best(self._runs)
        self._best = best_segments(self._runs, count)

    def set_runs(self, runs: list[RunRecord]) -> None:
        """Replace the earlier attempts that PB and golds compare against."""
        self._runs = list(runs)
        self._refresh_comparisons()

    @property
    def running(self) -> bool:
        return self.timer.state in (RUNNING, PAUSED)

    # Actions -----------------------------------------------------------
    def split(self) -> None:
        if self.game_id is None:
            return
        if self.timer.state == IDLE:
            self._attempts += 1
        self.timer.split()

    def reset(self) -> RunRecord | None:
        """End the attempt (saving it) and get ready for the next one."""
        record = self.timer.reset()
        if record is not None and self.game_id is not None:
            self._store(self.game_id, record)
            self._runs.append(record)
            self._refresh_comparisons()
        return record

    def add_deaths(self, game_id: int | None, delta: int) -> None:
        if game_id == self.game_id:
            self.timer.add_deaths(delta)

    # View --------------------------------------------------------------
    def view(self, max_rows: int = 8) -> TimerView:
        timer = self.timer
        names = timer.split_names
        pb_times = self._pb.split_times if self._pb else [None] * len(names)
        current = timer.current_index
        elapsed = timer.elapsed_ms()

        rows: list[SplitRow] = []
        run_segments = segment_times(timer.split_times)
        for index, name in enumerate(names):
            pb_time = pb_times[index] if index < len(pb_times) else None
            row = SplitRow(name=name, time=format_time(pb_time))
            if index < len(timer.split_times):
                mine = timer.split_times[index]
                row.time = format_time(mine)
                if mine is not None and pb_time is not None:
                    row.delta = format_delta(mine - pb_time)
                    row.delta_status = AHEAD if mine < pb_time else BEHIND
                segment, best = run_segments[index], self._best[index]
                if segment is not None and (best is None or segment < best):
                    row.delta_status = GOLD
                    row.delta = row.delta or format_time(segment)
            elif index == current and timer.state in (RUNNING, PAUSED):
                row.current = True
                if pb_time is not None and elapsed > pb_time:
                    row.delta = format_delta(elapsed - pb_time)  # live: losing time
                    row.delta_status = BEHIND
            rows.append(row)

        # Keep the current split in view: a little history, mostly what's next.
        start = max(0, min(current - 2, len(rows) - max_rows))
        rows = rows[start : start + max_rows]

        time_status = NEUTRAL
        if timer.state == FINISHED:
            pb_total = self._pb.total_ms if self._pb else None
            time_status = GOLD if pb_total is None or elapsed < pb_total else BEHIND
        elif timer.state == RUNNING and current < len(pb_times):
            comparison = pb_times[current]
            if comparison is not None:
                time_status = AHEAD if elapsed <= comparison else BEHIND

        return TimerView(
            game_name=self.game_name,
            attempts=self._attempts,
            state=timer.state,
            time=format_time(elapsed),
            time_status=time_status,
            rows=rows,
            deaths=timer.deaths,
            pb=format_time(self._pb.total_ms) if self._pb else "-",
            sum_of_best=format_time(sum_of_best(self._best)),
            pb_deaths=self._pb.deaths if self._pb else None,
        )
