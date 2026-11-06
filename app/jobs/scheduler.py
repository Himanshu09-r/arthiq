"""One tick = promises -> ladder -> escalation alerts -> send. APScheduler runs it every 60 s.
Production story: Celery beat + Redis run the same functions."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import Customer, LedgerEntry, Shop
from app.db.session import SessionLocal
from app.engine import clock
from app.engine.alerts import push_alert
from app.engine.commitments import check_promises
from app.engine.ladder import outstanding, run_ladder
from app.engine.sender import send_ready

_scheduler = None


def tick(db, shop_id: int, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    promises = check_promises(db, shop_id, now)
    ladder = run_ladder(db, shop_id, now)
    for r in ladder:
        if r["verdict"] == "escalate":
            e = db.get(LedgerEntry, r["entry_id"])
            c = db.get(Customer, e.customer_id)
            push_alert(db, shop, "escalation", now=now, name=c.name, amount=outstanding(e),
                       days=(now.date() - e.due_date).days)
    db.commit()
    sent = send_ready(db, shop_id, now)
    try:
        from app.engine.stock import nightly
        nightly(db, shop_id, now)
    except Exception as e:  # never break the tick
        db.rollback()
        print("nightly error:", e)
    return {"now": now.isoformat(), "promises": promises, "ladder": ladder, "sent": sent}


def _job():
    db = SessionLocal()
    try:
        for shop in db.scalars(select(Shop)).all():
            tick(db, shop.id)
    except Exception as e:  # never kill the scheduler thread
        print("tick error:", e)
    finally:
        db.close()


def start(interval_seconds: int = 60):
    global _scheduler
    if _scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_job, "interval", seconds=interval_seconds, max_instances=1, coalesce=True)
    _scheduler.start()