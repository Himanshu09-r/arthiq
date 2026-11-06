from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Shop, Item, InventoryMovement, Purchase, PurchaseItem
from app.engine.catalogue_import import (
    CatalogueImportError, commit_preview, parse_catalogue_csv, save_preview,
)


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    db.add(Shop(id=1, name="Test Shop", language="hi-IN"))
    db.commit()
    return engine, db


def test_csv_preview_and_commit_preserve_existing_stock_and_price_update():
    engine, db = make_db()
    try:
        rice = Item(shop_id=1, name="Rice", unit="kg", price=55, cost_price=40,
                    stock_qty=7, reorder_level=3, aliases=["chawal"], sku="RICE-1", category="Grocery")
        db.add(rice)
        db.commit()
        content = (
            "sku,item_name,category,unit,pack_size,purchase_price,selling_price,reorder_level,quantity,aliases\n"
            "RICE-1,Rice,Grains,kg,1 kg,42,60,4,,chawal|चावल\n"
            "MAG-1,Maggi Noodles,Packaged Food,packet,70 g packet,12,14,10,5,maggi|maggie|मैगी\n"
        ).encode()
        parsed = parse_catalogue_csv(content, db, 1)
        assert not parsed["errors"]
        preview = save_preview(db, 1, parsed)
        assert preview["can_commit"] is True
        result = commit_preview(db, 1, preview["token"], update_prices=True)
        db.expire_all()
        db.refresh(rice)
        maggi = db.scalar(select(Item).where(Item.shop_id == 1, Item.name == "Maggi Noodles"))
        assert result["created"] == 1 and result["updated"] == 1
        assert rice.stock_qty == 7  # blank quantity means no stock change
        assert rice.price == 60
        assert maggi is not None and maggi.stock_qty == 5
        assert maggi.price == 14 and maggi.cost_price == 12
        assert db.scalar(select(func.count(Purchase.id))) == 1
        assert db.scalar(select(func.count(PurchaseItem.id))) == 1
        assert db.scalar(select(func.count(InventoryMovement.id))) == 1
        try:
            commit_preview(db, 1, preview["token"])
            assert False, "second use of preview must be rejected"
        except CatalogueImportError as exc:
            assert exc.code == "preview_used"
    finally:
        db.close(); engine.dispose()


def test_csv_validation_rejects_duplicate_sku_and_unit_mismatch_without_writes():
    engine, db = make_db()
    try:
        item = Item(shop_id=1, name="Oil", unit="litre", price=150, cost_price=130,
                    stock_qty=4, reorder_level=2, sku="OIL-1", aliases=["tel"])
        db.add(item); db.commit()
        bad = (
            "sku,item_name,unit,selling_price,quantity\n"
            "OIL-1,Oil,kg,160,10\n"
            "OIL-1,Other Oil,litre,100,2\n"
        ).encode()
        parsed = parse_catalogue_csv(bad, db, 1)
        assert parsed["errors"]
        preview = save_preview(db, 1, parsed)
        assert preview["can_commit"] is False
        try:
            commit_preview(db, 1, preview["token"])
            assert False, "invalid preview cannot commit"
        except CatalogueImportError as exc:
            assert exc.code == "validation_failed"
        db.refresh(item)
        assert item.stock_qty == 4
        assert db.scalar(select(func.count(Purchase.id))) == 0
        assert db.scalar(select(func.count(InventoryMovement.id))) == 0
    finally:
        db.close(); engine.dispose()


def test_import_without_quantity_never_changes_stock_or_creates_purchase():
    engine, db = make_db()
    try:
        content = b"item_name,unit,selling_price,purchase_price,quantity\nSoap,piece,20,15,\n"
        parsed = parse_catalogue_csv(content, db, 1)
        p = save_preview(db, 1, parsed)
        result = commit_preview(db, 1, p["token"])
        soap = db.scalar(select(Item).where(Item.shop_id == 1, Item.name == "Soap"))
        assert result["stock_movements"] == 0
        assert soap.stock_qty == 0
        assert db.scalar(select(func.count(Purchase.id))) == 0
        assert db.scalar(select(func.count(InventoryMovement.id))) == 0
    finally:
        db.close(); engine.dispose()


def test_compact_six_column_csv_adds_stock_to_existing_stock():
    engine, db = make_db()
    try:
        rice = Item(shop_id=1, name="Rice", unit="kg", price=55, cost_price=40,
                    stock_qty=7, reorder_level=3, aliases=["chawal"])
        db.add(rice)
        db.commit()

        # This is the exact compact CSV format supplied by the user. stock_qty
        # represents incoming quantity and must be added to current stock.
        content = (
            "name,unit,price,cost_price,stock_qty,reorder_level\n"
            "Rice,kg,60,42,3,5\n"
        ).encode()
        parsed = parse_catalogue_csv(content, db, 1)
        assert parsed["errors"] == []
        assert parsed["rows"][0]["quantity"] == 3.0
        assert parsed["rows"][0]["selling_price"] == 60
        assert parsed["rows"][0]["purchase_price"] == 42

        preview = save_preview(db, 1, parsed)
        assert preview["can_commit"] is True
        result = commit_preview(db, 1, preview["token"], update_prices=True)

        db.expire_all()
        db.refresh(rice)
        movement = db.scalar(select(InventoryMovement).where(InventoryMovement.item_id == rice.id))
        assert rice.stock_qty == 10  # 7 old + 3 received; never overwritten with 3
        assert rice.price == 60
        assert rice.cost_price == 42
        assert rice.reorder_level == 5
        assert result["stock_movements"] == 1
        assert movement is not None
        assert movement.quantity == 3
        assert movement.previous_stock == 7
        assert movement.new_stock == 10
        assert db.scalar(select(func.count(Purchase.id))) == 1
    finally:
        db.close(); engine.dispose()
