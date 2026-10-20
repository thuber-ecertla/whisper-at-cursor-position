"""
overlay.py — Floating status pill (bottom-center of the monitor under the cursor).
Click-through, always on top, never takes focus, no taskbar button.
Must be driven from the Tk main thread.
"""

import ctypes
import ctypes.wintypes as wt
import time
import tkinter as tk
import tkinter.font as tkfont

KEY_COLOR = "#010101"   # painted pixels of this color become fully transparent
PILL_COLOR = "#202020"
BORDER_COLOR = "#4a4a4a"
TEXT_COLOR = "#f2f2f2"

STYLES = {
    #  state          dot color   default text
    "loading":      ("#9e9e9e", "Loading model…"),
    "recording":    ("#ff4545", "Recording"),
    "transcribing": ("#ffb300", "Transcribing…"),
    "info":         ("#9e9e9e", ""),
    "error":        ("#ff4545", "Error"),
}

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40
SW_HIDE = 0
GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAncestor.restype = wt.HWND
_user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
_user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
_user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, wt.LONG]
_user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wt.UINT]
_user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
_user32.MonitorFromPoint.restype = wt.HMONITOR
_user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def _work_area_under_cursor() -> wt.RECT:
    pt = wt.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    mon = _user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    _user32.GetMonitorInfoW(mon, ctypes.byref(info))
    return info.rcWork


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class Overlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.s = root.winfo_fpixels("1i") / 96.0      # DPI scale
        self.h = round(40 * self.s)
        self.font = tkfont.Font(family="Segoe UI", size=11)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=KEY_COLOR)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", KEY_COLOR)
        self.canvas = tk.Canvas(self.win, bg=KEY_COLOR, highlightthickness=0, bd=0, height=self.h)
        self.canvas.pack()

        # Map it off-screen once so the HWND exists, then take over visibility
        self.win.geometry("10x10+-32000+-32000")
        self.win.update()
        self.hwnd = _user32.GetAncestor(self.win.winfo_id(), GA_ROOT)
        ex = _user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                               ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        _user32.ShowWindow(self.hwnd, SW_HIDE)

        self.state = None
        self.text = ""
        self.t0 = 0.0
        self._hide_job = None
        self._tick_job = None

    # ── Public API ────────────────────────────────────────────────────────────

    def show(self, state: str, text: str = None, hide_after_ms: int = None) -> None:
        self._cancel_jobs()
        self.state = state
        self.text = text if text is not None else STYLES[state][1]
        self.t0 = time.monotonic()
        self._draw()
        self._place()
        _user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        if state == "recording":
            self._tick_job = self.root.after(250, self._tick)
        if hide_after_ms:
            self._hide_job = self.root.after(hide_after_ms, self.hide)

    def hide(self) -> None:
        self._cancel_jobs()
        self.state = None
        _user32.ShowWindow(self.hwnd, SW_HIDE)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _cancel_jobs(self) -> None:
        for job in (self._hide_job, self._tick_job):
            if job:
                self.root.after_cancel(job)
        self._hide_job = self._tick_job = None

    def _label(self) -> str:
        if self.state == "recording":
            return f"{self.text}   {_fmt_elapsed(time.monotonic() - self.t0)}"
        return self.text

    def _draw(self, dim_dot: bool = False) -> None:
        s, h = self.s, self.h
        label = self._label()
        if len(label) > 80:
            label = label[:79] + "…"
        pad, dot = round(16 * s), round(10 * s)
        text_w = self.font.measure(label if self.state != "recording" else self.text + "   00:00")
        w = max(round(180 * s), pad + dot + round(10 * s) + text_w + pad)
        self.w = w

        c = self.canvas
        c.delete("all")
        c.configure(width=w, height=h)
        # Stadium shape (two half-circles + a rectangle), border then fill inset by 1px
        for inset, fill in ((0, BORDER_COLOR), (max(1, round(self.s)), PILL_COLOR)):
            i, hh = inset, h - inset
            c.create_oval(i, i, hh, hh, fill=fill, outline="")
            c.create_oval(w - hh, i, w - i, hh, fill=fill, outline="")
            c.create_rectangle(h / 2, i, w - h / 2, hh, fill=fill, outline="")

        color = STYLES[self.state][0]
        if dim_dot:
            color = PILL_COLOR if self.state == "recording" else color
        cy = h / 2
        c.create_oval(pad, cy - dot / 2, pad + dot, cy + dot / 2, fill=color, outline="")
        c.create_text(pad + dot + round(10 * s), cy, text=label, anchor="w",
                      fill=TEXT_COLOR, font=self.font)

    def _place(self) -> None:
        wa = _work_area_under_cursor()
        x = (wa.left + wa.right - self.w) // 2
        y = wa.bottom - self.h - round(28 * self.s)
        self.win.geometry(f"{self.w}x{self.h}+{x}+{y}")
        self.win.update_idletasks()

    def _tick(self) -> None:
        # Blink the red dot twice a second, refresh the timer
        blink = int((time.monotonic() - self.t0) * 2) % 2 == 1
        self._draw(dim_dot=blink)
        self._tick_job = self.root.after(250, self._tick)
