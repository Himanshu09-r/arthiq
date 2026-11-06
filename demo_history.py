"""Demo data for Step 5 on the REAL arthiq.db. Safe to re-run.
Sets stock, cost prices, one expiry date, cash = 8000, and 30 days of fake cash-sale history."""
import random
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.db.models import Base, Item, SaleLog, Shop
from app.db.session import SessionLocal, engine
from app.engine.stock import set_cash

Base.metadata.create_all(engine)
db = SessionLocal()
shop = db.scalars(select(Shop).order_by(Shop.id)).first()
now = datetime.now()
random.seed(7)

# name: (average sold per day, stock now, cost price)
PLAN = {"chawal": (15, 12, 48), "atta": (6, 10, 36), "cheeni": (5, 5, 38),
        "biscuit": (8, 60, 8), "tel": (2, 40, 125), "chai patti": (None, 10, 95)}

items = {i.name.lower(): i for i in db.scalars(select(Item).where(Item.shop_id == shop.id)).all()}
db.execute(delete(SaleLog).where(SaleLog.source == "demo"))
for name, (daily, stock, cost) in PLAN.items():
    it = items.get(name)
    if it is None:
        print("skip (item not found):", name)
        continue
    it.stock_qty, it.cost_price = stock, cost
    if daily:
        for d in range(30):
            qty = max(1, round(daily * random.uniform(0.7, 1.3)))
            at = (now - timedelta(days=d)).replace(hour=random.randint(9, 19), minute=random.randint(0, 59))
            if at > now:
                at = now - timedelta(minutes=1)
            db.add(SaleLog(shop_id=shop.id, item_id=it.id, qty=qty, amount=qty * it.price,
                           sold_at=at, source="demo"))
    else:  # dead stock: last sold 45 days ago
        at = now - timedelta(days=45)
        it.last_sold_at = at
        db.add(SaleLog(shop_id=shop.id, item_id=it.id, qty=3, amount=3 * it.price, sold_at=at, source="demo"))
if "biscuit" in items:
    items["biscuit"].expiry_date = date.today() + timedelta(days=5)
db.commit()
set_cash(db, shop.id, cash=8000, payables=0, lead_time_days=3)
print("demo history ready: cash 8000, 3 low-stock items, 1 near-expiry, 1 dead-stock")