"""Dashboard API extensions for the premium ARTHIQ dashboard.
Provides aggregated KPIs, recent unified transaction stream, stock management (manual + CSV),
and quick actions, all backed by real database models and preserving append-only audit logs.
"""
import uuid
import hashlib
from datetime import datetime, date, time, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import (
    Shop, Customer, Item, LedgerEntry, SaleLog, CashState,
    Approval, ActionAudit, InventoryMovement
)
from app.engine import clock
from app.engine.ladder import outstanding
from app.tools import ledger_tools as L
from app.engine.stock_movement import record_movement

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _get_shop(db: Session, shop_id: int = 1) -> Shop:
    shop = db.get(Shop, shop_id)
    if not shop:
        shop = db.scalars(select(Shop).order_by(Shop.id)).first()
    if not shop:
        shop = Shop(id=1, name="Kirana Store", language="hi-IN")
        db.add(shop)
        db.commit()
        db.refresh(shop)
    return shop


@router.get("/overview")
def get_overview(shop_id: int = 1, db: Session = Depends(get_db)):
    """Fetch complete real-time dashboard KPIs, recent activity, and health indicators."""
    shop = _get_shop(db, shop_id)
    now = clock.now()
    start_today = datetime.combine(now.date(), time.min)
    end_today = start_today + timedelta(days=1)

    # 1. Today's metrics
    credit_entries_today = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop.id,
        LedgerEntry.type == "credit",
        LedgerEntry.created_at >= start_today,
        LedgerEntry.created_at < end_today
    )).all()
    credit_given_today = sum(e.amount for e in credit_entries_today)

    cash_sales_today = db.scalars(select(SaleLog).where(
        SaleLog.shop_id == shop.id,
        SaleLog.sold_at >= start_today,
        SaleLog.sold_at < end_today
    )).all()
    cash_today = sum(s.amount for s in cash_sales_today)

    today_sales = credit_given_today + cash_today

    payments_today = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop.id,
        LedgerEntry.type == "payment",
        LedgerEntry.created_at >= start_today,
        LedgerEntry.created_at < end_today
    )).all()
    today_collections = sum(e.amount for e in payments_today)

    # 2. Total outstanding credit across all active customers
    all_customers = db.scalars(select(Customer).where(Customer.shop_id == shop.id)).all()
    customer_map = {c.id: c.name for c in all_customers}
    total_outstanding = 0
    debtors = []
    for c in all_customers:
        bal = L.get_balance(db, c.id)
        if bal > 0:
            total_outstanding += bal
            debtors.append({
                "id": c.id,
                "name": c.name,
                "phone": c.phone or "—",
                "locality": c.locality or "Local",
                "balance": bal,
                "credit_limit": c.credit_limit,
                "trust_score": c.trust_score,
                "paused": c.paused
            })
    debtors.sort(key=lambda x: x["balance"], reverse=True)

    # 3. Cash position from CashState
    cs = db.get(CashState, shop.id)
    cash_position = cs.cash if (cs and cs.cash is not None) else 0

    # 4. Inventory counts
    items = db.scalars(select(Item).where(Item.shop_id == shop.id)).all()
    total_products = len(items)
    total_stock_units = sum(i.stock_qty for i in items)
    low_stock_items = []
    out_of_stock_count = 0
    for i in items:
        if i.stock_qty <= 0:
            out_of_stock_count += 1
        if i.stock_qty <= i.reorder_level:
            low_stock_items.append({
                "id": i.id,
                "name": i.name,
                "sku": i.sku or f"SKU-{i.id:03d}",
                "stock_qty": i.stock_qty,
                "reorder_level": i.reorder_level,
                "unit": i.unit,
                "price": i.price,
                "cost_price": i.cost_price or 0,
                "status": "out" if i.stock_qty <= 0 else "low"
            })
    low_stock_count = len(low_stock_items)

    # 5. Overdue credit entries
    overdue_entries = [
        e for e in db.scalars(select(LedgerEntry).where(
            LedgerEntry.shop_id == shop.id,
            LedgerEntry.type == "credit",
            LedgerEntry.status.in_(["OPEN", "PARTIAL"]),
            LedgerEntry.due_date.is_not(None),
            LedgerEntry.due_date < now.date()
        )).all() if outstanding(e) > 0
    ]
    overdue_amount = sum(outstanding(e) for e in overdue_entries)

    # 6. Unified recent transactions list
    recent_txs = []
    # Latest ledger entries
    ledger_recent = db.scalars(select(LedgerEntry).where(LedgerEntry.shop_id == shop.id)
                               .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
                               .limit(20)).all()
    for e in ledger_recent:
        items_summary = ", ".join(f"{l.get('qty', 0):g} {l.get('unit','')} {l.get('name','')}" for l in (e.items_json or []))
        if not items_summary:
            items_summary = "Direct Credit" if e.type == "credit" else "Payment Received"
        recent_txs.append({
            "id": f"TX-L{e.id}",
            "raw_id": e.id,
            "type": e.type,  # credit | payment
            "customer_id": e.customer_id,
            "customer_name": customer_map.get(e.customer_id, f"Customer #{e.customer_id}"),
            "description": items_summary,
            "amount": e.amount,
            "status": e.status,
            "created_at": e.created_at.isoformat(),
            "formatted_time": e.created_at.strftime("%d %b, %H:%M")
        })

    # Latest cash sales
    sales_recent = db.scalars(select(SaleLog).where(SaleLog.shop_id == shop.id)
                              .order_by(SaleLog.sold_at.desc(), SaleLog.id.desc())
                              .limit(10)).all()
    item_map = {i.id: i.name for i in items}
    for s in sales_recent:
        recent_txs.append({
            "id": f"TX-S{s.id}",
            "raw_id": s.id,
            "type": "sale",
            "customer_id": s.customer_id,
            "customer_name": customer_map.get(s.customer_id, "Cash Customer"),
            "description": f"{s.qty:g}x {item_map.get(s.item_id, 'Item')}",
            "amount": s.amount,
            "status": "COMPLETED",
            "created_at": s.sold_at.isoformat(),
            "formatted_time": s.sold_at.strftime("%d %b, %H:%M")
        })

    recent_txs.sort(key=lambda x: x["created_at"], reverse=True)
    recent_txs = recent_txs[:15]

    # 7. Unread counts
    pending_approvals = db.scalar(select(func.count(Approval.id)).where(
        Approval.shop_id == shop.id, Approval.status == "PENDING"
    )) or 0

    return {
        "shop": {
            "id": shop.id,
            "name": shop.name,
            "language": shop.language,
            "credit_days": shop.credit_days,
            "date": now.strftime("%A, %d %B %Y"),
            "iso_now": now.isoformat()
        },
        "kpis": {
            "today_sales": today_sales,
            "today_collections": today_collections,
            "today_credit_given": credit_given_today,
            "total_outstanding": total_outstanding,
            "overdue_amount": overdue_amount,
            "overdue_count": len({e.customer_id for e in overdue_entries}),
            "cash_position": cash_position,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "total_products": total_products,
            "total_stock_units": round(total_stock_units, 1)
        },
        "recent_transactions": recent_txs,
        "top_debtors": debtors[:6],
        "low_stock_items": low_stock_items[:6],
        "pending_approvals_count": pending_approvals
    }


class StockInRequest(BaseModel):
    shop_id: int = 1
    item_id: int
    quantity: float
    purchase_price: Optional[int] = None
    supplier_name: Optional[str] = None
    notes: Optional[str] = None


@router.post("/stock/in")
def stock_in_endpoint(body: StockInRequest, db: Session = Depends(get_db)):
    """Add stock to an existing item with proper InventoryMovement audit."""
    if body.quantity <= 0:
        raise HTTPException(400, "Quantity must be greater than zero")
    item = db.get(Item, body.item_id)
    if not item or item.shop_id != body.shop_id:
        raise HTTPException(404, "Product not found")

    req_id = uuid.uuid4().hex
    res = L.stock_in(db, body.shop_id, body.item_id, body.quantity, req_id)
    
    # Optionally update cost price if provided
    if body.purchase_price and body.purchase_price > 0:
        item.cost_price = body.purchase_price
        db.commit()

    return {
        "ok": True,
        "item_id": item.id,
        "name": item.name,
        "new_stock": item.stock_qty,
        "unit": item.unit
    }


class NewProductRequest(BaseModel):
    shop_id: int = 1
    name: str
    unit: str = "kg"
    price: int  # selling price
    cost_price: int = 0  # purchase price
    stock_qty: float = 0
    reorder_level: float = 5
    sku: Optional[str] = None
    category: Optional[str] = "General"
    pack_size: Optional[str] = None


@router.post("/stock/new")
def new_product_endpoint(body: NewProductRequest, db: Session = Depends(get_db)):
    """Create/update product metadata and record any received stock exactly once."""
    clean_name = (body.name or "").strip()
    if not clean_name:
        raise HTTPException(400, "Product name cannot be empty")
    if body.price < 0 or body.cost_price < 0 or body.stock_qty < 0:
        raise HTTPException(400, "Prices and stock quantity cannot be negative")
    if body.stock_qty > 100000:
        raise HTTPException(400, "Stock quantity is too large")
    shop = db.get(Shop, body.shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")

    sku = (body.sku or "").strip() or None
    existing = db.scalars(select(Item).where(
        Item.shop_id == body.shop_id,
        (Item.name.ilike(clean_name)) | (Item.sku == sku if sku else False)
    )).first()
    now = datetime.now()
    created = existing is None
    if existing:
        if body.unit and existing.unit and body.unit.strip().lower() != existing.unit.strip().lower():
            raise HTTPException(400, f"Unit mismatch: {existing.name} is tracked in {existing.unit}")
        item = existing
        item.price = body.price
        if body.cost_price > 0:
            item.cost_price = body.cost_price
        item.reorder_level = body.reorder_level
        if body.category:
            item.category = body.category
        if body.pack_size:
            item.pack_size = body.pack_size
        item.updated_at = now
    else:
        from app.engine.products import register_product, ProductError
        try:
            item = register_product(
                db, body.shop_id, clean_name, (body.unit or "piece").strip().lower(),
                body.price, cost_price=body.cost_price, sku=sku,
                category=body.category or "General", pack_size=body.pack_size,
                stock_qty=0, reorder_level=body.reorder_level,
                allow_existing=False, commit=False,
            )
        except ProductError as exc:
            db.rollback()
            raise HTTPException(400, str(exc)) from exc

    # record_movement is the single authority that increments stock and writes the audit row.
    if body.stock_qty > 0:
        record_movement(
            db, shop_id=body.shop_id, item_id=item.id,
            movement_type="STOCK_IN", quantity=body.stock_qty,
            unit=item.unit, source="dashboard_product_form",
            purchase_price=body.cost_price or item.cost_price,
            idempotency_key=f"dash_new_{uuid.uuid4().hex}"[:64],
            actor="shopkeeper",
        )
    db.add(ActionAudit(
        shop_id=body.shop_id, actor="shopkeeper", tool="create_or_update_product",
        arguments={"item_id": item.id, "name": item.name, "created": created,
                   "stock_received": body.stock_qty},
        rule_decision="allowed", timestamp=now,
    ))
    db.commit()
    db.refresh(item)
    return {"ok": True, "created": created, "item_id": item.id, "name": item.name,
            "sku": item.sku, "stock_qty": float(item.stock_qty or 0),
            "message": f"{'Product added' if created else 'Product updated'}: {item.name}"}


class CsvRow(BaseModel):
    name: str
    unit: str = "kg"
    price: int
    cost_price: Optional[int] = 0
    stock_qty: Optional[float] = 0
    reorder_level: Optional[float] = 5
    sku: Optional[str] = None
    category: Optional[str] = "General"


class CsvImportRequest(BaseModel):
    shop_id: int = 1
    rows: List[CsvRow]
    idempotency_key: Optional[str] = None


@router.post("/stock/csv-import")
def csv_import_endpoint(body: CsvImportRequest, db: Session = Depends(get_db)):
    """Legacy JSON import endpoint; stock changes flow through the purchase engine once."""
    from app.engine.products import register_product, ProductError
    from app.engine.purchases import record_purchase, PurchaseError

    if not db.get(Shop, body.shop_id):
        raise HTTPException(404, "Shop not found")
    created = updated = 0
    purchase_lines = []
    try:
        for row in body.rows:
            clean_name = (row.name or "").strip()
            if not clean_name:
                continue
            qty = float(row.stock_qty or 0)
            if qty < 0 or qty > 100000:
                raise HTTPException(400, f"Invalid stock quantity for {clean_name}")
            sku = (row.sku or "").strip() or None
            existing = db.scalars(select(Item).where(
                Item.shop_id == body.shop_id,
                (Item.name.ilike(clean_name)) | (Item.sku == sku if sku else False)
            )).first()
            if existing:
                if existing.unit and row.unit and existing.unit.strip().lower() != row.unit.strip().lower():
                    raise HTTPException(400, f"Unit mismatch for {clean_name}: existing unit is {existing.unit}")
                item = existing
                item.price = row.price
                if row.cost_price is not None and row.cost_price > 0:
                    item.cost_price = row.cost_price
                if row.reorder_level is not None:
                    item.reorder_level = row.reorder_level
                if row.category:
                    item.category = row.category
                updated += 1
            else:
                item = register_product(
                    db, body.shop_id, clean_name, (row.unit or "piece").strip().lower(),
                    row.price, cost_price=row.cost_price or 0, sku=sku,
                    category=row.category or "General", stock_qty=0,
                    reorder_level=row.reorder_level if row.reorder_level is not None else 5,
                    allow_existing=False, commit=False,
                )
                created += 1
            if qty > 0:
                purchase_lines.append({"item_id": item.id, "quantity": qty,
                                       "unit": item.unit,
                                       "purchase_price": row.cost_price if row.cost_price is not None else item.cost_price})
        purchase = None
        if purchase_lines:
            key = (body.idempotency_key or f"dashboard_csv_{uuid.uuid4().hex}")[:64]
            purchase = record_purchase(
                db, body.shop_id, purchase_lines, idempotency_key=key,
                notes="Dashboard CSV import",
            )
        else:
            db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (ProductError, PurchaseError) as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, f"CSV import failed safely: {exc}") from exc
    return {"ok": True, "imported": created, "updated": updated,
            "total": created + updated, "stock_movements": len(purchase_lines),
            "purchase_id": purchase.get("purchase_id") if purchase else None}


class QuickCreditRequest(BaseModel):
    shop_id: int = 1
    customer_id: int
    amount: int
    item_id: Optional[int] = None
    quantity: Optional[float] = 1.0


@router.post("/quick/credit")
def quick_credit(body: QuickCreditRequest, db: Session = Depends(get_db)):
    """Record credit directly from the dashboard quick action."""
    req_id = uuid.uuid4().hex
    if body.item_id:
        lines = [{"item_id": body.item_id, "qty": body.quantity or 1.0}]
        try:
            res = L.add_credit(db, body.shop_id, body.customer_id, lines, req_id)
            return {"ok": True, **res}
        except L.ToolError as e:
            raise HTTPException(400, detail=str(e))
    else:
        try:
            res = L.add_credit_amount(db, body.shop_id, body.customer_id, body.amount, req_id)
            return {"ok": True, **res}
        except L.ToolError as e:
            raise HTTPException(400, detail=str(e))


class QuickPaymentRequest(BaseModel):
    shop_id: int = 1
    customer_id: int
    amount: int


@router.post("/quick/payment")
def quick_payment(body: QuickPaymentRequest, db: Session = Depends(get_db)):
    """Record a payment directly from the dashboard."""
    req_id = uuid.uuid4().hex
    try:
        res = L.record_payment(db, body.shop_id, body.customer_id, body.amount, req_id)
        return {"ok": True, **res}
    except L.ToolError as e:
        raise HTTPException(400, detail=str(e))


@router.get("/daily-summary")
def get_daily_summary(shop_id: int = 1, lang: Optional[str] = None, db: Session = Depends(get_db)):
    """Fetch complete daily business intelligence summary."""
    from app.engine.daily_intelligence import compute_daily_summary
    return compute_daily_summary(db, shop_id, lang)


class BulkReminderRequest(BaseModel):
    shop_id: int = 1


@router.post("/reminders/bulk-send")
def send_bulk_reminders_endpoint(body: BulkReminderRequest, db: Session = Depends(get_db)):
    """Trigger bulk WhatsApp payment reminders for all pending customers."""
    from app.engine.daily_intelligence import compute_daily_summary, send_bulk_whatsapp_reminders
    summary = compute_daily_summary(db, body.shop_id)
    pending = summary.get("pending_customers", [])
    if not pending:
        return {"ok": True, "count": 0, "message": "No pending customer collections"}
    sent_count = send_bulk_whatsapp_reminders(db, body.shop_id, pending)
    return {"ok": True, "count": sent_count, "message": f"Reminders sent to {sent_count} customers"}

