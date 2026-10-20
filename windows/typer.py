"""
typer.py — Type text at the current cursor position via SendInput.
Uses KEYEVENTF_UNICODE, so accents, ¿, ñ and emoji are typed as-is
regardless of the active keyboard layout.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import time

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D

CHUNK_CHARS = 64        # characters per SendInput batch
CHUNK_DELAY = 0.005     # pause between batches so slow apps keep up


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_user32.SendInput.restype = wt.UINT


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    inp = _INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)
    return inp


def _events_for(text: str):
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            yield _key(vk=VK_RETURN)
            yield _key(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)
            continue
        # Characters outside the BMP are sent as a UTF-16 surrogate pair
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            yield _key(scan=unit, flags=KEYEVENTF_UNICODE)
            yield _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def type_text(text: str) -> None:
    for start in range(0, len(text), CHUNK_CHARS):
        events = list(_events_for(text[start:start + CHUNK_CHARS]))
        arr = (_INPUT * len(events))(*events)
        sent = _user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
        if sent != len(events):
            # Typically UIPI: the focused window belongs to an elevated process
            raise OSError(f"SendInput delivered {sent}/{len(events)} events "
                          f"(error {ctypes.get_last_error()}); is the target window running as admin?")
        time.sleep(CHUNK_DELAY)
