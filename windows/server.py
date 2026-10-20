"""
server.py — Lifecycle of the whisper.cpp HTTP server (whisper-server.exe)
- Launches it hidden, bound to localhost, with the model pre-loaded in VRAM
- Ties it to a Job Object so it dies with this process, even on a crash
- Sends WAV audio to /inference and returns the transcript
"""

import ctypes
import ctypes.wintypes as wt
import json
import logging
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

# Tokens whisper.cpp emits for silence / non-speech, e.g. "[BLANK_AUDIO]", "(music)"
_NON_SPEECH = re.compile(r"^\s*[\[(][^\])]*[\])]\s*$")


def clean_transcript(text: str) -> str:
    """Drop non-speech markers ("[BLANK_AUDIO]", "(music)") and join the lines."""
    lines = [ln.strip() for ln in text.splitlines()]
    return " ".join(ln for ln in lines if ln and not _NON_SPEECH.match(ln))


# ── Job Object (kill child when parent exits) ─────────────────────────────────

class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_JobObjectExtendedLimitInformation = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateJobObjectW.restype = wt.HANDLE
_kernel32.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
_kernel32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD]
_kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]


def _kill_on_close_job(proc: subprocess.Popen):
    """Put *proc* in a job that is killed when our last handle to it closes."""
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        log.warning("CreateJobObject failed: %d", ctypes.get_last_error())
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _kernel32.SetInformationJobObject(
        job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
    if not _kernel32.AssignProcessToJobObject(job, int(proc._handle)):
        log.warning("AssignProcessToJobObject failed: %d", ctypes.get_last_error())
    return job  # must stay referenced for the lifetime of the process


# ── Server ─────────────────────────────────────────────────────────────────────

class WhisperServer:
    name = "local"
    max_seconds = None      # no recording cap: the audio never leaves the machine

    def __init__(self, exe: str, model: str, language: str, port: int):
        self.exe = exe
        self.model = model
        self.language = language
        self.url = f"http://127.0.0.1:{port}"
        self.port = port
        self.proc = None
        self._job = None

    def start(self) -> None:
        # Leftover from a previous crash would hold the port (and the VRAM)
        subprocess.run(
            ["taskkill", "/F", "/IM", "whisper-server.exe"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        cmd = [
            self.exe,
            "-m", self.model,
            "-l", self.language,
            "--host", "127.0.0.1",
            "--port", str(self.port),
        ]
        log.info("Starting %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        self._job = _kill_on_close_job(self.proc)
        threading.Thread(target=self._pump_output, daemon=True).start()

    def _pump_output(self) -> None:
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                log.info("[server] %s", line)

    def wait_ready(self, timeout: float = 600) -> None:
        """Block until the model is loaded (GET /health → 200)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"whisper-server exited with code {self.proc.returncode}")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.5)
        raise TimeoutError("whisper-server did not become ready in time")

    def transcribe(self, wav: bytes) -> str:
        boundary = uuid.uuid4().hex
        fields = {"response_format": "json", "temperature": "0.0", "language": self.language}
        body = bytearray()
        for name, value in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                     f"{value}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f"filename=\"audio.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
        body += wav + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            self.url + "/inference",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.loads(r.read().decode("utf-8"))
        if "error" in result:
            raise RuntimeError(result["error"])

        return clean_transcript(result.get("text", ""))

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            log.info("Stopping whisper-server.")
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
