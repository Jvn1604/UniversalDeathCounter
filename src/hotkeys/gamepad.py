"""
Global controller bindings (Xbox, PlayStation, and generic gamepads).

No extra dependencies. On Windows both backends are Windows APIs called
via ctypes:

* **XInput** (``xinput1_4.dll``) for Xbox and other XInput controllers.
* **WinMM joystick API** (``winmm.dll``) for everything else, including
  DualShock 4 / DualSense, which Windows exposes as standard game
  controllers. Sony pads are recognized by USB vendor id so their buttons
  get the right names; Microsoft pads are skipped there (XInput has them).

On Linux the kernel's joystick devices (``/dev/input/js*``) are read
directly; the driver says which standard button each one is, so Xbox,
PlayStation, Steam Deck and other pads all get the shared names. macOS
has no controller backend yet.

Buttons are stored under shared names (``south``, ``back``, ``dpad_up``…),
so a binding such as ``back+dpad_up`` works on Xbox *and* PlayStation
pads and is shown as "View/Share + D-pad Up".

Controller presses are not consumed (the game sees them too), so bindings
are combos: an action fires once when every button of its combo is held.
Polling runs on a daemon thread (60 Hz while a pad is connected, 1 Hz
scan otherwise); signals reach Qt's main thread queued.
"""

from __future__ import annotations

import array
import glob
import os
import struct
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Shared button name -> (Xbox label, PlayStation label)
BUTTON_LABELS: dict[str, tuple[str, str]] = {
    "south": ("A", "Cross"),
    "east": ("B", "Circle"),
    "west": ("X", "Square"),
    "north": ("Y", "Triangle"),
    "lb": ("LB", "L1"),
    "rb": ("RB", "R1"),
    "lt": ("LT", "L2"),
    "rt": ("RT", "R2"),
    "back": ("View", "Share"),
    "start": ("Menu", "Options"),
    "ls": ("LS", "L3"),
    "rs": ("RS", "R3"),
    "guide": ("Xbox", "PS"),
    "touchpad": ("Touchpad", "Touchpad"),
    "dpad_up": ("D-pad Up", "D-pad Up"),
    "dpad_down": ("D-pad Down", "D-pad Down"),
    "dpad_left": ("D-pad Left", "D-pad Left"),
    "dpad_right": ("D-pad Right", "D-pad Right"),
}

# Display order inside a combo: modifiers first, d-pad last.
_ORDER = {name: index for index, name in enumerate(
    ["back", "start", "guide", "lb", "rb", "lt", "rt", "ls", "rs", "touchpad",
     "north", "west", "east", "south", "dpad_up", "dpad_down", "dpad_left", "dpad_right"]
)}

_XINPUT_BITS: dict[int, str] = {
    0x0001: "dpad_up", 0x0002: "dpad_down", 0x0004: "dpad_left", 0x0008: "dpad_right",
    0x0010: "start", 0x0020: "back", 0x0040: "ls", 0x0080: "rs",
    0x0100: "lb", 0x0200: "rb", 0x1000: "south", 0x2000: "east",
    0x4000: "west", 0x8000: "north",
}
_TRIGGER_THRESHOLD = 128

# DualShock 4 / DualSense button numbers (1-based) in the Windows joystick API.
_SONY_BUTTONS: dict[int, str] = {
    1: "west", 2: "south", 3: "east", 4: "north", 5: "lb", 6: "rb", 7: "lt", 8: "rt",
    9: "back", 10: "start", 11: "ls", 12: "rs", 13: "guide", 14: "touchpad",
}
_SONY_VENDOR_ID = 0x054C
_MICROSOFT_VENDOR_ID = 0x045E


def parse_combo(text: str) -> frozenset[str]:
    """``"back+dpad_up"`` -> ``{"back", "dpad_up"}``; empty/unknown -> empty set."""
    names = {part.strip().lower() for part in text.split("+") if part.strip()}
    if not names or any(not _is_button_name(name) for name in names):
        return frozenset()
    return frozenset(names)


def _is_button_name(name: str) -> bool:
    return name in BUTTON_LABELS or (name.startswith("button") and name[6:].isdigit())


def combo_text(buttons: frozenset[str] | set[str]) -> str:
    """Storage form of a combo, in a stable order (``"back+dpad_up"``)."""
    return "+".join(sorted(buttons, key=lambda b: (_ORDER.get(b, 99), b)))


def combo_label(text: str) -> str:
    """Human label for a stored combo: ``"back+dpad_up"`` -> "View/Share + D-pad Up"."""
    if not parse_combo(text):
        return ""
    labels = []
    for name in (part.strip().lower() for part in text.split("+") if part.strip()):
        if name in BUTTON_LABELS:
            xbox, playstation = BUTTON_LABELS[name]
            labels.append(xbox if xbox == playstation else f"{xbox}/{playstation}")
        else:
            labels.append(f"Button {name[6:]}")
    return " + ".join(labels)


def dpad_from_pov(pov: int) -> set[str]:
    """Convert a WinMM POV hat angle (hundredths of a degree) to d-pad buttons."""
    if pov > 36000:  # 0xFFFF = centered
        return set()
    angle = pov / 100
    pressed: set[str] = set()
    if angle >= 292.5 or angle <= 67.5:
        pressed.add("dpad_up")
    if 22.5 <= angle <= 157.5:
        pressed.add("dpad_right")
    if 112.5 <= angle <= 247.5:
        pressed.add("dpad_down")
    if 202.5 <= angle <= 337.5:
        pressed.add("dpad_left")
    return pressed


def winmm_buttons(button_mask: int, pov: int, vendor_id: int) -> set[str]:
    """Shared button names held on a WinMM joystick (Sony layout or generic)."""
    pressed = dpad_from_pov(pov)
    for number in range(1, 33):
        if button_mask & (1 << (number - 1)):
            if vendor_id == _SONY_VENDOR_ID and number in _SONY_BUTTONS:
                pressed.add(_SONY_BUTTONS[number])
            else:
                pressed.add(f"button{number}")
    return pressed


def xinput_buttons(button_mask: int, left_trigger: int, right_trigger: int) -> set[str]:
    """Shared button names held on an XInput controller."""
    pressed = {name for bit, name in _XINPUT_BITS.items() if button_mask & bit}
    if left_trigger > _TRIGGER_THRESHOLD:
        pressed.add("lt")
    if right_trigger > _TRIGGER_THRESHOLD:
        pressed.add("rt")
    return pressed


class ComboTracker:
    """
    Fires an action once when its whole combo becomes held.

    Pure logic (no I/O), fed with the set of held buttons each poll.
    """

    def __init__(self, bindings: dict[str, str]) -> None:
        self.set_bindings(bindings)
        self._held: frozenset[str] = frozenset()

    def set_bindings(self, bindings: dict[str, str]) -> None:
        combos = {action: parse_combo(text) for action, text in bindings.items()}
        # Larger combos first, so "back+lb+dpad_up" wins over "back+dpad_up".
        self._combos = sorted(
            ((a, c) for a, c in combos.items() if c), key=lambda item: -len(item[1])
        )

    def update(self, held: set[str] | frozenset[str]) -> list[str]:
        """Return the actions whose combo was just completed."""
        held = frozenset(held)
        fired: list[str] = []
        claimed: set[str] = set()
        for action, combo in self._combos:
            if combo <= held and not combo <= self._held and not combo & claimed:
                fired.append(action)
                claimed |= combo
        self._held = held
        return fired


class ComboRecorder:
    """Captures the largest set of buttons held until everything is released."""

    def __init__(self) -> None:
        self._peak: frozenset[str] = frozenset()

    def update(self, held: set[str] | frozenset[str]) -> frozenset[str] | None:
        """Feed held buttons; returns the recorded combo once all are released."""
        if held:
            if len(held) >= len(self._peak):
                self._peak = frozenset(held)
            return None
        recorded, self._peak = self._peak, frozenset()
        return recorded or None


# ----------------------------------------------------------------
# Windows backends
# ----------------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _XInputGamepad(ctypes.Structure):
        _fields_ = [
            ("wButtons", wintypes.WORD),
            ("bLeftTrigger", ctypes.c_ubyte),
            ("bRightTrigger", ctypes.c_ubyte),
            ("sThumbLX", ctypes.c_short),
            ("sThumbLY", ctypes.c_short),
            ("sThumbRX", ctypes.c_short),
            ("sThumbRY", ctypes.c_short),
        ]

    class _XInputState(ctypes.Structure):
        _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", _XInputGamepad)]

    class _JoyInfoEx(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in (
            "dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos",
            "dwVpos", "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1", "dwReserved2",
        )]

    class _JoyCapsW(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
            ("szPname", wintypes.WCHAR * 32),
            *[(name, wintypes.UINT) for name in (
                "wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax", "wNumButtons",
                "wPeriodMin", "wPeriodMax", "wRmin", "wRmax", "wUmin", "wUmax",
                "wVmin", "wVmax", "wCaps", "wMaxAxes", "wNumAxes", "wMaxButtons",
            )],
            ("szRegKey", wintypes.WCHAR * 32),
            ("szOEMVxD", wintypes.WCHAR * 260),
        ]

    _JOY_RETURNBUTTONS, _JOY_RETURNPOV = 0x80, 0x40


def _load_xinput():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return ctypes.WinDLL(name)
        except OSError:
            continue
    return None


class _WindowsBackends:
    """Reads every connected controller; owns all ctypes state."""

    _SCAN_INTERVAL = 2.0

    def __init__(self) -> None:
        self._xinput = _load_xinput()
        self._winmm = ctypes.WinDLL("winmm")
        self._joysticks: dict[int, int] = {}  # winmm id -> vendor id
        self._xinput_slots: list[int] = []
        self._next_scan = 0.0

    def _scan(self) -> None:
        self._xinput_slots = []
        if self._xinput is not None:
            state = _XInputState()
            for slot in range(4):
                if self._xinput.XInputGetState(slot, ctypes.byref(state)) == 0:
                    self._xinput_slots.append(slot)
        self._joysticks = {}
        info = _JoyInfoEx(dwSize=ctypes.sizeof(_JoyInfoEx), dwFlags=_JOY_RETURNBUTTONS)
        caps = _JoyCapsW()
        for joy_id in range(min(self._winmm.joyGetNumDevs(), 16)):
            if self._winmm.joyGetPosEx(joy_id, ctypes.byref(info)) != 0:
                continue
            if self._winmm.joyGetDevCapsW(joy_id, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
                continue
            if caps.wMid == _MICROSOFT_VENDOR_ID and self._xinput is not None:
                continue  # Xbox pad: read through XInput instead
            self._joysticks[joy_id] = caps.wMid

    def connected(self) -> bool:
        return bool(self._xinput_slots or self._joysticks)

    def held(self) -> set[str]:
        """Union of buttons held on all connected controllers."""
        now = time.monotonic()
        if now >= self._next_scan:
            self._scan()
            self._next_scan = now + self._SCAN_INTERVAL
        held: set[str] = set()
        state = _XInputState()
        for slot in self._xinput_slots:
            if self._xinput.XInputGetState(slot, ctypes.byref(state)) == 0:
                pad = state.Gamepad
                held |= xinput_buttons(pad.wButtons, pad.bLeftTrigger, pad.bRightTrigger)
        info = _JoyInfoEx(
            dwSize=ctypes.sizeof(_JoyInfoEx), dwFlags=_JOY_RETURNBUTTONS | _JOY_RETURNPOV
        )
        for joy_id, vendor_id in self._joysticks.items():
            if self._winmm.joyGetPosEx(joy_id, ctypes.byref(info)) == 0:
                held |= winmm_buttons(info.dwButtons, info.dwPOV, vendor_id)
        return held


# ----------------------------------------------------------------
# Linux backend: /dev/input/js*
# ----------------------------------------------------------------
# Kernel input codes (linux/input-event-codes.h) -> shared names. 0x133 and
# 0x134 depend on the driver: Xbox-style drivers send the X button as 0x133,
# while Sony's send Triangle (the top button) there.
_LINUX_BUTTONS: dict[int, str] = {
    0x130: "south", 0x131: "east", 0x133: "west", 0x134: "north",
    0x136: "lb", 0x137: "rb", 0x138: "lt", 0x139: "rt", 0x13A: "back", 0x13B: "start",
    0x13C: "guide", 0x13D: "ls", 0x13E: "rs",
    0x220: "dpad_up", 0x221: "dpad_down", 0x222: "dpad_left", 0x223: "dpad_right",
}
_SONY_SWAPPED = {0x133: "north", 0x134: "west"}
_BTN_SOUTH = 0x130
_ABS_Z, _ABS_RZ, _ABS_HAT0X, _ABS_HAT0Y = 0x02, 0x05, 0x10, 0x11
# Before a driver reports its button map, assume the xpad (Xbox) order.
_XPAD_ORDER = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E]
_JS_EVENT = struct.Struct("<IhBB")  # time, value, type, number
_JS_BUTTON, _JS_AXIS, _JS_INIT = 0x01, 0x02, 0x80
_JSIOCGAXES, _JSIOCGBUTTONS = 0x80016A11, 0x80016A12
_JSIOCGAXMAP, _JSIOCGBTNMAP = 0x80406A32, 0x84006A34


def linux_button_name(code: int, number: int, vendor_id: int) -> str:
    """Shared name for a kernel button code (``button<n>`` if it isn't a gamepad button)."""
    if vendor_id == _SONY_VENDOR_ID and code in _SONY_SWAPPED:
        return _SONY_SWAPPED[code]
    return _LINUX_BUTTONS.get(code, f"button{number + 1}")


def linux_axis_buttons(code: int, value: int) -> set[str]:
    """Buttons an axis counts as: the d-pad hat, and the analog triggers past halfway."""
    if code == _ABS_HAT0X:
        return {"dpad_left"} if value < 0 else {"dpad_right"} if value > 0 else set()
    if code == _ABS_HAT0Y:
        return {"dpad_up"} if value < 0 else {"dpad_down"} if value > 0 else set()
    if code == _ABS_Z and value > 0:
        return {"lt"}
    if code == _ABS_RZ and value > 0:
        return {"rt"}
    return set()


class _Joystick:
    """One open /dev/input/jsN: its button/axis map and what is held right now."""

    def __init__(self, path: str) -> None:
        import fcntl

        self.path = path
        self._fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        vendor_id = self._vendor_id(path)
        counts = array.array("B", [0])
        fcntl.ioctl(self._fd, _JSIOCGBUTTONS, counts, True)
        button_count = counts[0]
        fcntl.ioctl(self._fd, _JSIOCGAXES, counts, True)
        axis_count = counts[0]
        button_map = array.array("H", [0] * 512)
        axis_map = array.array("B", [0] * 64)
        try:
            fcntl.ioctl(self._fd, _JSIOCGBTNMAP, button_map, True)
            fcntl.ioctl(self._fd, _JSIOCGAXMAP, axis_map, True)
        except OSError:  # an older kernel's map size
            button_map = array.array("H", _XPAD_ORDER + [0] * 512)
            axis_map = array.array("B", [0, 1, _ABS_Z, 3, 4, _ABS_RZ, _ABS_HAT0X, _ABS_HAT0Y])
        self._buttons = {
            number: linux_button_name(button_map[number], number, vendor_id)
            for number in range(button_count)
        }
        is_gamepad = _BTN_SOUTH in button_map[:button_count]
        # Analog triggers only on real gamepads: on a joystick ABS_Z is a throttle.
        self._axes = {
            number: axis_map[number] for number in range(min(axis_count, len(axis_map)))
            if is_gamepad or axis_map[number] in (_ABS_HAT0X, _ABS_HAT0Y)
        }
        self._pressed: set[str] = set()
        self._axis_buttons: dict[int, set[str]] = {}

    @staticmethod
    def _vendor_id(path: str) -> int:
        name = os.path.basename(path)
        try:
            with open(f"/sys/class/input/{name}/device/id/vendor", encoding="ascii") as file:
                return int(file.read().strip(), 16)
        except (OSError, ValueError):
            return 0

    def read(self) -> set[str]:
        """Apply waiting events; raises OSError once the controller is unplugged."""
        while True:
            try:
                data = os.read(self._fd, _JS_EVENT.size * 32)
            except BlockingIOError:
                break
            if not data:
                break
            for offset in range(0, len(data) - _JS_EVENT.size + 1, _JS_EVENT.size):
                _time, value, kind, number = _JS_EVENT.unpack_from(data, offset)
                kind &= ~_JS_INIT
                if kind == _JS_BUTTON and number in self._buttons:
                    name = self._buttons[number]
                    if value:
                        self._pressed.add(name)
                    else:
                        self._pressed.discard(name)
                elif kind == _JS_AXIS and number in self._axes:
                    self._axis_buttons[number] = linux_axis_buttons(self._axes[number], value)
        held = set(self._pressed)
        for buttons in self._axis_buttons.values():
            held |= buttons
        return held

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


class _LinuxBackends:
    """Reads every /dev/input/js* controller."""

    _SCAN_INTERVAL = 2.0

    def __init__(self) -> None:
        self._pads: dict[str, _Joystick] = {}
        self._next_scan = 0.0

    def _scan(self) -> None:
        for path in sorted(glob.glob("/dev/input/js*")):
            if path in self._pads:
                continue
            try:
                self._pads[path] = _Joystick(path)
                logger.info("Controller found: %s", path)
            except OSError:
                logger.debug("Can't read %s", path, exc_info=True)

    def connected(self) -> bool:
        return bool(self._pads)

    def held(self) -> set[str]:
        now = time.monotonic()
        if now >= self._next_scan:
            self._scan()
            self._next_scan = now + self._SCAN_INTERVAL
        held: set[str] = set()
        for path, pad in list(self._pads.items()):
            try:
                held |= pad.read()
            except OSError:  # unplugged
                pad.close()
                del self._pads[path]
        return held


_Backends = _LinuxBackends if sys.platform.startswith("linux") else _WindowsBackends


def controllers_supported() -> bool:
    """Whether controller bindings work on this OS."""
    return sys.platform == "win32" or sys.platform.startswith("linux")


class GamepadManager(QObject):
    """
    Polls controllers and emits per-action signals for bound combos.

    Signals mirror :class:`~src.hotkeys.hotkey_manager.HotkeyManager`'s, so
    the main window connects both to the same handlers.

    Signals:
        action_triggered: Emitted with the action name ("increment", …).
        combo_recorded: Emitted with the stored combo text while recording.
        connection_changed: Emitted with True/False as controllers come and go.
    """

    action_triggered = Signal(str)
    combo_recorded = Signal(str)
    connection_changed = Signal(bool)

    _POLL_SECONDS = 1 / 60
    _IDLE_SECONDS = 1.0

    def __init__(self, bindings: dict[str, str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._tracker = ComboTracker(bindings)
        self._recorder: ComboRecorder | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False

    def start(self) -> None:
        if not controllers_supported() or self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="GamepadListener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def update_bindings(self, bindings: dict[str, str]) -> None:
        with self._lock:
            self._tracker.set_bindings(bindings)

    def start_recording(self) -> None:
        """Next combo pressed and released is emitted via combo_recorded (no actions)."""
        with self._lock:
            self._recorder = ComboRecorder()

    def cancel_recording(self) -> None:
        with self._lock:
            self._recorder = None

    def _run(self) -> None:
        try:
            backends = _Backends()
        except OSError:
            logger.warning("Controller APIs unavailable; controller bindings disabled")
            return
        logger.info("Controller listener started")
        while not self._stop_event.is_set():
            try:
                held = backends.held()
            except OSError:
                logger.debug("Controller poll failed", exc_info=True)
                held = set()
            connected = backends.connected()
            if connected != self.connected:
                self.connected = connected
                self.connection_changed.emit(connected)
                logger.info("Controller %s", "connected" if connected else "disconnected")

            with self._lock:
                recorder = self._recorder
                if recorder is not None:
                    recorded = recorder.update(held)
                    if recorded:
                        self._recorder = None
                    self._tracker.update(held)  # keep edge state, but fire nothing
                    fired: list[str] = []
                else:
                    recorded = None
                    fired = self._tracker.update(held)
            if recorded:
                self.combo_recorded.emit(combo_text(recorded))
            for action in fired:
                self.action_triggered.emit(action)

            self._stop_event.wait(self._POLL_SECONDS if connected else self._IDLE_SECONDS)
