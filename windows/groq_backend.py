"""
groq_backend.py — Cloud transcription through Groq's OpenAI-compatible Whisper API.
Same start / wait_ready / transcribe / stop as server.WhisperServer, so whisper_tray.py
can use either one without caring which it got.
Does no network traffic at startup: booting offline must not kill the tray app.
"""

import logging
import os

import openai

from server import clean_transcript

log = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")   # or whisper-large-v3
GROQ_MAX_UPLOAD_BYTES = 24 * 1024 * 1024    # the free tier caps uploads at 25 MB
MAX_SECONDS = 12 * 60                       # 16 kHz mono int16 WAV is 32 KB/s → ~23 MB at 12 min


def resolve_groq_key() -> str:
    """GROQ_API_KEY from the environment (install.ps1 -Groq saves it as a user variable)."""
    return os.environ.get("GROQ_API_KEY", "").strip()


class GroqBackend:
    name = "Groq"
    max_seconds = MAX_SECONDS

    def __init__(self, language: str, model: str, api_key: str):
        self.model = model
        # Groq wants ISO-639-1 ("es", "en"); "auto" or anything else → omitted → server-side detection
        self.language = language if len(language) == 2 and language.isalpha() else None
        if self.language is None and language != "auto":
            log.warning("WHISPER_LANG=%r is not an ISO-639-1 code; letting Groq auto-detect.", language)
        # The SDK retries connection errors and 408/409/429/5xx with backoff and honours Retry-After,
        # so no retry wrapper is needed here. connect=5 keeps an offline failure fast.
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
            max_retries=3,
            timeout=openai.Timeout(120.0, connect=5.0),
        )

    # ── Lifecycle: nothing to launch, nothing to wait for ─────────────────────

    def start(self) -> None:
        pass

    def wait_ready(self, timeout: float = 0) -> None:
        pass

    def stop(self) -> None:
        pass

    # ── Transcription ─────────────────────────────────────────────────────────

    def transcribe(self, wav: bytes) -> str:
        if len(wav) > GROQ_MAX_UPLOAD_BYTES:
            raise RuntimeError("Recording too large for Groq (25 MB cap)")
        kwargs = {
            "file": ("audio.wav", wav, "audio/wav"),
            "model": self.model,
            "response_format": "json",
            "temperature": 0.0,
        }
        if self.language:
            kwargs["language"] = self.language
        log.info("Groq: uploading %.2f MB to %s", len(wav) / 1048576, self.model)
        try:
            resp = self._client.audio.transcriptions.create(**kwargs)
        except openai.AuthenticationError as exc:            # 401, not retried
            raise RuntimeError("Invalid Groq API key") from exc
        except openai.PermissionDeniedError as exc:          # 403
            raise RuntimeError("Groq refused the key (403)") from exc
        except openai.RateLimitError as exc:                 # 429, after the SDK's own retries
            raise RuntimeError("Groq rate limit — wait a moment") from exc
        except openai.APITimeoutError as exc:                # subclass of APIConnectionError: must come first
            raise RuntimeError("Groq timed out") from exc
        except openai.APIConnectionError as exc:
            raise RuntimeError("Groq unreachable (offline?)") from exc
        except openai.APIStatusError as exc:                 # 400/404/413/422/5xx
            if exc.status_code == 413:
                raise RuntimeError("Recording too large for Groq (25 MB cap)") from exc
            raise RuntimeError(f"Groq error {exc.status_code}") from exc
        return clean_transcript(resp.text or "")
