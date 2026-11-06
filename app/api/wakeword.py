"""Hands-free wake-word endpoints for ARTHIQ.

The browser performs local voice-activity detection and uploads only short speech clips.
This module transcribes each clip with the same configured provider as the main voice flow.
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.models import Shop
from app.db.session import get_db
from app.languages import normalize_language
from app.voice.stt import transcribe
from app.voice.tts import speak
from app.voice.wake import detect

router = APIRouter()
WEB = Path(__file__).resolve().parents[2] / "web"
WAKE_PHRASE = "Suno ARTHIQ / ARTHIQ Suno / Hey ARTHIQ"
log = logging.getLogger(__name__)


def _turn(db: Session, shop_id: int, text: str) -> dict:
    # Late import avoids the app.main -> router -> app.main import cycle.
    from app.api.main import _turn as main_turn
    return main_turn(db, shop_id, text)


def _shop(db: Session, shop_id: int) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    return shop


def _transcribe(audio: UploadFile, shop: Shop):
    try:
        return transcribe(audio.file.read(), normalize_language(shop.language))
    except Exception as exc:
        log.exception("Speech recognition failed in hands-free endpoint")
        raise HTTPException(502, f"Speech recognition failed: {exc}") from exc


@router.get("/wakeword.js")
def wakeword_js():
    return FileResponse(WEB / "wakeword.js", media_type="application/javascript")


@router.get("/voice/status")
def voice_status():
    return {"wake_phrase": WAKE_PHRASE, "enabled_by_user": True,
            "note": "Wake detection is performed locally in the open browser tab."}


@router.post("/voice/wake")
def voice_wake(audio: UploadFile = File(...), shop_id: int = Form(1), db: Session = Depends(get_db)):
    """Transcribe a short utterance and process it only when a wake phrase is detected."""
    shop = _shop(db, shop_id)
    heard, detected_language = _transcribe(audio, shop)
    matched, command = detect(heard)
    if not matched:
        return {"wake": False, "heard": heard, "turn": None,
                "detected_language": detected_language}

    if command.strip():
        turn = _turn(db, shop_id, command.strip())
        return {"wake": True, "heard": heard, "command": command.strip(),
                "turn": turn, "detected_language": detected_language}

    # Wake phrase alone: acknowledge and leave the browser in command-listening mode.
    lang = normalize_language(shop.language)
    acknowledgement = "हाँ जी, बोलिए।" if lang != "en-IN" else "Yes, I’m listening."
    audio_b64 = None
    try:
        audio_b64 = base64.b64encode(speak(acknowledgement, lang)).decode("ascii")
    except Exception:
        log.exception("Could not synthesize wake acknowledgement")
    return {"wake": True, "heard": heard, "command": "", "turn": None,
            "ack_reply": acknowledgement, "ack_audio_b64": audio_b64,
            "detected_language": detected_language}


@router.post("/voice/command")
def voice_command(audio: UploadFile = File(...), shop_id: int = Form(1), db: Session = Depends(get_db)):
    """Handle the command/follow-up utterance after the wake word."""
    shop = _shop(db, shop_id)
    t0 = time.perf_counter()
    transcript, detected_language = _transcribe(audio, shop)
    result = _turn(db, shop_id, transcript)
    result["detected_language"] = detected_language
    result["processing_ms"] = int((time.perf_counter() - t0) * 1000)
    return result
