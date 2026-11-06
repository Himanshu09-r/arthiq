from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    ActionAudit, Base, Customer, InventoryMovement, Item, LedgerEntry,
    Purchase, PurchaseItem, SaleLog, Shop, Supplier,
)
from app.agent import intents
from app.agent.pipeline import handle, SESSIONS
from app.engine import stock_in
from app.voice.wake import detect
from app.languages import SUPPORTED, normalize_language
from import_catalogue import load_rows, DEFAULT_CSV


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    shop = Shop(id=1, name="Test Kirana", language="hi-IN")
    session.add(shop)
    session.commit()
    SESSIONS.pop(1, None)
    try:
        yield session
    finally:
        SESSIONS.pop(1, None)
        session.close()
        engine.dispose()


def add_item(db, name, unit, stock, aliases=None, price=60, cost=45):
    item = Item(
        shop_id=1, name=name, aliases=aliases or [], unit=unit,
        price=price, cost_price=cost, stock_qty=stock, reorder_level=2,
        sku=f"TEST-{name.upper().replace(' ', '-')}", category="Test", status="active",
    )
    db.add(item)
    db.commit()
    return item


def test_wake_phrases_and_false_positive():
    for phrase in ("Suno ARTHIQ", "ARTHIQ SUNO", "Hey ARTHIQ", "Suno Aarti"):
        assert detect(phrase)[0] is True
    matched, command = detect("ARTHIQ SUNO aaj ka hisaab batao")
    assert matched is True
    assert command == "aaj ka hisaab batao"
    # A single-digit quantity immediately after the wake phrase must not be
    # consumed by fuzzy matching of a split brand spelling.
    assert detect("Suno ARTHIQ 1 kg rice aaya") == (True, "1 kg rice aaya")
    assert detect("ARTHIQ SUNO 2 packet Maggi aaye") == (True, "2 packet Maggi aaye")
    assert detect("hello there")[0] is False
    assert detect("arthiq is a word in this sentence")[0] is False


def test_stock_intent_parser_handles_single_and_multiple_items():
    one = intents.parse_stock_in("abhi 10 kg oil aaya hai")
    assert one["items"] == [{"name": "oil", "qty": 10.0, "unit": "kg", "price": None}]

    many = intents.parse_stock_in("5 kilo rice, 10 kilo sugar aur 15 packet Maggi aaya hai")
    assert [(x["name"].casefold(), x["qty"], x["unit"]) for x in many["items"]] == [
        ("rice", 5.0, "kg"), ("sugar", 10.0, "kg"), ("maggi", 15.0, "packet")
    ]
    assert intents.parse_stock_in("samaan aaya")["needs_items"] is True


def test_stock_in_writes_only_after_yes_and_is_idempotent(db):
    rice = add_item(db, "Rice", "kg", 5, ["chawal", "चावल"])

    preview = handle(db, 1, "1 kg rice aaya")
    assert preview["state"] == "confirm"
    assert db.get(Item, rice.id).stock_qty == 5
    pending = dict(SESSIONS[1].pending)

    saved = handle(db, 1, "haan")
    assert saved["state"] == "saved"
    db.expire_all()
    assert db.get(Item, rice.id).stock_qty == 6
    assert db.scalar(select(func.count(InventoryMovement.id))) == 1
    assert db.scalar(select(func.count(Purchase.id))) == 1
    assert db.scalar(select(func.count(PurchaseItem.id))) == 1

    # A retry using the same request id must replay, never add stock twice.
    stock_in.commit_stock_in(db, 1, pending["lines"], pending.get("supplier"), pending["request_id"])
    db.expire_all()
    assert db.get(Item, rice.id).stock_qty == 6
    assert db.scalar(select(func.count(InventoryMovement.id))) == 1
    assert db.scalar(select(func.count(Purchase.id))) == 1


def test_stock_in_multiple_items_and_unknown_new_product_flow(db):
    rice = add_item(db, "Rice", "kg", 5, ["chawal"])
    maggi = add_item(db, "Maggi Noodles", "packet", 8, ["maggi", "maggie", "noodles"], price=14, cost=12)

    preview = handle(db, 1, "2 kg chawal aur 3 packet Maggi aaye")
    assert preview["state"] == "confirm"
    assert db.get(Item, rice.id).stock_qty == 5
    assert db.get(Item, maggi.id).stock_qty == 8
    assert handle(db, 1, "haan")["state"] == "saved"
    db.expire_all()
    assert db.get(Item, rice.id).stock_qty == 7
    assert db.get(Item, maggi.id).stock_qty == 11

    unknown = handle(db, 1, "2 packet quinoa aaya")
    assert unknown["state"] == "ask"
    assert "quinoa" in unknown["reply"].casefold()
    ask = handle(db, 1, "haan naya hai")
    assert ask["state"] == "ask"  # asks for a selling price; no price is invented
    ready = handle(db, 1, "30 rupaye")
    assert ready["state"] == "confirm"
    assert "30" in ready["reply"]
    saved = handle(db, 1, "haan")
    assert saved["state"] == "saved"
    quinoa = db.scalar(select(Item).where(Item.shop_id == 1, Item.name == "Quinoa"))
    assert quinoa is not None
    assert quinoa.stock_qty == 2
    assert quinoa.price == 30


def test_daily_summary_is_database_backed_and_read_only(db):
    rice = add_item(db, "Rice", "kg", 5, ["chawal"])
    customer = Customer(shop_id=1, name="Ramesh", preferred_language="hi-IN", credit_limit=2000)
    db.add(customer)
    db.commit()
    now = datetime.now()
    db.add_all([
        SaleLog(shop_id=1, item_id=rice.id, qty=1, amount=60, sold_at=now, source="cash"),
        LedgerEntry(shop_id=1, customer_id=customer.id, type="credit", amount=100, paid_amount=0,
                    items_json=[], due_date=(now.date() - timedelta(days=1)), status="OPEN", created_at=now),
        LedgerEntry(shop_id=1, customer_id=customer.id, type="payment", amount=20, paid_amount=0,
                    items_json=[], due_date=None, status="OPEN", created_at=now),
    ])
    db.commit()
    before = db.scalar(select(func.count(ActionAudit.id)))

    result = handle(db, 1, "aaj ka poora hisaab batao")
    assert result["state"] == "summary"
    assert result["summary"]["cash_sales"] == 60
    assert result["summary"]["credit_sales"] == 100
    assert result["summary"]["sales"] == 160
    assert result["summary"]["collected"] == 20
    assert result["summary"]["outstanding_total"] == 80
    assert result["summary"]["overdue_count"] == 1
    assert db.scalar(select(func.count(ActionAudit.id))) == before


def test_odia_is_not_selectable_and_unknown_languages_fall_back():
    assert "od-IN" not in SUPPORTED
    assert normalize_language("od-IN") == "hi-IN"
    assert normalize_language("hi-IN") == "hi-IN"


def test_catalogue_csv_is_valid_and_includes_maggi():
    rows = load_rows(DEFAULT_CSV)
    assert len(rows) >= 50
    by_name = {r["item_name"].casefold(): r for r in rows}
    assert "maggi noodles" in by_name
    maggi = by_name["maggi noodles"]
    assert maggi["unit"] == "packet"
    assert int(maggi["purchase_price"]) < int(maggi["selling_price"])
    assert "maggie" in maggi["aliases"].casefold()


def test_incompatible_stock_units_are_rejected_without_mutation(db):
    oil = add_item(db, "Oil", "litre", 4, ["tel", "तेल"], price=150, cost=135)
    result = handle(db, 1, "10 kg oil aaya")
    assert result["state"] == "error"
    db.refresh(oil)
    assert oil.stock_qty == 4
    assert db.scalar(select(func.count(Purchase.id))) == 0


def test_exact_unit_conversions_are_not_labelled_approximate():
    from types import SimpleNamespace
    from app.engine.units import convert

    converted = convert(1000, "g", SimpleNamespace(unit="kg"))
    assert converted.ok and converted.qty == 1
    assert converted.approximate is False


def test_stock_parser_does_not_mistake_a_person_arriving_for_stock():
    assert intents.parse_stock_in("Ramesh aaya") is None
    assert intents.parse_stock_in("samaan aaya") == {"items": [], "supplier": None, "needs_items": True}


def test_bundled_catalogue_uses_exact_six_column_schema_and_sidecar_aliases():
    import csv
    from pathlib import Path

    expected = ["name", "unit", "price", "cost_price", "stock_qty", "reorder_level"]
    for filename in ("arthiq_item_price_list.csv", "arthiq_stock_import_template.csv"):
        path = Path(__file__).resolve().parents[1] / "data" / filename
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            assert next(reader) == expected
            assert sum(1 for row in reader if row and any(x.strip() for x in row)) >= 50

    maggi = next(r for r in load_rows(DEFAULT_CSV) if r["item_name"].casefold() == "maggi noodles")
    assert "maggie" in maggi["aliases"].casefold()
    assert maggi["sku"]
