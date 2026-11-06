import os
if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"  # must be set before the imports below

from app.db.seed import seed
from app.db.session import SessionLocal
from app.db.models import Item, LedgerEntry
from app.tools.ledger_tools import ToolError, add_credit, record_payment, get_balance

seed()


def expect_error(code, fn):
    try:
        fn()
    except ToolError as e:
        assert e.code == code, f"expected {code}, got {e.code}"
        return
    raise AssertionError(f"expected error {code}, but nothing failed")


with SessionLocal() as db:
    rice = db.query(Item).filter_by(name="chawal").one()
    bisc = db.query(Item).filter_by(name="biscuit").one()
    lines = [{"item_id": rice.id, "qty": 2}, {"item_id": bisc.id, "qty": 1}]

    r1 = add_credit(db, 1, 1, lines, "req-1")
    assert r1["total"] == 130 and r1["balance"] == 130, r1
    assert rice.stock_qty == 38 and bisc.stock_qty == 23
    print("1. credit saved: Rs 130, rice 38 kg, biscuit 23   OK")

    r2 = add_credit(db, 1, 1, lines, "req-1")  # same request again (retry)
    assert r2["entry_id"] == r1["entry_id"] and r2["replay"] is True
    assert rice.stock_qty == 38 and get_balance(db, 1) == 130
    print("2. retry did not duplicate anything              OK")

    expect_error("low_stock", lambda: add_credit(db, 1, 1, [{"item_id": rice.id, "qty": 999}], "req-2"))
    print("3. too much stock rejected                       OK")

    expect_error("credit_limit_exceeded", lambda: add_credit(db, 1, 1, [{"item_id": rice.id, "qty": 36}], "req-3"))
    print("4. credit limit enforced                         OK")

    expect_error("payment_exceeds_balance", lambda: record_payment(db, 1, 1, 500, "pay-1"))
    print("5. overpayment rejected                          OK")

    p = record_payment(db, 1, 1, 130, "pay-2")
    entry = db.get(LedgerEntry, r1["entry_id"])
    db.refresh(entry)
    assert p["balance"] == 0 and entry.status == "PAID"
    print("6. payment closed the entry (PAID)               OK")

print("\nAll Step 1 checks passed.")