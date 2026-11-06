import os
import sys
import types
from datetime import datetime

if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["ARTHIQ_SCHEDULER"] = "0"

# fake speech-to-text so the test is offline
STT = {"text": "haan"}
fake = types.ModuleType("app.voice.stt")
fake.transcribe = lambda data: (STT["text"], "hi-IN")
sys.modules["app.voice.stt"] = fake

from app.db.models import (Base, Shop, Customer, LedgerEntry, Approval, Commitment, ActionAudit)
from app.db.session import engine, SessionLocal
from app.tools.ledger_tools import add_credit_amount
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.inbox import router

Base.metadata.create_all(engine)
db = SessionLocal()
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name)


NOW = datetime(2026, 10, 30, 12, 0)
shop = Shop(name="Test Kirana", language="hi-IN")
db.add(shop)
db.flush()


def mk_c(name, **kw):
    c = Customer(shop_id=shop.id, name=name, **kw)
    db.add(c)
    db.commit()
    return c


def mk_ap(kind, cust=None, entry=None, **payload):
    a = Approval(shop_id=shop.id, kind=kind, customer_id=cust.id if cust else None,
                 entry_id=entry.id if entry else None, payload=payload, created_at=NOW)
    db.add(a)
    db.commit()
    return a


app = FastAPI()
app.include_router(router)
cl = TestClient(app)

R = mk_c("Ramesh Kumar")
add_credit_amount(db, shop.id, R.id, 500, request_id="d1")
esc = mk_ap("escalation", R, amount=500, days_overdue=21)
lst = cl.get("/inbox").json()
item = [i for i in lst["pending"] if i["id"] == esc.id][0]
check("inbox lists escalation with summary", "Ramesh" in item["summary"] and "21" in item["summary"])
check("escalation has 4 actions", [a["id"] for a in item["actions"]] == ["pause_reminders", "freeze_credit", "visit", "dismiss"])

# invalid action must change nothing
dsp_c = mk_c("Harish Jain")
add_credit_amount(db, shop.id, dsp_c.id, 100, request_id="d2")
e_d = db.query(LedgerEntry).filter_by(customer_id=dsp_c.id, type="credit").one()
e_d.status = "DISPUTED"
db.commit()
dsp = mk_ap("dispute", dsp_c, e_d, text="galat hai")
check("invalid action rejected, item stays pending",
      cl.post(f"/inbox/{dsp.id}/act", json={"action": "pause_reminders"}).json()["status"] == "invalid_action"
      and db.get(Approval, dsp.id).status == "PENDING")

r = cl.post(f"/inbox/{esc.id}/act", json={"action": "pause_reminders"}).json()
db.expire_all()
check("pause_reminders pauses customer", r["status"] == "done" and db.get(Customer, R.id).paused is True)
check("action audited with approver", db.query(ActionAudit).filter_by(tool="inbox_action", approved_by="shopkeeper").count() == 1)
check("second click does nothing", cl.post(f"/inbox/{esc.id}/act", json={"action": "pause_reminders"}).json()["status"] == "not_pending")

esc2 = mk_ap("escalation", R, amount=500, days_overdue=22)
cl.post(f"/inbox/{esc2.id}/act", json={"action": "freeze_credit"})
db.expire_all()
check("freeze_credit sets limit = balance (500)", db.get(Customer, R.id).credit_limit == 500)

# dispute resolve
r = cl.post(f"/inbox/{dsp.id}/act", json={"action": "resolve"}).json()
db.expire_all()
check("dispute resolved -> entry OPEN again", r["status"] == "done" and db.get(LedgerEntry, e_d.id).status == "OPEN")

# claimed paid
K = mk_c("Kabir Ali")
add_credit_amount(db, shop.id, K.id, 150, request_id="d3")
db.add(Commitment(shop_id=shop.id, customer_id=K.id, amount=150, due_at=datetime(2026, 11, 5, 18, 0),
                  state="PENDING", source_text="claimed paid: maine pay kar diya"))
db.commit()
cp = mk_ap("claimed_paid", K, text="maine pay kar diya")
cl.post(f"/inbox/{cp.id}/act", json={"action": "not_received"})
db.expire_all()
check("not_received cancels claimed-paid hold", db.query(Commitment).filter_by(customer_id=K.id).one().state == "CANCELLED")

# blocked reminder
P = mk_c("Paused Guy", paused=True)
bp = mk_ap("blocked_reminder", P, step=0, reason="customer_paused", amount=100)
O = mk_c("OptOut Guy", message_opt_in=False)
bo = mk_ap("blocked_reminder", O, step=0, reason="no_opt_in", amount=100)
items = {i["id"]: i for i in cl.get("/inbox").json()["pending"]}
check("paused block offers unpause", "unpause" in [a["id"] for a in items[bp.id]["actions"]])
check("opt-out can never be overridden", [a["id"] for a in items[bo.id]["actions"]] == ["dismiss"])
check("unpause on opt-out refused", cl.post(f"/inbox/{bo.id}/act", json={"action": "unpause"}).json()["status"] == "invalid_action")
cl.post(f"/inbox/{bp.id}/act", json={"action": "unpause"})
db.expire_all()
check("unpause clears paused flag", db.get(Customer, P.id).paused is False)

# held payment
hp = mk_ap("held_payment", None, gateway_ref="GW-X", amount=75, reason="no_match")
check("held payment summary", "75" in [i for i in cl.get("/inbox").json()["pending"] if i["id"] == hp.id][0]["summary"])
check("held payment mark reviewed", cl.post(f"/inbox/{hp.id}/act", json={"action": "ack"}).json()["status"] == "done")

# supplier orders
so1 = mk_ap("supplier_order", None, sig=[], items=[], total=500, message="Order: chawal 93 kg", lang="hi-IN")
so2 = mk_ap("supplier_order", None, sig=[], items=[], total=300, message="Order: atta 20 kg", lang="hi-IN")
check("supplier order shows message", [i for i in cl.get("/inbox").json()["pending"] if i["id"] == so1.id][0]["message"] == "Order: chawal 93 kg")
check("approve supplier order -> sent (simulated) + audit",
      cl.post(f"/inbox/{so1.id}/act", json={"action": "approve"}).json()["status"] == "done"
      and db.query(ActionAudit).filter_by(tool="supplier_send").count() == 1)
check("reject supplier order", cl.post(f"/inbox/{so2.id}/act", json={"action": "reject"}).json()["status"] == "rejected")

# voice approval
wav = {"audio": ("a.wav", b"RIFFfakewav", "audio/wav")}
so3 = mk_ap("supplier_order", None, sig=[], items=[], total=400, message="x", lang="hi-IN")
STT["text"] = "hmm"
r = cl.post(f"/inbox/{so3.id}/voice", files=wav).json()
check("voice: unclear changes nothing", r["status"] == "unclear" and r["transcript"] == "hmm" and db.get(Approval, so3.id).status == "PENDING")
STT["text"] = "haan"
r = cl.post(f"/inbox/{so3.id}/voice", files=wav).json()
check("voice: haan approves", r["status"] == "done" and r["transcript"] == "haan")
so4 = mk_ap("supplier_order", None, sig=[], items=[], total=400, message="y", lang="hi-IN")
STT["text"] = "nahi"
check("voice: nahi rejects", cl.post(f"/inbox/{so4.id}/voice", files=wav).json()["status"] == "rejected")
cr = mk_ap("customer_reply", R, text="thanks")
check("voice only for supplier orders", cl.post(f"/inbox/{cr.id}/voice", files=wav).json()["status"] == "voice_not_supported")

# recent list
rec = cl.get("/inbox").json()["recent"]
check("recent shows decided items with decision", len(rec) > 0 and any(i["decision"] for i in rec))

# audit
a_all = cl.get("/audit").json()
check("audit returns rows, tools and actors", len(a_all["rows"]) > 0 and "inbox_action" in a_all["tools"] and "shopkeeper" in a_all["actors"])
check("audit filter by tool", all(r["tool"] == "supplier_send" for r in cl.get("/audit?tool=supplier_send").json()["rows"])
      and len(cl.get("/audit?tool=supplier_send").json()["rows"]) >= 1)
check("audit filter by actor", all(r["actor"] == "shopkeeper" for r in cl.get("/audit?actor=shopkeeper").json()["rows"]))
check("audit text search", len(cl.get("/audit?q=freeze_credit").json()["rows"]) == 1)
check("audit limit", len(cl.get("/audit?limit=2").json()["rows"]) == 2)
check("dashboard page loads", cl.get("/dashboard").status_code == 200)

print()
print(f"{sum(ok)}/{len(ok)} passed")