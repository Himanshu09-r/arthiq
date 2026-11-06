"""Gnani (Vachana) speech over plain HTTPS: Prisma speech-to-text, Timbre text-to-speech.
Uses httpx, which is already installed. STT and TTS use two different API keys."""
import io
import os
import re
import threading
import time
import wave

import httpx
from dotenv import load_dotenv

from app.voice.provider import GNANI_LANGS

load_dotenv()
BASE = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai").rstrip("/")

_stt_lock = threading.Lock()      # some accounts allow only 1 active request at a time
_tts_lock = threading.Lock()

HINTS = {
    401: "invalid or missing API key (check the key for this service in .env)",
    402: "no credit left on this Gnani account",
    403: "this key is not allowed for this service. Check that GNANI_STT_API_KEY is the "
         "speech-to-text key and GNANI_TTS_API_KEY is the text-to-speech key",
    429: "rate limited (this account may allow only one request at a time)",
}


class GnaniError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _key(env_name: str) -> str:
    k = os.getenv(env_name, "").strip()
    if not k:
        raise GnaniError(f"{env_name} is not set in .env")
    return k


def _err_message(r) -> str:
    try:
        j = r.json()
    except Exception:
        return r.text[:200]
    if isinstance(j, dict):
        d = j.get("detail")
        if isinstance(d, dict):
            return d.get("message") or str(d)
        if isinstance(d, list):
            return "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)[:200]
        e = j.get("error")
        if isinstance(e, dict):
            return e.get("message") or str(e)
        return j.get("message") or (e if isinstance(e, str) else str(j)[:200])
    return str(j)[:200]


def _call(lock, make_request):
    """Run one request. Retries rate limits, server errors and network problems."""
    delay, last = 0.6, None
    for _ in range(3):
        try:
            with lock:
                r = make_request()
        except httpx.HTTPError as e:
            last = GnaniError(f"network error: {e}")
        else:
            if r.status_code == 200:
                return r
            hint = HINTS.get(r.status_code)
            msg = f"HTTP {r.status_code}: {_err_message(r)}" + (f" ({hint})" if hint else "")
            last = GnaniError(msg, r.status_code)
            if r.status_code not in (429, 500, 502, 503, 504):
                raise last
        time.sleep(delay)
        delay *= 2
    raise last


# ------------------------------- speech to text -------------------------------
def stt(wav_bytes: bytes, language=None):
    """WAV bytes -> (transcript, detected language code or None)."""
    if language is not None and language not in GNANI_LANGS:
        raise GnaniError(f"Gnani does not support {language} (Odia is not available)")
    key = _key("GNANI_STT_API_KEY")
    model = os.getenv("GNANI_STT_MODEL", "prisma-v3.0").strip()
    fmt = os.getenv("GNANI_STT_FORMAT", "transcribe").strip()

    data = {"format": fmt}
    if model == "prisma-v3.0":
        data["model"] = model
        if language is None:
            data["language_code"] = "indic-auto"
        elif language == "en-IN":
            data["language_code"] = "en-IN,hi-IN"          # hints, not a lock
        else:
            data["language_code"] = f"{language},en-IN"    # shop language + English words
    else:                                                    # Prisma v2.5: one language only
        data["language_code"] = language or "hi-IN"

    def request():
        return httpx.post(
            f"{BASE}/stt/v3", headers={"X-API-Key-ID": key}, data=data,
            files={"audio_file": ("speech.wav", wav_bytes, "audio/wav")},
            timeout=httpx.Timeout(40.0))

    body = _call(_stt_lock, request).json()
    text = body.get("transcript") or ""
    if isinstance(text, dict):                               # defensive: older response shape
        text = text.get("literal") or str(text)
    return str(text).strip(), body.get("detected_language_code")


# ------------------------------- text to speech -------------------------------
def _chunks(text: str, limit: int = 450):
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for part in re.split(r"(?<=[.!?।॥])\s+", text):
        if cur and len(cur) + 1 + len(part) > limit:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        out.append(cur)
    return out


def _join_wavs(chunks):
    if len(chunks) == 1:
        return chunks[0]
    try:
        frames, params = [], None
        for c in chunks:
            with wave.open(io.BytesIO(c), "rb") as w:
                params = params or w.getparams()
                frames.append(w.readframes(w.getnframes()))
        out = io.BytesIO()
        with wave.open(out, "wb") as wo:
            wo.setparams(params)
            for f in frames:
                wo.writeframes(f)
        return out.getvalue()
    except Exception as e:
        raise GnaniError(f"could not join audio chunks: {e}")


def _synthesize(text: str, language: str, key: str) -> bytes:
    model = os.getenv("GNANI_TTS_MODEL", "timbre-v3.0").strip()
    voice = os.getenv("GNANI_TTS_VOICE", "Shivani").strip()
    body = {
        "text": text, "model": model, "voice": voice, "language": language,
        "speed": float(os.getenv("GNANI_TTS_SPEED", "1.0")),
        "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }

    def request():
        return httpx.post(f"{BASE}/api/v1/tts/inference",
                          headers={"X-API-Key-ID": key, "Content-Type": "application/json"},
                          json=body, timeout=httpx.Timeout(40.0))

    audio = _call(_tts_lock, request).content
    if not audio.startswith(b"RIFF"):
        raise GnaniError(f"unexpected TTS response: {audio[:120]!r}")
    return audio


def tts(text: str, language: str) -> bytes:
    """Text -> WAV bytes."""
    if language not in GNANI_LANGS:
        raise GnaniError(f"Gnani does not support {language} (Odia is not available)")
    key = _key("GNANI_TTS_API_KEY")
    clean = re.sub(r"[<>]", " ", text or "").strip()       # < > would be read as audio tags
    if not clean:
        raise GnaniError("empty text")
    return _join_wavs([_synthesize(c, language, key) for c in _chunks(clean)])