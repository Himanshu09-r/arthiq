import os
from datetime import date, datetime

if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"   # throwaway DB, real arthiq.db untouched

from app.db.models import (Base, Shop, Customer, LedgerEntry, Reminder,
                           Commitment, Approval, ActionAudit)
from app.db.session import engine, SessionLocal
from app.engine import clock
from app.engine.guardrails import check_reminder, in_quiet_hours, late_fee_allowed
from app.engine.ladder import run_ladder, channel_for, outstanding

Base.metadata.create_all(engine)
db = SessionLocal()
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name)


# ---------- setup ----------
shop = Shop(name="Test Kirana")
db.add(shop)
db.flush()
DUE = date(2026, 10, 1)


def mk_customer(name, **kw):
    c = Customer(shop_id=shop.id, name=name, **kw)
    db.add(c)
    db.flush()
    return c


def mk_entry(c, amount, **kw):
    e = LedgerEntry(shop_id=shop.id, customer_id=c.id, type="credit",
                    amount=amount, due_date=DUE, **kw)
    db.add(e)
    db.flush()
    return e


c1 = mk_customer("Ramesh Kumar")
c2 = mk_customer("Paused Guy", paused=True)
c3 = mk_customer("OptOut Guy", message_opt_in=False)
c4 = mk_customer("Disputer")
c5 = mk_customer("Promiser")
c6 = mk_customer("CommitDispute")
c8 = mk_customer("Payer")
e1 = mk_entry(c1, 130)
e2 = mk_entry(c2, 100)
e3 = mk_entry(c3, 100)
e4 = mk_entry(c4, 100, status="DISPUTED")
e5 = mk_entry(c5, 100)
e6 = mk_entry(c6, 100)
e8 = mk_entry(c8, 100, paid_amount=100, status="PAID")
db.add(Commitment(shop_id=shop.id, customer_id=c5.id, entry_id=e5.id, amount=100,
                  due_at=datetime(2026, 10, 5, 18, 0), state="PENDING"))
db.add(Commitment(shop_id=shop.id, customer_id=c6.id, entry_id=e6.id, amount=100,
                  due_at=datetime(2026, 10, 3, 18, 0), state="DISPUTED"))
db.commit()


def run(now):
    return {r["entry_id"]: r for r in run_ladder(db, shop.id, now)}


def rems(e):
    return db.query(Reminder).filter_by(entry_id=e.id).order_by(Reminder.ladder_step).all()


def blocked_count():
    return db.query(Approval).filter_by(kind="blocked_reminder").count()


# ---------- pure helpers ----------
check("quiet 22:00", in_quiet_hours(22, 20, 9))
check("quiet 03:00", in_quiet_hours(3, 20, 9))
check("not quiet 09:00", not in_quiet_hours(9, 20, 9))
check("not quiet 19:00", not in_quiet_hours(19, 20, 9))
check("late fee off by default", late_fee_allowed(shop) is False)
check("outstanding = amount - paid", outstanding(LedgerEntry(amount=200, paid_amount=50)) == 150)

# ---------- ladder ----------
r = run(datetime(2026, 9, 30, 10, 0))
check("nothing before due date", r == {})

r = run(datetime(2026, 10, 1, 22, 0))   # due day, but quiet hours
check("quiet hours -> delay", r[e1.id]["verdict"] == "delay" and r[e1.id]["reason"] == "quiet_hours")
check("delay resumes next day 09:00", r[e1.id]["resume_at"] == "2026-10-02T09:00:00")
check("paused customer blocked", r[e2.id]["verdict"] == "block" and r[e2.id]["reason"] == "customer_paused")
check("opted-out customer blocked", r[e3.id]["reason"] == "no_opt_in")
check("disputed commitment blocks", r[e6.id]["reason"] == "open_dispute")
check("DISPUTED entry never messaged", e4.id not in r)
check("PAID entry never messaged", e8.id not in r)
check("pending promise skips ladder", e5.id not in r)
check("delay saves no reminder row", db.query(Reminder).count() == 0)
check("3 blocked items in inbox", blocked_count() == 3)

r = run(datetime(2026, 10, 2, 10, 0))   # next morning
check("due step sent after quiet hours", r[e1.id]["verdict"] == "allow" and r[e1.id]["step"] == 0)
check("reminder row READY on whatsapp", len(rems(e1)) == 1 and rems(e1)[0].status == "READY"
      and rems(e1)[0].channel == "whatsapp")
check("inbox not duplicated", blocked_count() == 3)

r = run(datetime(2026, 10, 2, 10, 0))   # run again
check("re-run sends nothing twice", e1.id not in r and len(rems(e1)) == 1)

r = run(datetime(2026, 10, 4, 10, 0))   # +3
check("+3 reminder", r[e1.id]["step"] == 3 and r[e1.id]["verdict"] == "allow")
check("promise still pending -> skipped", e5.id not in r)

r = run(datetime(2026, 10, 8, 10, 0))   # +7
check("+7 falls back to whatsapp when calls off",
      r[e1.id]["step"] == 7 and r[e1.id]["channel"] == "whatsapp" and r[e1.id]["verdict"] == "allow")
check("ladder resumes after promise date passes", r[e5.id]["step"] == 7 and r[e5.id]["verdict"] == "allow")
shop.calls_allowed = True
check("+7 uses voice when calls allowed", channel_for(7, shop) == "voice")
shop.calls_allowed = False
d = check_reminder(db, shop, c1, e1, "voice", datetime(2026, 10, 8, 10, 0))
check("voice blocked when calls not allowed", d.verdict == "block" and d.reason == "calls_not_allowed")

r = run(datetime(2026, 10, 15, 10, 0))  # +14
check("+14 reminder", r[e1.id]["step"] == 14 and r[e1.id]["verdict"] == "allow")

r = run(datetime(2026, 10, 22, 10, 0))  # +21
check("+21 escalates, no customer message", r[e1.id]["verdict"] == "escalate")
check("escalation in inbox once", db.query(Approval).filter_by(kind="escalation", entry_id=e1.id).count() == 1)
check("day-21 reminder row is ESCALATED",
      [x for x in rems(e1) if x.ladder_step == 21][0].status == "ESCALATED")
run(datetime(2026, 10, 22, 10, 0))
check("escalation not duplicated on re-run",
      db.query(Approval).filter_by(kind="escalation", entry_id=e1.id).count() == 1)

# ---------- weekly cap ----------
c7 = mk_customer("Capped")
e7 = mk_entry(c7, 100)
for step, t in [(0, datetime(2026, 10, 8, 8, 0)), (3, datetime(2026, 10, 8, 9, 0)), (7, datetime(2026, 10, 8, 9, 30))]:
    db.add(Reminder(shop_id=shop.id, entry_id=e7.id, customer_id=c7.id, ladder_step=step,
                    channel="whatsapp", status="SENT", created_at=t))
db.commit()
d = check_reminder(db, shop, c7, e7, "whatsapp", datetime(2026, 10, 8, 11, 0))
check("weekly cap -> delay", d.verdict == "delay" and d.reason == "weekly_cap")
check("cap resumes when oldest ages out", d.resume_at == datetime(2026, 10, 15, 8, 0))

# ---------- audit + clock ----------
audits = db.query(ActionAudit).filter_by(actor="guardrail").all()
check("guardrail decisions audited", len(audits) > 0)
check("pause decision in audit log",
      any(a.rule_decision == "block:customer_paused" and a.arguments["entry_id"] == e2.id for a in audits))
clock.advance(days=2)
delta = (clock.now() - datetime.now()).total_seconds() / 86400
check("fast-forward clock +2 days", 1.99 < delta < 2.01)
clock.reset()
check("clock reset", abs((clock.now() - datetime.now()).total_seconds()) < 2)

print()
print(f"{sum(ok)}/{len(ok)} passed")