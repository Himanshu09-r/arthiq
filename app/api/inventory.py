"""Inventory catalogue, movement history and safe CSV import routes."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InventoryMovement, Item, Shop
from app.db.session import get_db
from app.engine.catalogue_import import (
    CatalogueImportError, commit_preview, parse_catalogue_csv, save_preview,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])
ROOT = Path(__file__).resolve().parents[2]


def _raise_import_error(exc: CatalogueImportError):
    raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.get("/page")
def inventory_page():
    return FileResponse(ROOT / "web" / "inventory.html")


@router.get("/items")
def inventory_items(shop_id: int = 1, q: str = "", db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    stmt = select(Item).where(Item.shop_id == shop_id, Item.status != "deleted")
    rows = db.scalars(stmt.order_by(Item.category, Item.name)).all()
    needle = q.strip().casefold()
    result = []
    for item in rows:
        if needle and needle not in item.name.casefold() and not any(needle in str(a).casefold() for a in (item.aliases or [])):
            continue
        result.append({
            "id": item.id, "sku": item.sku, "name": item.name,
            "category": item.category or "General", "unit": item.unit,
            "pack_size": item.pack_size, "purchase_price": item.cost_price or 0,
            "selling_price": item.price, "stock_qty": float(item.stock_qty or 0),
            "reorder_level": float(item.reorder_level or 0),
            "low_stock": float(item.stock_qty or 0) <= float(item.reorder_level or 0),
            "aliases": item.aliases or [],
        })
    return result


@router.get("/movements")
def inventory_movements(shop_id: int = 1, limit: int = 50, db: Session = Depends(get_db)):
    if not db.get(Shop, shop_id):
        raise HTTPException(404, "Shop not found")
    limit = max(1, min(int(limit), 200))
    rows = db.scalars(select(InventoryMovement).where(
        InventoryMovement.shop_id == shop_id
    ).order_by(InventoryMovement.timestamp.desc(), InventoryMovement.id.desc()).limit(limit)).all()
    out = []
    for movement in rows:
        item = db.get(Item, movement.item_id)
        out.append({
            "id": movement.id, "item": item.name if item else "Deleted item",
            "movement_type": movement.movement_type, "quantity": movement.quantity,
            "unit": movement.unit, "previous_stock": movement.previous_stock,
            "new_stock": movement.new_stock, "source": movement.source,
            "timestamp": movement.timestamp.isoformat() if movement.timestamp else None,
        })
    return out


@router.post("/import/preview")
async def inventory_import_preview(
    file: UploadFile = File(...), shop_id: int = Form(1), db: Session = Depends(get_db)
):
    if not db.get(Shop, shop_id):
        raise HTTPException(404, "Shop not found")
    if not file.filename or not file.filename.casefold().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file")
    content = await file.read(5 * 1024 * 1024 + 1)
    try:
        parsed = parse_catalogue_csv(content, db, shop_id)
        return save_preview(db, shop_id, parsed)
    except CatalogueImportError as exc:
        _raise_import_error(exc)


class ImportCommitIn(BaseModel):
    shop_id: int = 1
    token: str
    update_prices: bool = True


@router.post("/import/commit")
def inventory_import_commit(body: ImportCommitIn, db: Session = Depends(get_db)):
    try:
        return commit_preview(db, body.shop_id, body.token, body.update_prices)
    except CatalogueImportError as exc:
        _raise_import_error(exc)
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"Import failed safely: {type(exc).__name__}: {exc}") from exc


@router.get("/catalogue.csv")
def inventory_catalogue_csv():
    path = ROOT / "data" / "arthiq_item_price_list.csv"
    if not path.exists():
        raise HTTPException(404, "Product catalogue CSV not found")
    return FileResponse(path, media_type="text/csv", filename="arthiq_item_price_list.csv")


@router.get("/stock-import-template.csv")
def inventory_stock_template():
    path = ROOT / "data" / "arthiq_stock_import_template.csv"
    if not path.exists():
        raise HTTPException(404, "Stock import template CSV not found")
    return FileResponse(path, media_type="text/csv", filename="arthiq_stock_import_template.csv")
