import os
import uuid

from app.agent.llm import _get_client
from app.voice import gnani
from app.voice.provider import provider_for, fallback_enabled


def _sarvam_transcribe(wav_bytes: bytes):
    os.makedirs("data", exist_ok=True)
    path = f"data/up_{uuid.uuid4().hex}.wav"
    with open(path, "wb") as f:
        f.write(wav_bytes)
    try:
        with open(path, "rb") as f:
            r = _get_client().speech_to_text.transcribe(
                file=f, model="saaras:v4", mode="codemix")
        return (r.transcript or "").strip(), getattr(r, "language_code", None)
    finally:
        os.remove(path)


def transcribe(wav_bytes: bytes, language=None):
    """WAV bytes -> (transcript, detected language). Pass the shop language when known."""
    if provider_for(language) == "gnani":
        try:
            return gnani.stt(wav_bytes, language)
        except gnani.GnaniError as e:
            if not fallback_enabled():
                raise
            print(f"[speech] Gnani STT failed ({e}); using Sarvam for this request")
    return _sarvam_transcribe(wav_bytes)