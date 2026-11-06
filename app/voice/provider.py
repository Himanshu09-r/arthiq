import os
from dotenv import load_dotenv

load_dotenv()

# Languages Gnani supports for BOTH speech-to-text and text-to-speech (no Odia)
GNANI_LANGS = frozenset({"hi-IN", "en-IN", "mr-IN", "gu-IN", "bn-IN",
                         "ta-IN", "te-IN", "kn-IN", "ml-IN", "pa-IN"})


def main_provider() -> str:
    return os.getenv("SPEECH_PROVIDER", "sarvam").strip().lower()


def fallback_enabled() -> bool:
    return (os.getenv("SPEECH_FALLBACK", "sarvam").strip().lower() == "sarvam"
            and bool(os.getenv("SARVAM_API_KEY", "").strip()))


def provider_for(lang=None) -> str:
    """Which provider handles this language: 'gnani' or 'sarvam'."""
    if main_provider() != "gnani":
        return "sarvam"
    if lang is None or lang in GNANI_LANGS:
        return "gnani"
    return "sarvam" if fallback_enabled() else "gnani"   # gnani then fails with a clear message