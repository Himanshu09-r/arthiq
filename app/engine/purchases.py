"""Stock Purchase & Supplier Management Service.
Handles supplier registration, stock purchase recording, idempotent inventory increments,
and line-item cost tracking.
"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import select

from app.db.models import Purchase, PurchaseItem, Supplier, Item, Shop, ActionAudit
from app.engine.stock_movement import record_movement


class PurchaseError(Exception):
    def __init__(self, code: str, message: str, **info):
        super().__init__(message)
        self.code = code
        self.message = message
        self.info = info


def register_supplier(
    db,
    shop_id: int,
    name: str,
    phone: Optional[str] = None,
    contact_person: Optional[str] = None,
    locality: Optional[str] = None,
    address: Optional[str] = None,
    gstin: Optional[str] = None
) -> Supplier:
    """Register or retrieve an existing supplier profile."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise PurchaseError("invalid_name", "Supplier name cannot be empty")

    clean_phone = phone.strip() if phone else None
    if clean_phone:
        existing = db.scalar(select(Supplier).where(Supplier.shop_id == shop_id, Supplier.phone == clean_phone))
        if existing:
            return existing

    now = datetime.now()
    sup = Supplier(
        shop_id=shop_id,
        name=clean_name,
        phone=clean_phone,
        contact_person=contact_person.strip() if contact_person else None,
        locality=locality.strip() if locality else None,
        address=address.strip() if address else None,
        gstin=gstin.strip().upper() if gstin else None,
        status="active",
        created_at=now,
        updated_at=now
    )
    db.add(sup)
    db.commit()
    return sup


def list_suppliers(db, shop_id: int, limit: int = 50) -> list[Supplier]:
    """List all active suppliers for a shop."""
    return list(db.scalars(
        select(Supplier).where(Supplier.shop_id == shop_id, Supplier.status == "active")
        .order_by(Supplier.name).limit(limit)
    ).all())


def record_purchase(
    db,
    shop_id: int,
    lines: list[dict],
    supplier_id: Optional[int] = None,
    invoice_ref: Optional[str] = None,
    purchase_date: Optional[date] = None,
    idempotency_key: Optional[str] = None,
    notes: Optional[str] = None,
    payment_status: str = "UNPAID",
    paid_amount: int = 0
) -> dict:
    """Record a purchase order, line items, and stock increments idempotently.
    Retrying with the same idempotency_key returns the existing purchase without re-incrementing stock."""
    shop = db.get(Shop, shop_id)
    if not shop:
        raise PurchaseError("shop_not_found", f"Shop {shop_id} does not exist")

    if not lines:
        raise PurchaseError("no_items", "Purchase must contain at least one product line")

    # Idempotency check: if already completed, replay result
    if idempotency_key:
        done = db.scalar(select(Purchase).where(
            Purchase.shop_id == shop_id,
            Purchase.idempotency_key == idempotency_key
        ))
        if done:
            items = db.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == done.id)).all()
            return {
                "purchase_id": done.id,
                "total_amount": done.total_amount,
                "invoice_ref": done.invoice_ref,
                "lines_count": len(items),
                "replay": True
            }

    if supplier_id:
        supplier = db.get(Supplier, supplier_id)
        if not supplier or supplier.shop_id != shop_id:
            supplier_id = None

    now = datetime.now()
    p_date = purchase_date or date.today()

    # Pre-validate all lines
    validated = []
    total_amount = 0
    for idx, ln in enumerate(lines):
        item_id = ln.get("item_id")
        item = db.get(Item, item_id)
        if not item or item.shop_id != shop_id:
            raise PurchaseError("item_not_found", f"Item ID {item_id} not found in shop {shop_id}")

        qty = float(ln.get("quantity") or ln.get("qty") or 0)
        if qty <= 0:
            raise PurchaseError("bad_quantity", f"Quantity for item '{item.name}' must be positive")

        unit_cost = int(ln.get("purchase_price") if ln.get("purchase_price") is not None else item.cost_price)
        if unit_cost < 0:
            raise PurchaseError("bad_price", f"Purchase price cannot be negative for '{item.name}'")

        line_total = round(unit_cost * qty)
        total_amount += line_total
        unit = ln.get("unit") or item.unit
        expiry = ln.get("expiry_date")
        batch = ln.get("batch_number")

        validated.append({
            "item": item,
            "qty": qty,
            "unit": unit,
            "purchase_price": unit_cost,
            "line_total": line_total,
            "expiry_date": expiry,
            "batch_number": batch
        })

    # Create Purchase Header
    purchase = Purchase(
        shop_id=shop_id,
        supplier_id=supplier_id,
        invoice_ref=invoice_ref.strip() if invoice_ref else None,
        purchase_date=p_date,
        total_amount=total_amount,
        status="RECEIVED",
        payment_status=payment_status,
        paid_amount=max(0, int(paid_amount)),
        idempotency_key=idempotency_key,
        notes=notes,
        created_at=now
    )
    db.add(purchase)
    db.flush()

    # Record purchase items and stock movements
    items_created = []
    for idx, v in enumerate(validated):
        item = v["item"]
        qty = v["qty"]
        price = v["purchase_price"]

        # 1. Increment inventory through unified movement engine
        mov_key = f"purch_{purchase.id}_{item.id}_{idx}" if idempotency_key else None
        movement = record_movement(
            db=db,
            shop_id=shop_id,
            item_id=item.id,
            movement_type="STOCK_IN",
            quantity=qty,
            unit=v["unit"],
            source="purchase",
            purchase_price=price,
            reference_tx_id=str(purchase.id),
            idempotency_key=mov_key,
            audit_info={"purchase_id": purchase.id, "invoice_ref": purchase.invoice_ref},
            actor="shopkeeper"
        )

        # 2. Update item cost price if non-zero
        if price > 0:
            item.cost_price = price
        if v["expiry_date"]:
            item.expiry_date = v["expiry_date"]

        # 3. Create Purchase Item
        pi = PurchaseItem(
            purchase_id=purchase.id,
            item_id=item.id,
            quantity=qty,
            unit=v["unit"],
            purchase_price=price,
            line_total=v["line_total"],
            expiry_date=v["expiry_date"],
            batch_number=v["batch_number"],
            inventory_movement_id=movement.id,
            created_at=now
        )
        db.add(pi)
        items_created.append(pi)

    db.add(ActionAudit(
        shop_id=shop_id,
        actor="shopkeeper",
        tool="record_purchase",
        arguments={
            "purchase_id": purchase.id,
            "supplier_id": supplier_id,
            "total_amount": total_amount,
            "items_count": len(items_created),
            "invoice_ref": purchase.invoice_ref
        },
        rule_decision="allowed",
        timestamp=now
    ))
    db.commit()

    return {
        "purchase_id": purchase.id,
        "total_amount": total_amount,
        "invoice_ref": purchase.invoice_ref,
        "lines_count": len(items_created),
        "replay": False
    }


def list_purchases(
    db,
    shop_id: int,
    supplier_id: Optional[int] = None,
    limit: int = 50
) -> list[dict]:
    """Retrieve purchase history with supplier and line-item details."""
    stmt = select(Purchase).where(Purchase.shop_id == shop_id)
    if supplier_id:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)

    purchases = db.scalars(stmt.order_by(Purchase.id.desc()).limit(limit)).all()
    out = []
    for p in purchases:
        sup = db.get(Supplier, p.supplier_id) if p.supplier_id else None
        p_items = db.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == p.id)).all()
        lines = []
        for pi in p_items:
            it = db.get(Item, pi.item_id)
            lines.append({
                "item_id": pi.item_id,
                "name": it.name if it else "Unknown",
                "quantity": pi.quantity,
                "unit": pi.unit,
                "purchase_price": pi.purchase_price,
                "line_total": pi.line_total
            })
        out.append({
            "id": p.id,
            "supplier": sup.name if sup else None,
            "invoice_ref": p.invoice_ref,
            "purchase_date": p.purchase_date.isoformat(),
            "total_amount": p.total_amount,
            "payment_status": p.payment_status,
            "lines": lines
        })
    return out

