"""CSV product-catalogue import with preview, validation and one-time commit.

Stock changes are delegated to the project's purchases service, which uses the
unified stock movement engine. Existing on-hand quantities are never overwritten.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from app.db.models import InventoryImportDraft, Item, Supplier
from app.engine.products import register_product
from app.engine.purchases import record_purchase
from app.engine.units import canon_unit

MAX_CSV_BYTES = 5 * 1024 * 1024
# Accept both the full catalogue template and the compact stock-upload format:
# name,unit,price,cost_price,stock_qty,reorder_level.
REQUIRED_NAME_HEADERS = {"item_name", "name"}
REQUIRED_SELLING_HEADERS = {"selling_price", "price"}


def _field(row: dict, *names: str):
    """Return the first non-empty value among compatible CSV column names."""
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


class CatalogueImportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value).casefold())


def _number(value: Any, label: str, line: int, *, required=False, minimum=0):
    raw = _clean(value).replace(",", "").replace("₹", "").replace("Rs.", "").replace("rs", "")
    if not raw:
        if required:
            raise ValueError(f"Row {line}: {label} is required")
        return None
    try:
        number = float(raw)
    except ValueError as exc:
        raise ValueError(f"Row {line}: {label} must be a number") from exc
    if number < minimum:
        raise ValueError(f"Row {line}: {label} cannot be below {minimum}")
    return number


def parse_catalogue_csv(content: bytes, db, shop_id: int) -> dict:
    if len(content) > MAX_CSV_BYTES:
        raise CatalogueImportError("file_too_large", "CSV must be 5 MB or smaller", 413)
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogueImportError("encoding", "CSV must be UTF-8 encoded") from exc
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise CatalogueImportError("empty_csv", "CSV is empty or has no header")
    headers = {str(h).strip().lower() for h in reader.fieldnames if h}
    missing = []
    if not (headers & REQUIRED_NAME_HEADERS):
        missing.append("name (or item_name)")
    if "unit" not in headers:
        missing.append("unit")
    if not (headers & REQUIRED_SELLING_HEADERS):
        missing.append("price (or selling_price)")
    if missing:
        raise CatalogueImportError("missing_columns", "Missing columns: " + ", ".join(missing))

    items = db.scalars(select(Item).where(Item.shop_id == shop_id, Item.status != "deleted")).all()
    by_sku = {_norm(i.sku): i for i in items if _norm(i.sku)}
    by_name = {}
    for item in items:
        for term in [item.name, *(item.aliases or [])]:
            by_name.setdefault(_norm(term), item)

    seen_skus, seen_names = set(), set()
    rows, errors = [], []
    for line, raw in enumerate(reader, start=2):
        row = {str(k).strip().lower(): _clean(v) for k, v in (raw or {}).items() if k}
        if not any(row.values()):
            continue
        try:
            name = _field(row, "item_name", "name") or ""
            unit_raw = row.get("unit", "").strip().lower()
            if not name:
                raise ValueError(f"Row {line}: item_name is required")
            if not unit_raw:
                raise ValueError(f"Row {line}: unit is required")
            unit = canon_unit(unit_raw)
            if not unit:
                raise ValueError(f"Row {line}: unsupported unit '{unit_raw}'. Use kg, g, litre, ml, piece, packet, bottle, box, bag, jar or dozen.")
            sku = row.get("sku") or None
            sku_key, name_key = _norm(sku), _norm(name)
            if sku_key and sku_key in seen_skus:
                raise ValueError(f"Row {line}: duplicate SKU '{sku}' in this CSV")
            if name_key in seen_names:
                raise ValueError(f"Row {line}: duplicate item_name '{name}' in this CSV")
            if sku_key:
                seen_skus.add(sku_key)
            seen_names.add(name_key)

            selling = _number(_field(row, "selling_price", "price"), "selling_price/price", line, required=True, minimum=0.01)
            purchase = _number(_field(row, "purchase_price", "cost_price"), "purchase_price/cost_price", line, minimum=0)
            # In the compact six-column format, stock_qty is the quantity being
            # received in this import, not a replacement for on-hand stock.
            # record_purchase() applies it as an additive STOCK_IN movement.
            quantity = _number(_field(row, "quantity", "stock_qty"), "quantity/stock_qty", line, minimum=0) or 0.0
            reorder = _number(row.get("reorder_level"), "reorder_level", line, minimum=0)
            expiry = row.get("expiry_date") or None
            if expiry:
                try:
                    date.fromisoformat(expiry)
                except ValueError as exc:
                    raise ValueError(f"Row {line}: expiry_date must use YYYY-MM-DD") from exc

            item = by_sku.get(sku_key) if sku_key else None
            if item is None:
                item = by_name.get(name_key)
            if item and _norm(item.unit) != _norm(unit):
                raise ValueError(f"Row {line}: unit mismatch for {name}; catalogue uses '{item.unit}', CSV uses '{unit}'")
            if item and sku and item.sku and _norm(item.sku) != sku_key:
                raise ValueError(f"Row {line}: {name} already has SKU '{item.sku}', not '{sku}'")
            if not item and sku_key and sku_key in by_sku:
                raise ValueError(f"Row {line}: SKU '{sku}' is already assigned")
            aliases = list(dict.fromkeys(x.strip() for x in (row.get("aliases") or "").split("|") if x.strip()))
            rows.append({
                "row_num": line, "sku": sku, "item_name": name,
                "category": row.get("category") or "General", "unit": unit,
                "pack_size": row.get("pack_size") or None, "quantity": float(quantity),
                "purchase_price": int(round(purchase)) if purchase is not None else None,
                "selling_price": int(round(selling)),
                "reorder_level": float(reorder) if reorder is not None else None,
                "supplier_name": row.get("supplier_name") or None,
                "expiry_date": expiry, "aliases": aliases,
                "matched_item_id": item.id if item else None,
                "current_stock": float(item.stock_qty or 0) if item else 0.0,
                "projected_stock": round(float(item.stock_qty or 0) + float(quantity), 4) if item else float(quantity),
                "match_type": "SKU" if item and sku_key and _norm(item.sku) == sku_key else ("name" if item else "new"),
            })
        except ValueError as exc:
            errors.append(str(exc))
    if not rows and not errors:
        errors.append("CSV contains no product rows")
    return {"rows": rows, "errors": errors}


def save_preview(db, shop_id: int, parsed: dict) -> dict:
    token = uuid.uuid4().hex
    draft = InventoryImportDraft(token=token, shop_id=shop_id, rows_json=parsed["rows"],
                                 errors_json=parsed["errors"], status="PENDING")
    db.add(draft)
    db.commit()
    public_rows = [{k: v for k, v in row.items() if k != "aliases"} for row in parsed["rows"]]
    return {
        "token": token, "rows": public_rows, "errors": parsed["errors"],
        "can_commit": bool(public_rows) and not parsed["errors"],
        "new_count": sum(r["match_type"] == "new" for r in public_rows),
        "update_count": sum(r["match_type"] != "new" for r in public_rows),
        "stock_in_count": sum(r["quantity"] > 0 for r in public_rows),
    }


def commit_preview(db, shop_id: int, token: str, update_prices: bool = True) -> dict:
    draft = db.get(InventoryImportDraft, token)
    if not draft or draft.shop_id != shop_id:
        raise CatalogueImportError("preview_not_found", "Import preview not found. Upload the CSV again.", 404)
    if draft.status != "PENDING":
        raise CatalogueImportError("preview_used", "This preview has already been applied. Upload it again for another import.", 409)
    if draft.errors_json:
        raise CatalogueImportError("validation_failed", "Fix CSV errors before applying the import.", 422)

    current = db.scalars(select(Item).where(Item.shop_id == shop_id, Item.status != "deleted")).all()
    by_id = {i.id: i for i in current}
    by_sku = {_norm(i.sku): i for i in current if _norm(i.sku)}
    by_name = {}
    for item in current:
        for term in [item.name, *(item.aliases or [])]:
            by_name.setdefault(_norm(term), item)

    prepared = []
    for row in draft.rows_json:
        item = by_id.get(row.get("matched_item_id"))
        if item is None and row.get("sku"):
            item = by_sku.get(_norm(row["sku"]))
        if item is None:
            item = by_name.get(_norm(row["item_name"]))
        if item and _norm(item.unit) != _norm(row["unit"]):
            raise CatalogueImportError("unit_mismatch", f"{row['item_name']}: unit changed after preview; upload again.", 409)
        if item and row.get("sku") and item.sku and _norm(item.sku) != _norm(row["sku"]):
            raise CatalogueImportError("sku_conflict", f"{row['item_name']}: SKU changed after preview; upload again.", 409)
        prepared.append((row, item))

    # Supplier is linked only when all received stock lines name the same supplier.
    stock_rows = [(r, i) for r, i in prepared if float(r.get("quantity") or 0) > 0]
    supplier_names = {r.get("supplier_name") for r, _ in stock_rows if r.get("supplier_name")}
    supplier_id = None
    if len(supplier_names) == 1:
        supplier_name = next(iter(supplier_names))
        supplier = db.scalar(select(Supplier).where(
            Supplier.shop_id == shop_id, Supplier.name.ilike(supplier_name), Supplier.status == "active"
        ))
        if supplier is None:
            supplier = Supplier(shop_id=shop_id, name=supplier_name, status="active")
            db.add(supplier)
            db.flush()
        supplier_id = supplier.id

    created = updated = 0
    purchase_lines = []
    for row, item in prepared:
        expiry = date.fromisoformat(row["expiry_date"]) if row.get("expiry_date") else None
        if item is None:
            item = register_product(
                db, shop_id, row["item_name"], row["unit"], row["selling_price"],
                cost_price=row.get("purchase_price") or 0, sku=row.get("sku"),
                category=row.get("category") or "General", pack_size=row.get("pack_size"),
                stock_qty=0, reorder_level=row.get("reorder_level") if row.get("reorder_level") is not None else 5,
                aliases=row.get("aliases") or [], expiry_date=expiry, commit=False,
            )
            created += 1
        else:
            item.category = row.get("category") or item.category or "General"
            item.pack_size = row.get("pack_size") or item.pack_size
            item.aliases = list(dict.fromkeys((item.aliases or []) + (row.get("aliases") or [])))
            if row.get("sku"):
                item.sku = row["sku"]
            if row.get("reorder_level") is not None:
                item.reorder_level = row["reorder_level"]
            if expiry:
                item.expiry_date = expiry
            if update_prices:
                item.price = row["selling_price"]
                if row.get("purchase_price") is not None:
                    item.cost_price = row["purchase_price"]
            updated += 1

        qty = float(row.get("quantity") or 0)
        if qty > 0:
            purchase_lines.append({
                "item_id": item.id, "quantity": qty, "unit": item.unit,
                "purchase_price": row.get("purchase_price") if row.get("purchase_price") is not None else item.cost_price,
                "expiry_date": expiry,
            })

    # Mark pending before record_purchase; its commit includes this status atomically.
    draft.status = "APPLIED"
    purchase_result = None
    if purchase_lines:
        purchase_result = record_purchase(
            db, shop_id, purchase_lines, supplier_id=supplier_id,
            idempotency_key=f"csv_{token}"[:64], notes=f"Catalogue CSV import {token}",
        )
    else:
        db.commit()

    return {
        "created": created, "updated": updated,
        "stock_movements": len(purchase_lines),
        "purchase_id": purchase_result["purchase_id"] if purchase_result else None,
        "message": f"Imported {created + updated} catalogue items; stock received for {len(purchase_lines)} items. Existing stock quantities were preserved unless CSV quantity was provided.",
    }
