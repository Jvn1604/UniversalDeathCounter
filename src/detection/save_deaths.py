"""
The game's own death count, read from its save file.

Many games keep a death total in the save (Elden Ring, Sekiro, Dark Souls
II and III, and plenty of others), counting every death of that character,
including deaths from before this app was installed and from earlier NG+
cycles. Few show it, and save formats aren't documented, so the count is
*learned*: while the player dies as usual, :class:`SaveLearner` watches the
save and keeps the one number that goes up by exactly one per death (and
doesn't change otherwise). From then on :class:`SaveLocation` reads it.

Only the file is read: nothing touches the game, so it's safe alongside
anti-cheat. Works with any save that isn't encrypted or compressed, plain
binary or text (JSON, INI, …). FromSoftware's BND4 saves are split into
their character slots, and Dark Souls II/III's are decrypted first (their
keys are public; Windows' own AES, no extra dependency).
"""

from __future__ import annotations

import json
import os
import re
import struct
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from src.utils.logger import get_logger
from src.utils.platform_info import IS_WINDOWS

logger = get_logger(__name__)

_MAX_DEATHS = 10_000_000  # larger values aren't death counts
_CONTEXT = 12  # bytes kept on each side of a learned binary field
_TEXT_CONTEXT = 32  # characters kept before a learned number in a text save
_MAX_TEXT_BYTES = 8 * 1024 * 1024
DEATHS_TO_LEARN = 2  # deaths seen before a single remaining candidate is trusted

# FromSoftware saves: (game, folder in %APPDATA%, file name, AES key or None).
KNOWN_SAVES: tuple[tuple[str, str, str, bytes | None], ...] = (
    ("Elden Ring", "EldenRing", "ER0000.sl2", None),
    ("Elden Ring (Seamless Co-op)", "EldenRing", "ER0000.co2", None),
    ("Sekiro", "Sekiro", "S0000.sl2", None),
    ("Dark Souls III", "DarkSoulsIII", "DS30000.sl2",
     bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")),
    ("Dark Souls II: SotFS", "DarkSoulsII", "DS2SOFS0000.sl2",
     bytes.fromhex("599F9B699640A55236EE2D70835EC744")),
)


class SaveReadError(OSError):
    """The save can't be read (missing, locked, encrypted, …)."""


def find_known_saves(appdata: str | None = None) -> list[tuple[str, Path]]:
    """``(game, path)`` for every known save on this PC, newest first."""
    base = Path(appdata or os.environ.get("APPDATA", ""))
    found: list[tuple[str, Path]] = []
    if not base.name:
        return found
    for game, folder, name, _key in KNOWN_SAVES:
        root = base / folder
        if root.is_dir():
            found += [(game, path) for path in root.glob(f"*/{name}")]
    return sorted(found, key=lambda item: item[1].stat().st_mtime, reverse=True)


def _key_for(path: Path) -> bytes | None:
    for _game, _folder, name, key in KNOWN_SAVES:
        if path.name.lower() == name.lower():
            return key
    return None


# ---------------------------------------------------------------- reading
def read_save(path: str | Path) -> list[bytes] | str:
    """
    The save's contents: its parts (character slots) as bytes, or the text
    of a text save.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SaveReadError(f"Can't read {path.name}: {exc.strerror or exc}") from exc
    if data[:4] == b"BND4":
        return _bnd4_entries(data, _key_for(path))
    unpacked = _unpack_whole(data)
    if unpacked is not None:
        data = unpacked  # a save compressed as a whole (gzip, xz, bzip2, zlib)
    if len(data) <= _MAX_TEXT_BYTES and b"\0" not in data[:4096]:
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    # A save made of compressed chunks: each unpacked chunk is a part to read.
    return [data, *_zlib_chunks(data)]


# ---------------------------------------------------------------- compressed saves
_MAX_UNPACKED = 256 * 1024 * 1024  # never unpack more than this from one save


def _unpack_whole(data: bytes) -> bytes | None:
    """The save unpacked, if it's one gzip, xz, bzip2 or zlib stream; else None."""
    import bz2
    import gzip
    import lzma

    try:
        if data[:2] == b"\x1f\x8b":
            return gzip.decompress(data)
        if data[:6] == b"\xfd7zXZ\x00":
            return lzma.decompress(data)
        if data[:3] == b"BZh":
            return bz2.decompress(data)
        if _zlib_header(data, 0):
            unpacker = zlib.decompressobj()
            out = unpacker.decompress(data, _MAX_UNPACKED)
            if unpacker.eof and not unpacker.unused_data.strip(b"\0"):
                return out
    except (OSError, EOFError, ValueError, lzma.LZMAError, zlib.error):
        pass
    return None


def _zlib_header(data: bytes, at: int) -> bool:
    if at + 2 > len(data):
        return False
    first, second = data[at], data[at + 1]
    return first == 0x78 and second in (0x01, 0x5E, 0x9C, 0xDA) and (first * 256 + second) % 31 == 0


def _zlib_chunks(data: bytes) -> list[bytes]:
    """
    zlib streams inside the save (many engines compress a save in chunks),
    unpacked. Only for saves that don't compress any further themselves: a
    plain save is read as it is.
    """
    sample = data[:262_144]
    if len(sample) < 4096 or len(zlib.compress(sample, 1)) < 0.9 * len(sample):
        return []
    chunks, total, at = [], 0, 0
    while total < _MAX_UNPACKED:
        at = data.find(b"\x78", at)
        if at < 0:
            break
        if _zlib_header(data, at):
            unpacker = zlib.decompressobj()
            try:
                out = unpacker.decompress(data[at:], _MAX_UNPACKED - total)
            except zlib.error:
                out = b""
            if unpacker.eof and len(out) >= 256:
                chunks.append(out)
                total += len(out)
                at = len(data) - len(unpacker.unused_data)
                continue
        at += 1
    return chunks


def _bnd4_entries(data: bytes, key: bytes | None) -> list[bytes]:
    """The files inside a BND4 container (decrypted with ``key`` if given)."""
    try:
        count = struct.unpack_from("<i", data, 12)[0]
        entries = []
        for i in range(count):
            header = 0x40 + i * 0x20
            size = struct.unpack_from("<q", data, header + 8)[0]
            offset = struct.unpack_from("<i", data, header + 16)[0]
            entry = data[offset: offset + size]
            if key is not None:
                # MD5 (16 bytes), IV (16 bytes), then AES-128-CBC.
                entry = _aes_cbc_decrypt(key, entry[16:32], entry[32:])
            entries.append(entry)
    except struct.error as exc:
        raise SaveReadError("The save file is damaged or not a save") from exc
    return entries


def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not IS_WINDOWS:
        raise SaveReadError("This game's save is encrypted; reading it needs Windows")
    import ctypes
    from ctypes import wintypes

    bcrypt = ctypes.windll.bcrypt
    algorithm, handle = ctypes.c_void_p(), ctypes.c_void_p()
    length = len(data) // 16 * 16
    out = ctypes.create_string_buffer(length)
    written = wintypes.ULONG()
    mode = ctypes.create_unicode_buffer("ChainingModeCBC")
    try:
        if (bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "AES", None, 0)
                or bcrypt.BCryptSetProperty(algorithm, "ChainingMode", mode,
                                            ctypes.sizeof(mode), 0)
                or bcrypt.BCryptGenerateSymmetricKey(algorithm, ctypes.byref(handle), None, 0,
                                                     key, len(key), 0)
                or bcrypt.BCryptDecrypt(handle, data[:length], length, None,
                                        ctypes.create_string_buffer(iv, 16), 16, out, length,
                                        ctypes.byref(written), 0)):
            raise SaveReadError("Couldn't decrypt the save")
    finally:
        if handle:
            bcrypt.BCryptDestroyKey(handle)
        if algorithm:
            bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)
    return out.raw


def _u32(entry: bytes, phase: int) -> np.ndarray:
    """The little-endian 32-bit values starting at offsets ``phase``, ``phase + 4``, …"""
    usable = (len(entry) - phase) // 4 * 4
    return np.frombuffer(entry, dtype="<u4", count=usable // 4, offset=phase).astype(np.int64)


_NUMBER = re.compile(r"(?<![\w.])\d{1,8}(?![\w.])")


def _text_numbers(text: str) -> dict[tuple[str, int], int]:
    """Numbers in a text save, keyed by the text before them (and which one with that text)."""
    found: dict[tuple[str, int], int] = {}
    seen: dict[str, int] = {}
    for match in _NUMBER.finditer(text):
        before = re.sub(r"\d", "#", text[max(0, match.start() - _TEXT_CONTEXT): match.start()])
        nth = seen.get(before, 0)
        seen[before] = nth + 1
        found[(before, nth)] = int(match.group())
    return found


# ---------------------------------------------------------------- learned location
@dataclass
class SaveLocation:
    """Where the death count is in a save: a binary field or a number in a text save."""

    entry: int = 0  # binary: which part (character slot)
    offset: int = 0
    before: str = ""  # hex bytes before the field / text before the number
    after: str = ""  # hex bytes after the field
    nth: int = 0  # text: which number with that text before it

    @property
    def is_text(self) -> bool:
        return self.offset < 0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> SaveLocation | None:
        try:
            return cls(**json.loads(text))
        except (ValueError, TypeError):
            return None

    def read(self, contents: list[bytes] | str) -> int | None:
        """The count, or None if it can't be found any more (the save changed shape)."""
        if isinstance(contents, str):
            if not self.is_text:
                return None
            return _text_numbers(contents).get((self.before, self.nth))
        if self.is_text or self.entry >= len(contents):
            return None
        data = contents[self.entry]
        offset = self._find(data)
        if offset is None:
            return None
        # Remember the surroundings as they are now: they may change slowly.
        self.offset = offset
        self.before = data[max(0, offset - _CONTEXT): offset].hex()
        self.after = data[offset + 4: offset + 4 + _CONTEXT].hex()
        return struct.unpack_from("<I", data, offset)[0]

    def _find(self, data: bytes) -> int | None:
        before, after = bytes.fromhex(self.before), bytes.fromhex(self.after)
        offset = self.offset
        if (0 <= offset <= len(data) - 4 and data[offset - len(before): offset] == before
                and data[offset + 4: offset + 4 + len(after)] == after):
            return offset
        # Moved (the save grew or shrank before it): the nearest spot with the
        # same surroundings.
        spots = []
        if len(before) == _CONTEXT:
            spots += [m.start() + _CONTEXT for m in re.finditer(re.escape(before), data)]
        if len(after) == _CONTEXT and not spots:
            spots += [m.start() - 4 for m in re.finditer(re.escape(after), data)]
        spots = [s for s in spots if 0 <= s <= len(data) - 4]
        return min(spots, key=lambda s: abs(s - offset)) if spots else None


# ---------------------------------------------------------------- learning
class SaveLearner:
    """
    Finds the death count in a save by watching it while the player dies.

    Call :meth:`observe` with the save's contents whenever it has been
    written (and the game had a moment to save the latest death), together
    with how many deaths the app has counted for the game so far. A field
    stays a candidate only while it rises by exactly as many deaths as were
    counted, and doesn't change otherwise.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._reference: list[bytes] | str | None = None
        self._reference_deaths = 0
        self._candidates: dict[int, tuple[np.ndarray, np.ndarray]] | None = None
        self._text_candidates: dict[tuple[str, int], int] | None = None
        self.deaths_seen = 0
        self.location: SaveLocation | None = None

    @property
    def candidate_count(self) -> int:
        if self._text_candidates is not None:
            return len(self._text_candidates)
        if self._candidates is not None:
            return sum(len(offsets) for offsets, _values in self._candidates.values())
        return 0

    def observe(self, contents: list[bytes] | str, deaths: int) -> SaveLocation | None:
        """Learn from the save as it is now; returns the location once it's found."""
        if self.location is not None:
            return self.location
        started = self._candidates is not None or self._text_candidates is not None
        if started and isinstance(contents, str) != (self._text_candidates is not None):
            self.reset()  # the file changed kind (another file was picked)
            started = False
        if not started and (
            self._reference is None or type(contents) is not type(self._reference)
        ):
            self._reference, self._reference_deaths = contents, deaths
            return None
        expected = deaths - self._reference_deaths
        if isinstance(contents, str):
            self._observe_text(contents, expected)
        else:
            self._observe_binary(contents, expected)
        if expected > 0:
            self.deaths_seen += expected
        self._reference_deaths = deaths
        self._decide()
        return self.location

    def _observe_binary(self, entries: list[bytes], expected: int) -> None:
        if self._candidates is None:
            reference = self._reference
            if expected <= 0:  # nothing to learn from yet: compare with this one next time
                self._reference = entries
                return
            candidates = {}
            for index, entry in enumerate(entries):
                if index >= len(reference) or len(reference[index]) != len(entry):
                    continue
                if reference[index] == entry:
                    continue
                for phase in range(4):
                    new, old = _u32(entry, phase), _u32(reference[index], phase)
                    hits = np.nonzero((new - old == expected) & (old >= 0)
                                      & (new < _MAX_DEATHS))[0]
                    if len(hits):
                        offsets = hits * 4 + phase
                        previous = candidates.get(index)
                        values = new[hits]
                        if previous is not None:
                            offsets = np.concatenate([previous[0], offsets])
                            values = np.concatenate([previous[1], values])
                        candidates[index] = (offsets, values)
            self._candidates = candidates
            self._reference = None  # only the candidates are needed from now on: frees memory
            return
        kept = {}
        for index, (offsets, values) in self._candidates.items():
            if index >= len(entries):
                continue
            entry = np.frombuffer(entries[index], dtype=np.uint8)
            valid = offsets <= len(entry) - 4
            offsets, values = offsets[valid], values[valid]
            now = (entry[offsets].astype(np.int64) | entry[offsets + 1].astype(np.int64) << 8
                   | entry[offsets + 2].astype(np.int64) << 16
                   | entry[offsets + 3].astype(np.int64) << 24)
            match = now - values == expected
            if match.any():
                kept[index] = (offsets[match], now[match])
        self._candidates = kept

    def _observe_text(self, text: str, expected: int) -> None:
        now = _text_numbers(text)
        if self._text_candidates is None:
            if expected <= 0:
                self._reference = text
                return
            before = _text_numbers(self._reference)
            self._text_candidates = {
                key: value for key, value in now.items()
                if key in before and value - before[key] == expected
            }
            self._reference = None
            return
        self._text_candidates = {
            key: now[key] for key, value in self._text_candidates.items()
            if key in now and now[key] - value == expected
        }

    def _decide(self) -> None:
        if self._text_candidates is not None:
            if not self._text_candidates:
                self._restart()
            elif len(self._text_candidates) == 1 and self.deaths_seen >= DEATHS_TO_LEARN:
                (before, nth), = self._text_candidates
                self.location = SaveLocation(offset=-1, before=before, nth=nth)
            return
        if self._candidates is None:
            return
        count = self.candidate_count
        if count == 0:
            self._restart()
        elif self.deaths_seen >= DEATHS_TO_LEARN and (
            count == 1 or self.deaths_seen >= DEATHS_TO_LEARN + 2
        ):
            # Still more than one after a few more deaths: the highest count
            # (an all-time total rather than a per-area one), first in the file.
            best = None
            for index, (offsets, values) in self._candidates.items():
                for offset, value in zip(offsets.tolist(), values.tolist(), strict=True):
                    key = (-value, index, offset)
                    if best is None or key < best[0]:
                        best = (key, index, offset)
            if best is not None:
                self.location = SaveLocation(entry=best[1], offset=best[2])

    def _restart(self) -> None:
        """Nothing fits (a death the app didn't count?): start again from the next save."""
        logger.info("Save learning found no match; starting again")
        self.reset()

    def finish(self, contents: list[bytes] | str) -> int | None:
        """Fill in the location's surroundings and read the count."""
        if self.location is None:
            return None
        if isinstance(contents, list):
            data = contents[self.location.entry]
            offset = self.location.offset
            self.location.before = data[max(0, offset - _CONTEXT): offset].hex()
            self.location.after = data[offset + 4: offset + 4 + _CONTEXT].hex()
        return self.location.read(contents)
