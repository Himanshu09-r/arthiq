import base64

from app.agent.llm import _get_client
from app.languages import get_language
from app.voice import gnani
from app.voice.provider import provider_for, fallback_enabled


def _sarvam_speak(text: str, lang: str) -> bytes:
    l = get_language(lang)
    r = _get_client().text_to_speech.convert(
        text=text, language_code=l.code, model="bulbul:v3", speaker=l.speaker)
    return base64.b64decode(r.audios[0])


def speak(text: str, lang: str) -> bytes:
    """Text -> WAV bytes in the given language."""
    if provider_for(lang) == "gnani":
        try:
            return gnani.tts(text, lang)
        except gnani.GnaniError as e:
            if not fallback_enabled():
                raise
            print(f"[speech] Gnani TTS failed ({e}); using Sarvam for this request")
    return _sarvam_speak(text, lang)