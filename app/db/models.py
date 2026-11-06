from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, JSON, ForeignKey, UniqueConstraint, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(10), default="hi-IN")
    credit_days: Mapped[int] = mapped_column(default=15)
    late_fee_enabled: Mapped[bool] = mapped_column(default=False)
    calls_allowed: Mapped[bool] = mapped_column(default=False)
    autonomy_level: Mapped[int] = mapped_column(default=2)
    quiet_start_hour: Mapped[int] = mapped_column(default=20)
    quiet_end_hour: Mapped[int] = mapped_column(default=9)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (Index("uq_customer_code", "customer_code", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(100))
    nicknames: Mapped[list] = mapped_column(JSON, default=list)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    preferred_language: Mapped[str] = mapped_column(String(10), default="hi-IN")
    message_opt_in: Mapped[bool] = mapped_column(default=True)
    paused: Mapped[bool] = mapped_column(default=False)
    trust_score: Mapped[int] = mapped_column(default=50)
    credit_limit: Mapped[int] = mapped_column(default=2000)  # rupees
    # Dynamic Customer extensions
    customer_code: Mapped[Optional[str]] = mapped_column(String(20), default=None)  # CUST-0007
    locality: Mapped[Optional[str]] = mapped_column(String(150), default=None)
    alternate_phone: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(100))
    contact_person: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    phone: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    locality: Mapped[Optional[str]] = mapped_column(String(150), default=None)
    address: Mapped[Optional[str]] = mapped_column(Text, default=None)
    gstin: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    unit: Mapped[str] = mapped_column(String(20))
    price: Mapped[int] = mapped_column()        # rupees per unit (selling price)
    cost_price: Mapped[int] = mapped_column(default=0)  # rupees per unit (purchase price)
    stock_qty: Mapped[float] = mapped_column(default=0)
    reorder_level: Mapped[float] = mapped_column(default=5)
    expiry_date: Mapped[Optional[date]] = mapped_column()
    last_sold_at: Mapped[Optional[datetime]] = mapped_column()
    # Dynamic Item extensions
    sku: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    category: Mapped[Optional[str]] = mapped_column(String(50), default="General")
    pack_size: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    multilingual_names: Mapped[dict] = mapped_column(JSON, default=dict)
    preferred_supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    type: Mapped[str] = mapped_column(String(10))       # credit | payment
    amount: Mapped[int] = mapped_column()
    paid_amount: Mapped[int] = mapped_column(default=0)  # for credit rows
    items_json: Mapped[list] = mapped_column(JSON, default=list)
    due_date: Mapped[Optional[date]] = mapped_column()
    status: Mapped[str] = mapped_column(String(12), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_ref: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class ActionAudit(Base):  # append-only: we only ever insert
    __tablename__ = "actions_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column()
    actor: Mapped[str] = mapped_column(String(30))
    tool: Mapped[str] = mapped_column(String(50))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_decision: Mapped[str] = mapped_column(String(100), default="allowed")
    approved_by: Mapped[Optional[str]] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(default=datetime.now)


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (UniqueConstraint("entry_id", "ladder_step", name="uq_reminder_entry_step"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    ladder_step: Mapped[int] = mapped_column()               # 0, 3, 7, 14, 21
    channel: Mapped[str] = mapped_column(String(12))         # whatsapp | voice | none
    message_text: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="hi-IN")
    status: Mapped[str] = mapped_column(String(12), default="READY")  # READY|SENT|ESCALATED|CANCELLED
    outcome: Mapped[Optional[str]] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    sent_at: Mapped[Optional[datetime]] = mapped_column()


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger_entries.id"))
    gateway_ref: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(12), default="APPLIED")  # APPLIED|HELD|ADVANCE
    received_at: Mapped[datetime] = mapped_column(default=datetime.now)


class Commitment(Base):
    __tablename__ = "commitments"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger_entries.id"))
    amount: Mapped[int] = mapped_column(default=0)
    due_at: Mapped[datetime] = mapped_column()
    state: Mapped[str] = mapped_column(String(12), default="PENDING")  # PENDING|FULFILLED|OVERDUE|DISPUTED|CANCELLED
    source_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column()


class Approval(Base):  # shopkeeper inbox
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    kind: Mapped[str] = mapped_column(String(30))  # escalation|blocked_reminder|held_payment|supplier_order
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger_entries.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="PENDING")  # PENDING|APPROVED|REJECTED|DONE
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    decided_at: Mapped[Optional[datetime]] = mapped_column()


class OutboxMessage(Base):  # simulated WhatsApp / SMS / voice outbox, plus inbound replies
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    entry_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ledger_entries.id"))
    reminder_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reminders.id"))
    direction: Mapped[str] = mapped_column(String(4))        # out | in
    channel: Mapped[str] = mapped_column(String(12), default="whatsapp")
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[Optional[str]] = mapped_column(String(200))
    label: Mapped[Optional[str]] = mapped_column(String(20))  # classifier label for inbound
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class CashState(Base):
    __tablename__ = "cash_state"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    cash: Mapped[Optional[int]] = mapped_column()          # None = unknown, ask once
    payables: Mapped[int] = mapped_column(default=0)
    lead_time_days: Mapped[int] = mapped_column(default=3)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)


class SaleLog(Base):  # cash sales (credit sales are read from the ledger)
    __tablename__ = "sales_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty: Mapped[float] = mapped_column()
    amount: Mapped[int] = mapped_column(default=0)
    sold_at: Mapped[datetime] = mapped_column(default=datetime.now)
    source: Mapped[str] = mapped_column(String(12), default="cash")
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), default=None)
    inventory_movement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_movements.id"), default=None)


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    movement_type: Mapped[str] = mapped_column(String(30))
    # STOCK_IN | STOCK_OUT | RETURN_IN | RETURN_OUT | MANUAL_ADJUSTMENT | REVERSAL
    quantity: Mapped[float] = mapped_column()
    previous_stock: Mapped[float] = mapped_column()
    new_stock: Mapped[float] = mapped_column()
    unit: Mapped[str] = mapped_column(String(20))
    purchase_price: Mapped[Optional[int]] = mapped_column(default=None)  # rupees per unit if applicable
    reference_tx_id: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    source: Mapped[str] = mapped_column(String(50))
    # ledger_credit | cash_sale | purchase | manual_adjustment | return_in | return_out | reversal
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, default=None)
    audit_info: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.now)


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id"), default=None)
    invoice_ref: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    purchase_date: Mapped[date] = mapped_column(default=date.today)
    total_amount: Mapped[int] = mapped_column(default=0)  # rupees
    status: Mapped[str] = mapped_column(String(20), default="RECEIVED")  # RECEIVED | PENDING | CANCELLED
    payment_status: Mapped[str] = mapped_column(String(20), default="UNPAID")  # UNPAID | PARTIAL | PAID
    paid_amount: Mapped[int] = mapped_column(default=0)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, default=None)
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[float] = mapped_column()
    unit: Mapped[str] = mapped_column(String(20))
    purchase_price: Mapped[int] = mapped_column()  # unit cost price in rupees
    line_total: Mapped[int] = mapped_column()  # quantity * purchase_price
    expiry_date: Mapped[Optional[date]] = mapped_column(default=None)
    batch_number: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    inventory_movement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_movements.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class InventoryImportDraft(Base):
    """Validated CSV import preview; a pending preview can be applied only once."""
    __tablename__ = "inventory_import_drafts"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    rows_json: Mapped[list] = mapped_column(JSON, default=list)
    errors_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | APPLIED
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class TransactionItem(Base):
    __tablename__ = "transaction_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    ledger_entry_id: Mapped[int] = mapped_column(ForeignKey("ledger_entries.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    quantity: Mapped[float] = mapped_column()
    unit: Mapped[str] = mapped_column(String(20))
    unit_price: Mapped[int] = mapped_column()
    line_total: Mapped[int] = mapped_column()
    inventory_movement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory_movements.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    applied_at: Mapped[datetime] = mapped_column(default=datetime.now)