"""
Screen capture through DXGI Desktop Duplication (Windows 8+).

The normal capture (``mss``, GDI) reads what Windows composes for the
desktop. A game in exclusive fullscreen draws straight to the display, so
that capture comes out black. Desktop Duplication reads the display's own
picture from the graphics card instead (what OBS's Display Capture uses),
so it sees those games too, still without touching the game.

Only used as a fallback when the normal capture is black: see
:class:`FallbackCapture`. Plain ``ctypes`` COM calls, no extra dependency.

Each display gets one duplication. Its newest frame is kept on the graphics
card; a capture copies just the requested rectangle back, so a small region
costs little even on a 4K display.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import numpy as np

from src.utils.logger import get_logger
from src.utils.platform_info import IS_WINDOWS

logger = get_logger(__name__)

Rect = tuple[int, int, int, int]  # left, top, width, height

_HRESULT = ctypes.c_long
_WAIT_TIMEOUT = -2005270489  # DXGI_ERROR_WAIT_TIMEOUT (0x887A0027): no new frame yet
_ACCESS_LOST = -2005270490  # DXGI_ERROR_ACCESS_LOST (0x887A0026): mode change, UAC, …
_NOT_FOUND = -2005270526  # DXGI_ERROR_NOT_FOUND (0x887A0002): no more adapters/outputs
_BGRA_FORMATS = (87, 91)  # DXGI_FORMAT_B8G8R8A8_UNORM (and _SRGB)
_USAGE_STAGING = 3
_CPU_ACCESS_READ = 0x20000
_MAP_READ = 1
_SDK_VERSION = 7


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    parts = text.split("-")
    tail = bytes.fromhex(parts[3] + parts[4])
    return _GUID(
        int(parts[0], 16), int(parts[1], 16), int(parts[2], 16), (ctypes.c_ubyte * 8)(*tail)
    )


_IID_FACTORY1 = _guid("770aae78-f26f-4dba-a829-253c83d1b387")
_IID_OUTPUT1 = _guid("00cddea8-939b-4b83-a340-a685226666cc")
_IID_TEXTURE2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class _OutputDesc(ctypes.Structure):  # DXGI_OUTPUT_DESC
    _fields_ = [
        ("DeviceName", ctypes.c_wchar * 32),
        ("DesktopCoordinates", wintypes.RECT),
        ("AttachedToDesktop", wintypes.BOOL),
        ("Rotation", ctypes.c_uint),
        ("Monitor", ctypes.c_void_p),
    ]


class _FrameInfo(ctypes.Structure):  # DXGI_OUTDUPL_FRAME_INFO
    _fields_ = [
        ("LastPresentTime", ctypes.c_longlong),
        ("LastMouseUpdateTime", ctypes.c_longlong),
        ("AccumulatedFrames", ctypes.c_uint),
        ("RectsCoalesced", wintypes.BOOL),
        ("ProtectedContentMaskedOut", wintypes.BOOL),
        ("PointerPosition", wintypes.POINT),
        ("PointerVisible", wintypes.BOOL),
        ("TotalMetadataBufferSize", ctypes.c_uint),
        ("PointerShapeBufferSize", ctypes.c_uint),
    ]


class _TextureDesc(ctypes.Structure):  # D3D11_TEXTURE2D_DESC
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("MipLevels", ctypes.c_uint),
        ("ArraySize", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("SampleCount", ctypes.c_uint),
        ("SampleQuality", ctypes.c_uint),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
    ]


class _Box(ctypes.Structure):  # D3D11_BOX
    _fields_ = [(name, ctypes.c_uint) for name in
                ("left", "top", "front", "right", "bottom", "back")]


class _Mapped(ctypes.Structure):  # D3D11_MAPPED_SUBRESOURCE
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint),
                ("DepthPitch", ctypes.c_uint)]


class DuplicationError(OSError):
    """Desktop Duplication isn't available (or stopped working) here."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


def _method(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    """COM method number ``index`` of ``obj``, ready to call with ``obj`` first."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def _check(result: int, what: str) -> None:
    if result < 0:
        raise DuplicationError(f"{what} failed (0x{result & 0xFFFFFFFF:08X})", result)


def _release(obj: ctypes.c_void_p | None) -> None:
    if obj:
        _method(obj, 2, ctypes.c_ulong)(obj)


def _query(obj: ctypes.c_void_p, iid: _GUID) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    _check(_method(obj, 0, _HRESULT, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
        obj, ctypes.byref(iid), ctypes.byref(out)), "QueryInterface")
    return out


class _Display:
    """One display's duplication: its newest frame, copied out rectangle by rectangle."""

    def __init__(self, adapter: ctypes.c_void_p, output: ctypes.c_void_p, rect: Rect) -> None:
        self.rect = rect
        self._device = ctypes.c_void_p()
        self._context = ctypes.c_void_p()
        self._duplication = ctypes.c_void_p()
        self._latest: ctypes.c_void_p | None = None  # newest frame, on the graphics card
        self._staging: dict[tuple[int, int], ctypes.c_void_p] = {}
        self._have_frame = False
        create = ctypes.windll.d3d11.D3D11CreateDevice
        create.restype = _HRESULT
        _check(create(adapter, 0, None, 0, None, 0, _SDK_VERSION,  # 0: D3D_DRIVER_TYPE_UNKNOWN
                      ctypes.byref(self._device), None, ctypes.byref(self._context)),
               "D3D11CreateDevice")
        output1 = _query(output, _IID_OUTPUT1)
        try:
            # IDXGIOutput1::DuplicateOutput
            _check(_method(output1, 22, _HRESULT, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_void_p))(
                output1, self._device, ctypes.byref(self._duplication)), "DuplicateOutput")
        finally:
            _release(output1)

    def close(self) -> None:
        for texture in self._staging.values():
            _release(texture)
        self._staging.clear()
        for obj in (self._latest, self._duplication, self._context, self._device):
            _release(obj)
        self._latest = None
        self._duplication = self._context = self._device = ctypes.c_void_p()

    def _update(self) -> None:
        """Take the newest frame, if a new one came since the last capture."""
        info = _FrameInfo()
        resource = ctypes.c_void_p()
        # IDXGIOutputDuplication::AcquireNextFrame (wait up to 100 ms for the first one)
        result = _method(self._duplication, 8, _HRESULT, ctypes.c_uint,
                         ctypes.POINTER(_FrameInfo), ctypes.POINTER(ctypes.c_void_p))(
            self._duplication, 0 if self._have_frame else 100,
            ctypes.byref(info), ctypes.byref(resource))
        if result == _WAIT_TIMEOUT:
            return  # nothing changed on screen: the kept frame is current
        _check(result, "AcquireNextFrame")
        try:
            texture = _query(resource, _IID_TEXTURE2D)
            try:
                if self._latest is None:
                    desc = _TextureDesc()
                    _method(texture, 10, None, ctypes.POINTER(_TextureDesc))(
                        texture, ctypes.byref(desc))  # ID3D11Texture2D::GetDesc
                    if desc.Format not in _BGRA_FORMATS:
                        raise DuplicationError(f"display format {desc.Format} not supported")
                    # A process that isn't DPI aware gets scaled desktop coordinates
                    # but full-size frames: rectangles wouldn't line up.
                    if (desc.Width, desc.Height) != self.rect[2:]:
                        raise DuplicationError("display scaling doesn't match the frame")
                    desc.Usage, desc.BindFlags, desc.CPUAccessFlags, desc.MiscFlags = 0, 0, 0, 0
                    self._latest = self._texture(desc)
                # ID3D11DeviceContext::CopyResource
                _method(self._context, 47, None, ctypes.c_void_p, ctypes.c_void_p)(
                    self._context, self._latest, texture)
                self._have_frame = True
            finally:
                _release(texture)
        finally:
            _release(resource)
            _method(self._duplication, 14, _HRESULT)(self._duplication)  # ReleaseFrame

    def _texture(self, desc: _TextureDesc) -> ctypes.c_void_p:
        texture = ctypes.c_void_p()
        # ID3D11Device::CreateTexture2D
        _check(_method(self._device, 5, _HRESULT, ctypes.POINTER(_TextureDesc), ctypes.c_void_p,
                       ctypes.POINTER(ctypes.c_void_p))(
            self._device, ctypes.byref(desc), None, ctypes.byref(texture)), "CreateTexture2D")
        return texture

    def grab(self, left: int, top: int, width: int, height: int) -> np.ndarray | None:
        """BGRA pixels of a rectangle in this display's own coordinates (None: no frame yet)."""
        self._update()
        if not self._have_frame:
            return None
        staging = self._staging.get((width, height))
        if staging is None:
            if len(self._staging) > 8:  # regions change with the game: don't pile up
                for texture in self._staging.values():
                    _release(texture)
                self._staging.clear()
            desc = _TextureDesc(width, height, 1, 1, _BGRA_FORMATS[0], 1, 0,
                                _USAGE_STAGING, 0, _CPU_ACCESS_READ, 0)
            staging = self._staging[(width, height)] = self._texture(desc)
        box = _Box(left, top, 0, left + width, top + height, 1)
        # ID3D11DeviceContext::CopySubresourceRegion
        _method(self._context, 46, None, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
                ctypes.POINTER(_Box))(
            self._context, staging, 0, 0, 0, 0, self._latest, 0, ctypes.byref(box))
        mapped = _Mapped()
        # ID3D11DeviceContext::Map / Unmap
        _check(_method(self._context, 14, _HRESULT, ctypes.c_void_p, ctypes.c_uint,
                       ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(_Mapped))(
            self._context, staging, 0, _MAP_READ, 0, ctypes.byref(mapped)), "Map")
        try:
            buffer = (ctypes.c_ubyte * (mapped.RowPitch * height)).from_address(mapped.pData)
            rows = np.frombuffer(buffer, dtype=np.uint8).reshape(height, mapped.RowPitch)
            return rows[:, : width * 4].reshape(height, width, 4).copy()
        finally:
            _method(self._context, 15, None, ctypes.c_void_p, ctypes.c_uint)(
                self._context, staging, 0)


class DesktopDuplicator:
    """Captures any desktop rectangle through Desktop Duplication."""

    def __init__(self) -> None:
        if not IS_WINDOWS:
            raise DuplicationError("Desktop Duplication is Windows only")
        self._displays: list[_Display] = []
        self._open()

    def _open(self) -> None:
        factory = ctypes.c_void_p()
        create = ctypes.windll.dxgi.CreateDXGIFactory1
        create.restype = _HRESULT
        _check(create(ctypes.byref(_IID_FACTORY1), ctypes.byref(factory)), "CreateDXGIFactory1")
        try:
            # Each display through the graphics card that drives it (laptops with
            # two GPUs can't duplicate a display from the other card).
            for a in range(16):
                adapter = ctypes.c_void_p()
                result = _method(factory, 12, _HRESULT, ctypes.c_uint,
                                 ctypes.POINTER(ctypes.c_void_p))(  # EnumAdapters1
                    factory, a, ctypes.byref(adapter))
                if result == _NOT_FOUND:
                    break
                _check(result, "EnumAdapters1")
                try:
                    self._open_outputs(adapter)
                finally:
                    _release(adapter)
        finally:
            _release(factory)
        if not self._displays:
            raise DuplicationError("no display could be duplicated")

    def _open_outputs(self, adapter: ctypes.c_void_p) -> None:
        for o in range(16):
            output = ctypes.c_void_p()
            result = _method(adapter, 7, _HRESULT, ctypes.c_uint,
                             ctypes.POINTER(ctypes.c_void_p))(  # EnumOutputs
                adapter, o, ctypes.byref(output))
            if result == _NOT_FOUND:
                return
            _check(result, "EnumOutputs")
            try:
                desc = _OutputDesc()
                _check(_method(output, 7, _HRESULT, ctypes.POINTER(_OutputDesc))(
                    output, ctypes.byref(desc)), "GetDesc")
                # Rotated displays come out sideways: leave those to the normal capture.
                if not desc.AttachedToDesktop or desc.Rotation not in (0, 1):
                    continue
                r = desc.DesktopCoordinates
                rect = (r.left, r.top, r.right - r.left, r.bottom - r.top)
                try:
                    self._displays.append(_Display(adapter, output, rect))
                except DuplicationError as exc:
                    logger.info("Display at %s can't be duplicated: %s", rect, exc)
            finally:
                _release(output)

    def close(self) -> None:
        for display in self._displays:
            display.close()
        self._displays.clear()

    def grab(self, rect: Rect) -> np.ndarray | None:
        """
        BGRA pixels of ``rect`` (desktop coordinates) from the display it's on,
        cut to that display. None if there's no picture yet.
        """
        left, top, width, height = rect
        center_x, center_y = left + width // 2, top + height // 2
        for display in self._displays:
            d_left, d_top, d_width, d_height = display.rect
            if d_left <= center_x < d_left + d_width and d_top <= center_y < d_top + d_height:
                break
        else:
            return None
        x0, y0 = max(left, d_left), max(top, d_top)
        x1 = min(left + width, d_left + d_width)
        y1 = min(top + height, d_top + d_height)
        try:
            pixels = display.grab(x0 - d_left, y0 - d_top, x1 - x0, y1 - y0)
        except DuplicationError as exc:
            if exc.code != _ACCESS_LOST:  # not just "access lost": give up
                raise
            # A display mode change, UAC prompt or fullscreen switch: start over.
            logger.info("Desktop Duplication was interrupted; reopening it")
            self.close()
            self._open()
            return None
        if pixels is None or (x0, y0, x1 - x0, y1 - y0) == rect:
            return pixels
        canvas = np.zeros((height, width, 4), dtype=np.uint8)  # part of it off the display
        canvas[y0 - top: y1 - top, x0 - left: x1 - left] = pixels
        return canvas


class FallbackCapture:
    """
    An ``mss`` capture that can switch to Desktop Duplication: the same
    ``grab`` and ``monitors`` as mss, so the detection code doesn't change.
    Call :meth:`use_duplication` when the normal capture keeps coming out
    black; it returns False if Desktop Duplication can't be used (right now).
    """

    RETRY_SECONDS = 30.0  # after a failure (e.g. during a UAC prompt), try again later

    def __init__(self, sct) -> None:
        self._sct = sct
        self._duplicator: DesktopDuplicator | None = None
        self._retry_at = 0.0

    @property
    def monitors(self):
        return self._sct.monitors

    @property
    def duplicating(self) -> bool:
        return self._duplicator is not None

    def use_duplication(self) -> bool:
        if self._duplicator is None and time.monotonic() >= self._retry_at:
            try:
                self._duplicator = DesktopDuplicator()
                logger.info("Capture is black: switched to Desktop Duplication")
            except (DuplicationError, OSError, AttributeError) as exc:
                self._retry_at = time.monotonic() + self.RETRY_SECONDS
                logger.info("Desktop Duplication isn't available: %s", exc)
        return self._duplicator is not None

    def reset(self) -> None:
        """Back to the normal capture; Desktop Duplication may be tried again at once."""
        self.close()
        self._retry_at = 0.0

    def grab(self, area: dict):
        if self._duplicator is not None:
            rect = (area["left"], area["top"], area["width"], area["height"])
            try:
                pixels = self._duplicator.grab(rect)
            except (DuplicationError, OSError) as exc:
                logger.info("Desktop Duplication stopped (%s); back to the normal capture", exc)
                self.close()
                self._retry_at = time.monotonic() + self.RETRY_SECONDS
                pixels = None
            if pixels is not None:
                return pixels
        return self._sct.grab(area)

    def close(self) -> None:
        if self._duplicator is not None:
            self._duplicator.close()
            self._duplicator = None
