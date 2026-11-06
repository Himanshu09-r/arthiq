"""Unified Inventory Movement Engine.
Enforces transactional consistency, negative stock protection,
movement type audits, and idempotency across all stock mutations.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import select

from app.db.models import InventoryMovement, Item, Shop, ActionAudit


class MovementError(Exception):
    def __init__(self, code: str, message: str, **info):
        super().__init__(message)
        self.code = code
        self.message = message
        self.info = info


VALID_MOVEMENT_TYPES = {
    "STOCK_IN",
    "STOCK_OUT",
    "RETURN_IN",
    "RETURN_OUT",
    "MANUAL_ADJUSTMENT",
    "REVERSAL"
}


def record_movement(
    db,
    shop_id: int,
    item_id: int,
    movement_type: str,
    quantity: float,
    unit: Optional[str] = None,
    source: str = "manual",
    purchase_price: Optional[int] = None,
    reference_tx_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    audit_info: Optional[dict] = None,
    allow_negative: bool = False,
    actor: str = "system"
) -> InventoryMovement:
    """Execute and record an inventory movement atomically.
    Guarantees that stock quantity and movement records never drift."""
    movement_type = (movement_type or "").upper().strip()
    if movement_type not in VALID_MOVEMENT_TYPES:
        raise MovementError("invalid_movement_type", f"Unknown movement type '{movement_type}'")

    # Idempotency check: if key already exists, return existing record
    if idempotency_key:
        existing = db.scalar(select(InventoryMovement).where(
            InventoryMovement.shop_id == shop_id,
            InventoryMovement.idempotency_key == idempotency_key
        ))
        if existing:
            return existing

    item = db.get(Item, item_id)
    if not item or item.shop_id != shop_id:
        raise MovementError("item_not_found", f"Item {item_id} not found in shop {shop_id}")

    qty = float(quantity)
    if qty <= 0 and movement_type != "MANUAL_ADJUSTMENT":
        raise MovementError("bad_quantity", "Quantity must be greater than zero")

    prev_stock = float(item.stock_qty or 0.0)
    info = dict(audit_info or {})

    # Calculate new stock based on movement type
    if movement_type in ("STOCK_IN", "RETURN_IN"):
        new_stock = round(prev_stock + qty, 4)
    elif movement_type in ("STOCK_OUT", "RETURN_OUT"):
        new_stock = round(prev_stock - qty, 4)
    elif movement_type == "MANUAL_ADJUSTMENT":
        mode = info.get("mode", "delta")
        if mode == "set":
            new_stock = round(qty, 4)
            qty = abs(round(new_stock - prev_stock, 4))
        else:
            new_stock = round(prev_stock + qty, 4)
            qty = abs(qty)
    elif movement_type == "REVERSAL":
        # Check original direction from audit_info
        orig_dir = info.get("original_type", "STOCK_OUT")
        if orig_dir in ("STOCK_OUT", "RETURN_OUT"):
            new_stock = round(prev_stock + qty, 4)
        else:
            new_stock = round(prev_stock - qty, 4)
    else:
        raise MovementError("invalid_movement_type", f"Unsupported type {movement_type}")

    # Enforce negative stock guardrail
    if new_stock < 0 and not allow_negative:
        raise MovementError(
            "negative_stock",
            f"Cannot complete {movement_type} of {qty} {item.unit} for '{item.name}'. "
            f"Current stock is {prev_stock}, operation would result in {new_stock}.",
            current_stock=prev_stock,
            attempted_change=qty,
            resulting_stock=new_stock
        )

    now = datetime.now()
    item.stock_qty = new_stock
    if movement_type in ("STOCK_OUT", "RETURN_OUT"):
        item.last_sold_at = now

    movement = InventoryMovement(
        shop_id=shop_id,
        item_id=item.id,
        movement_type=movement_type,
        quantity=qty,
        previous_stock=prev_stock,
        new_stock=new_stock,
        unit=unit or item.unit,
        purchase_price=purchase_price if purchase_price is not None else item.cost_price,
        reference_tx_id=str(reference_tx_id) if reference_tx_id is not None else None,
        source=source,
        idempotency_key=idempotency_key,
        audit_info=info,
        timestamp=now
    )
    db.add(movement)
    db.flush()

    db.add(ActionAudit(
        shop_id=shop_id,
        actor=actor,
        tool="inventory_movement",
        arguments={
            "movement_id": movement.id,
            "item_id": item.id,
            "item_name": item.name,
            "type": movement_type,
            "qty": qty,
            "previous_stock": prev_stock,
            "new_stock": new_stock,
            "source": source
        },
        rule_decision="allowed",
        timestamp=now
    ))
    return movement


def list_movements(
    db,
    shop_id: int,
    item_id: Optional[int] = None,
    movement_type: Optional[str] = None,
    source: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 50
) -> list[InventoryMovement]:
    """Query inventory movement history with filtering."""
    stmt = select(InventoryMovement).where(InventoryMovement.shop_id == shop_id)
    if item_id:
        stmt = stmt.where(InventoryMovement.item_id == item_id)
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type.upper())
    if source:
        stmt = stmt.where(InventoryMovement.source == source)
    if since:
        stmt = stmt.where(InventoryMovement.timestamp >= since)

    return list(db.scalars(stmt.order_by(InventoryMovement.id.desc()).limit(limit)).all())

