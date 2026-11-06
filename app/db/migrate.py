"""ARTHIQ Database Migration System.
Applies safe, non-destructive schema migrations and backfills historical data.
Compatible with SQLite and SQLAlchemy.
"""
import json
import logging
from datetime import datetime
from sqlalchemy import text, inspect
from app.db.session import engine
from app.db.models import Base

logger = logging.getLogger("arthiq.migrate")


def get_existing_columns(conn, table_name: str) -> set[str]:
    """Return set of existing column names for table using PRAGMA table_info."""
    res = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
    return {row[1] for row in res}


def has_table(conn, table_name: str) -> bool:
    """Check if a table exists in sqlite_master."""
    res = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t;"),
        {"t": table_name}
    ).fetchone()
    return res is not None


def ensure_migration_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(50) PRIMARY KEY,
            description VARCHAR(200) NOT NULL,
            applied_at DATETIME NOT NULL
        );
    """))


def is_migration_applied(conn, version: str) -> bool:
    res = conn.execute(
        text("SELECT version FROM schema_migrations WHERE version=:v;"),
        {"v": version}
    ).fetchone()
    return res is not None


def record_migration(conn, version: str, description: str):
    conn.execute(
        text("INSERT OR REPLACE INTO schema_migrations (version, description, applied_at) VALUES (:v, :d, :at);"),
        {"v": version, "d": description, "at": datetime.now()}
    )


def run_migrations(target_engine=None) -> list[str]:
    """Execute all pending migrations safely. Zero data loss guaranteed."""
    eng = target_engine or engine
    applied = []

    with eng.connect() as conn:
        ensure_migration_table(conn)

        # ---------------------------------------------------------
        # Migration 001: Customer dynamic fields
        # ---------------------------------------------------------
        v = "001_customer_fields"
        if not is_migration_applied(conn, v) and has_table(conn, "customers"):
            cols = get_existing_columns(conn, "customers")
            if "locality" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN locality VARCHAR(150);"))
            if "alternate_phone" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN alternate_phone VARCHAR(20);"))
            if "status" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN status VARCHAR(20) DEFAULT 'active';"))
                conn.execute(text("UPDATE customers SET status = 'active' WHERE status IS NULL;"))
            if "duplicate_of_id" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN duplicate_of_id INTEGER REFERENCES customers(id);"))
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN created_at DATETIME;"))
                conn.execute(text("UPDATE customers SET created_at = datetime('now') WHERE created_at IS NULL;"))
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN updated_at DATETIME;"))
                conn.execute(text("UPDATE customers SET updated_at = datetime('now') WHERE updated_at IS NULL;"))
            record_migration(conn, v, "Add locality, alternate_phone, status, duplicate_of_id, timestamps to customers")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 002: Item catalogue fields
        # ---------------------------------------------------------
        v = "002_item_fields"
        if not is_migration_applied(conn, v) and has_table(conn, "items"):
            cols = get_existing_columns(conn, "items")
            if "sku" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN sku VARCHAR(50);"))
            if "category" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN category VARCHAR(50) DEFAULT 'General';"))
                conn.execute(text("UPDATE items SET category = 'General' WHERE category IS NULL;"))
            if "pack_size" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN pack_size VARCHAR(50);"))
            if "multilingual_names" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN multilingual_names JSON DEFAULT '{}';"))
                conn.execute(text("UPDATE items SET multilingual_names = '{}' WHERE multilingual_names IS NULL;"))
            if "preferred_supplier_id" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN preferred_supplier_id INTEGER REFERENCES suppliers(id);"))
            if "status" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN status VARCHAR(20) DEFAULT 'active';"))
                conn.execute(text("UPDATE items SET status = 'active' WHERE status IS NULL;"))
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN created_at DATETIME;"))
                conn.execute(text("UPDATE items SET created_at = datetime('now') WHERE created_at IS NULL;"))
            if "updated_at" not in cols:
                conn.execute(text("ALTER TABLE items ADD COLUMN updated_at DATETIME;"))
                conn.execute(text("UPDATE items SET updated_at = datetime('now') WHERE updated_at IS NULL;"))
            record_migration(conn, v, "Add sku, category, pack_size, multilingual_names, supplier, timestamps to items")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 003: SaleLog enhancement fields
        # ---------------------------------------------------------
        v = "003_sales_log_fields"
        if not is_migration_applied(conn, v) and has_table(conn, "sales_log"):
            cols = get_existing_columns(conn, "sales_log")
            if "customer_id" not in cols:
                conn.execute(text("ALTER TABLE sales_log ADD COLUMN customer_id INTEGER REFERENCES customers(id);"))
            if "inventory_movement_id" not in cols:
                conn.execute(text("ALTER TABLE sales_log ADD COLUMN inventory_movement_id INTEGER REFERENCES inventory_movements(id);"))
            record_migration(conn, v, "Add customer_id and inventory_movement_id to sales_log")
            applied.append(v)

        conn.commit()

    # ---------------------------------------------------------
    # Migration 004: Create new tables using metadata
    # ---------------------------------------------------------
    Base.metadata.create_all(eng)

    with eng.connect() as conn:
        v = "004_create_tables"
        if not is_migration_applied(conn, v):
            record_migration(conn, v, "Create suppliers, purchases, purchase_items, inventory_movements, transaction_items")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 005: Create performance & integrity indexes
        # ---------------------------------------------------------
        v = "005_indexes"
        if not is_migration_applied(conn, v):
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customers_phone ON customers (phone);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customers_locality ON customers (locality);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_sku ON items (sku);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_items_category ON items (category);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inv_movements_item_id ON inventory_movements (item_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inv_movements_timestamp ON inventory_movements (timestamp);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_inv_movements_type ON inventory_movements (movement_type);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_purchases_supplier_id ON purchases (supplier_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transaction_items_ledger_id ON transaction_items (ledger_entry_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_transaction_items_item_id ON transaction_items (item_id);"))
            record_migration(conn, v, "Create indexes on customers, items, movements, purchases, transaction_items")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 006: Backfill transaction_items from ledger_entries
        # ---------------------------------------------------------
        v = "006_backfill_transaction_items"
        if not is_migration_applied(conn, v) and has_table(conn, "ledger_entries"):
            entries = conn.execute(text("SELECT id, shop_id, items_json, created_at FROM ledger_entries WHERE type='credit';")).fetchall()
            backfilled_count = 0
            for e_id, s_id, items_raw, created_at in entries:
                if not items_raw:
                    continue
                try:
                    lines = json.loads(items_raw) if isinstance(items_raw, str) else items_raw
                except Exception:
                    continue
                if not isinstance(lines, list):
                    continue
                # Check if already backfilled for this entry
                existing = conn.execute(text("SELECT COUNT(*) FROM transaction_items WHERE ledger_entry_id=:lid"), {"lid": e_id}).scalar()
                if existing > 0:
                    continue
                for ln in lines:
                    if not isinstance(ln, dict):
                        continue
                    item_id = ln.get("item_id")
                    qty = float(ln.get("qty") or ln.get("quantity") or 0)
                    unit = str(ln.get("unit") or "")
                    price = int(ln.get("price") or 0)
                    line_total = int(ln.get("line_total") or round(price * qty))
                    if item_id and qty > 0:
                        conn.execute(text("""
                            INSERT INTO transaction_items (shop_id, ledger_entry_id, item_id, quantity, unit, unit_price, line_total, created_at)
                            VALUES (:shop_id, :ledger_entry_id, :item_id, :quantity, :unit, :unit_price, :line_total, :created_at)
                        """), {
                            "shop_id": s_id,
                            "ledger_entry_id": e_id,
                            "item_id": item_id,
                            "quantity": qty,
                            "unit": unit,
                            "unit_price": price,
                            "line_total": line_total,
                            "created_at": created_at or datetime.now()
                        })
                        backfilled_count += 1
            record_migration(conn, v, f"Backfilled {backfilled_count} lines into transaction_items from ledger_entries.items_json")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 007: Baseline inventory movements
        # ---------------------------------------------------------
        v = "007_baseline_inventory_movements"
        if not is_migration_applied(conn, v) and has_table(conn, "items") and has_table(conn, "inventory_movements"):
            movements_count = conn.execute(text("SELECT COUNT(*) FROM inventory_movements;")).scalar()
            if movements_count == 0:
                items = conn.execute(text("SELECT id, shop_id, name, unit, cost_price, stock_qty FROM items;")).fetchall()
                for i_id, s_id, name, unit, cost_price, stock_qty in items:
                    if stock_qty > 0:
                        conn.execute(text("""
                            INSERT INTO inventory_movements (
                                shop_id, item_id, movement_type, quantity, previous_stock, new_stock,
                                unit, purchase_price, reference_tx_id, source, idempotency_key, audit_info, timestamp
                            ) VALUES (
                                :shop_id, :item_id, 'MANUAL_ADJUSTMENT', :quantity, 0, :new_stock,
                                :unit, :purchase_price, 'migration_baseline', 'migration', :key, :audit, :ts
                            )
                        """), {
                            "shop_id": s_id,
                            "item_id": i_id,
                            "quantity": stock_qty,
                            "new_stock": stock_qty,
                            "unit": unit or "unit",
                            "purchase_price": cost_price or 0,
                            "key": f"baseline_item_{i_id}",
                            "audit": json.dumps({"reason": "Initial migration stock baseline", "item": name}),
                            "ts": datetime.now()
                        })
            record_migration(conn, v, "Recorded initial stock baselines into inventory_movements")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 008: Remove the retired Odia locale safely.
        # Existing shops/customers are retained and moved to Hindi.
        # ---------------------------------------------------------
        v = "008_remove_odia_language"
        if not is_migration_applied(conn, v):
            if has_table(conn, "shops") and "language" in get_existing_columns(conn, "shops"):
                conn.execute(text("UPDATE shops SET language='hi-IN' WHERE lower(language)='od-in';"))
            if has_table(conn, "customers") and "preferred_language" in get_existing_columns(conn, "customers"):
                conn.execute(text("UPDATE customers SET preferred_language='hi-IN' WHERE lower(preferred_language)='od-in';"))
            record_migration(conn, v, "Move legacy od-IN shop/customer preferences to hi-IN")
            applied.append(v)

        # ---------------------------------------------------------
        # Migration 009: Record persistent import-draft table availability.
        # Base.metadata.create_all above creates the table on existing installs.
        # ---------------------------------------------------------
        v = "009_inventory_import_drafts"
        if not is_migration_applied(conn, v) and has_table(conn, "inventory_import_drafts"):
            record_migration(conn, v, "Create persisted, one-time catalogue import previews")
            applied.append(v)

        conn.commit()

    return applied


if __name__ == "__main__":
    print("Running ARTHIQ database migrations...")
    applied = run_migrations()
    if applied:
        print(f"Successfully applied {len(applied)} migrations:")
        for m in applied:
            print(f"  - {m}")
    else:
        print("Database is already up to date. No migrations needed.")
