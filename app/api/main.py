import base64
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db, init_db, SessionLocal
from app.db.models import Shop, Customer, Item, InventoryMovement
from app.languages import SUPPORTED, normalize_language
from app.tools.ledger_tools import get_balance
from app.agent.pipeline import handle, SESSIONS
from app.voice.stt import transcribe
from app.voice.tts import speak
from app.voice.templates import say
from app.api.customers import router as customers_router
from app.api.collect import router as collect_router
from app.api.inbox import router as inbox_router
from app.api.insights import router as insights_router
from app.api.dashboard_api import router as dashboard_router
from app.api.inventory import router as inventory_router
from app.api.wakeword import router as wakeword_router

app = FastAPI(title="Arthiq")
app.include_router(customers_router)
app.include_router(collect_router)
app.include_router(inbox_router)
app.include_router(insights_router)
app.include_router(dashboard_router)
app.include_router(inventory_router)
app.include_router(wakeword_router)

# Ensure schema/migrations exist before the first database query.
init_db()
with SessionLocal() as db:
    if not db.get(Shop, 1):
        db.add(Shop(id=1, name="Demo Shop", language="hi-IN"))
        db.commit()


@app.get("/")
def home():
    return FileResponse("web/index.html")


@app.get("/languages")
def languages():
    return [{"code": l.code, "name": l.name, "native": l.native} for l in SUPPORTED.values()]


class LanguageIn(BaseModel):
    shop_id: int = 1
    language: str


@app.post("/shop/language")
def set_language(body: LanguageIn, db: Session = Depends(get_db)):
    language = normalize_language(body.language)
    if body.language not in SUPPORTED:
        raise HTTPException(400, "Unsupported language")
    shop = db.get(Shop, body.shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    shop.language = language
    db.commit()
    return {"shop_id": shop.id, "language": shop.language}


@app.get("/ledger")
def ledger(shop_id: int = 1, db: Session = Depends(get_db)):
    rows = db.query(Customer).filter_by(shop_id=shop_id).all()
    return [{"id": c.id, "name": c.name, "language": normalize_language(c.preferred_language),
             "balance": get_balance(db, c.id), "credit_limit": c.credit_limit} for c in rows]


@app.get("/stock")
def stock(shop_id: int = 1, db: Session = Depends(get_db)):
    rows = db.query(Item).filter_by(shop_id=shop_id).order_by(Item.name).all()
    return [{"id": i.id, "name": i.name, "unit": i.unit, "price": i.price,
             "cost_price": i.cost_price, "sku": i.sku, "category": i.category,
             "stock_qty": i.stock_qty, "reorder_level": i.reorder_level,
             "low_stock": float(i.stock_qty or 0) <= float(i.reorder_level or 0)} for i in rows]


@app.get("/stock/movements")
def stock_movements(shop_id: int = 1, limit: int = 20, db: Session = Depends(get_db)):
    limit = max(1, min(int(limit), 100))
    rows = db.scalars(select(InventoryMovement).where(
        InventoryMovement.shop_id == shop_id
    ).order_by(InventoryMovement.timestamp.desc(), InventoryMovement.id.desc()).limit(limit)).all()
    result = []
    for movement in rows:
        item = db.get(Item, movement.item_id)
        result.append({"id": movement.id, "item": item.name if item else "Unknown item",
                       "movement_type": movement.movement_type, "quantity": movement.quantity,
                       "unit": movement.unit, "previous_stock": movement.previous_stock,
                       "new_stock": movement.new_stock, "source": movement.source,
                       "timestamp": movement.timestamp.isoformat() if movement.timestamp else None})
    return result


def _turn(db, shop_id: int, transcript: str):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    lang = normalize_language(shop.language)
    if not transcript.strip():
        result = {"state": "error", "reply": say(lang, "err_generic")}
    else:
        result = handle(db, shop_id, transcript)
    audio = None
    try:
        audio = base64.b64encode(speak(result["reply"], lang)).decode()
    except Exception as exc:  # Text remains available when TTS is unavailable.
        print("TTS failed:", exc)
    return {"transcript": transcript, **result, "audio_b64": audio, "language": lang}


@app.post("/voice/turn")
def voice_turn(audio: UploadFile = File(...), shop_id: int = Form(1),
               db: Session = Depends(get_db)):
    try:
        shop = db.get(Shop, shop_id)
        transcript, detected = transcribe(audio.file.read(), normalize_language(shop.language) if shop else None)
    except Exception as exc:
        raise HTTPException(502, f"Speech-to-text failed: {exc}") from exc
    return _turn(db, shop_id, transcript) | {"detected_language": detected}


class TextIn(BaseModel):
    shop_id: int = 1
    text: str


@app.post("/text/turn")
def text_turn(body: TextIn, db: Session = Depends(get_db)):
    return _turn(db, body.shop_id, body.text)


@app.post("/session/reset")
def reset(shop_id: int = 1):
    SESSIONS.pop(shop_id, None)
    return {"ok": True}
