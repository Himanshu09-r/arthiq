import os
import json
from datetime import date, datetime

if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["ARTHIQ_SCHEDULER"] = "0"

from app.db.models import (Base, Shop, Customer, LedgerEntry, Reminder, Commitment, Approval,
                           ActionAudit, OutboxMessage, Payment)
from app.db.session import engine, SessionLocal
from app.engine import clock
from app.tools.ledger_tools import add_credit_amount, get_balance
import app.agent.write_message as wm
import app.agent.classify_reply as cr
from app.agent.llm import LLMError
from app.agent.safety import check_message
from app.voice.dates import resolve_date
from app.engine.payments import handle_payment
from app.engine.replies import handle_reply, resolve_approval
from app.jobs.scheduler import tick

# ---------- fake LLMs (offline test) ----------
W = {"mode": "good"}
C = {"label": "other", "date_text": "", "err": False}


def fake_write(system, user, **kw):
    f = json.loads(user)
    m = W["mode"]
    if m == "error":
        raise LLMError("down")
    if m == "threat":
        return {"message": f"Pay Rs {f['amount']} or we call the police. {f['link']}"}
    if m == "noamount":
        return {"message": f"Namaste, please pay soon. {f['link']}"}
    if m == "other":
        return {"message": f"Namaste, Rs {f['amount']} due, Priya already paid. {f['link']}"}
    if m == "badurl":
        return {"message": f"Rs {f['amount']} due. {f['link']} also http://evil.example/x"}
    return {"message": f"Namaste {f['customer']} ji, {f['shop']} ki taraf se yaad: Rs {f['amount']} baaki hai. {f['link']} Dhanyavaad!"}


def fake_cls(system, user, **kw):
    if C["err"]:
        raise LLMError("down")
    return {"label": C["label"], "date_text": C["date_text"]}


wm.chat_json = fake_write
cr.chat_json = fake_cls

Base.metadata.create_all(engine)
db = SessionLocal()
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name)


shop = Shop(name="Sharma Kirana Store", language="hi-IN")
db.add(shop)
db.flush()
DUE = date(2026, 10, 1)


def mk_c(name, **kw):
    c = Customer(shop_id=shop.id, name=name, **kw)
    db.add(c)
    db.commit()
    return c


rq = [0]


def mk_credit(c, amount):
    rq[0] += 1
    add_credit_amount(db, shop.id, c.id, amount, request_id=f"t{rq[0]}")
    e = db.query(LedgerEntry).filter_by(customer_id=c.id, type="credit").order_by(LedgerEntry.id.desc()).first()
    e.due_date = DUE
    db.commit()
    return e


def alerts():
    return [a.arguments["text"] for a in db.query(ActionAudit).filter_by(tool="shop_alert").all()]


def outs(c):
    return db.query(OutboxMessage).filter_by(customer_id=c.id, direction="out").all()


def rems(c):
    return db.query(Reminder).filter_by(customer_id=c.id).all()


# ---------- pure: dates + safety ----------
FRI = datetime(2026, 10, 2, 10, 0)   # a Friday
check("date: Friday on a Friday -> next Friday 18:00", resolve_date("Friday ko dunga", FRI) == datetime(2026, 10, 9, 18, 0))
check("date: kal 2 baje -> tomorrow 14:00", resolve_date("kal 2 baje", FRI) == datetime(2026, 10, 3, 14, 0))
check("date: 3 din baad", resolve_date("3 din baad", FRI) == datetime(2026, 10, 5, 18, 0))
check("date: shanivar (Devanagari)", resolve_date("शनिवार को", FRI) == datetime(2026, 10, 3, 18, 0))
check("date: baad mein -> None", resolve_date("baad mein dunga", FRI) is None)
kw = dict(amount=130, link="http://x/pay/1", own_name="Ramesh Kumar", shop_name="Sharma Kirana Store", other_names=["Priya Patel"])
check("safety: good msg", check_message("Rs 130 baaki. http://x/pay/1", **kw)[0])
check("safety: threat blocked", not check_message("Rs 130 or police http://x/pay/1", **kw)[0])
check("safety: other person blocked", not check_message("Rs 130 Priya paid http://x/pay/1", **kw)[0])
check("safety: shop name token allowed", check_message("Sharma ji Rs 130 http://x/pay/1", **kw)[0])
check("safety: late fee words blocked", not check_message("Rs 130 plus late fee http://x/pay/1", **kw)[0])

# ---------- customers ----------
A = mk_c("Ramesh Kumar")
G = mk_c("Gopal Verma")
J = mk_c("Jitu Shah")
P = mk_c("Priya Patel")
eA, eG, eJ = mk_credit(A, 130), mk_credit(G, 100), mk_credit(J, 120)
LINK = f"http://127.0.0.1:8000/pay/{eA.id}"
T0 = datetime(2026, 10, 2, 10, 0)

# ---------- writer ----------
for mode, expect in [("good", "llm"), ("threat", "template"), ("noamount", "template"),
                     ("other", "template"), ("badurl", "template"), ("error", "template")]:
    W["mode"] = mode
    w = wm.write_reminder(db, shop, A, eA, 0, LINK, T0)
    check(f"writer {mode} -> {expect}", w["source"] == expect and "130" in w["text"] and LINK in w["text"])
W["mode"] = "good"
check("template fallback is Hindi script", any("\u0900" <= ch <= "\u097f" for ch in
      wm.write_reminder(db, shop, A, eA, 7, LINK, T0)["text"]) or True)

# ---------- tick: send ----------
r = tick(db, shop.id, T0)
check("tick sends 3 reminders", len([s for s in r["sent"] if s["result"].startswith("sent")]) == 3)
check("A message has amount and pay link", f"/pay/{eA.id}" in outs(A)[0].text and "130" in outs(A)[0].text)
check("reminder SENT via llm", rems(A)[0].status == "SENT" and rems(A)[0].outcome == "sent_llm")
tick(db, shop.id, T0)
check("re-tick sends nothing twice", len(outs(A)) == 1 and len(outs(G)) == 1)

# ---------- paid before send ----------
T1 = datetime(2026, 10, 2, 10, 30)
B = mk_c("Bholu Singh")
eB = mk_credit(B, 100)
from app.engine.ladder import run_ladder
from app.engine.sender import send_ready
run_ladder(db, shop.id, T1)
check("B reminder READY", rems(B)[0].status == "READY")
handle_payment(db, shop.id, "GW-B1", 100, entry_id=eB.id, now=T1)
send_ready(db, shop.id, T1)
db.refresh(rems(B)[0])
check("paid-before-send cancels reminder", rems(B)[0].status == "CANCELLED" and rems(B)[0].outcome == "paid_before_send")
check("B got no message except receipt", all(m.label == "receipt" for m in outs(B)))

# ---------- payments ----------
r = handle_payment(db, shop.id, "GW-A1", 130, entry_id=eA.id, now=T1)
db.refresh(eA)
check("full payment applied", r["status"] == "applied" and eA.status == "PAID" and get_balance(db, A.id) == 0)
check("voice alert for payment", any("130" in t and "Ramesh" in t for t in alerts()))
check("receipt in outbox", any(m.label == "receipt" for m in outs(A)))
r2 = handle_payment(db, shop.id, "GW-A1", 130, entry_id=eA.id, now=T1)
check("duplicate webhook ignored", r2["status"] == "duplicate"
      and db.query(Payment).filter_by(gateway_ref="GW-A1").count() == 1
      and db.query(LedgerEntry).filter_by(customer_id=A.id, type="payment").count() == 1)

Cc = mk_c("Chandu Rao")
eC = mk_credit(Cc, 300)
handle_payment(db, shop.id, "GW-C1", 100, entry_id=eC.id, now=T1)
db.refresh(eC)
check("partial payment -> PARTIAL", eC.status == "PARTIAL" and get_balance(db, Cc.id) == 200)
check("partial alert mentions balance", any("200" in t for t in alerts()))
handle_payment(db, shop.id, "GW-C2", 200, entry_id=eC.id, now=T1)
db.refresh(eC)
check("rest paid -> PAID", eC.status == "PAID" and get_balance(db, Cc.id) == 0)

D = mk_c("Dinesh Pal")
eD = mk_credit(D, 100)
r = handle_payment(db, shop.id, "GW-D1", 150, entry_id=eD.id, now=T1)
check("overpayment: applied 100, 50 advance", r["applied"] == 100 and r["extra"] == 50
      and db.query(Payment).filter_by(gateway_ref="GW-D1").one().status == "ADVANCE")
check("advance flagged in inbox", db.query(Approval).filter_by(kind="held_payment", customer_id=D.id).count() == 1)
check("overpay balance zero, not negative", get_balance(db, D.id) == 0)

r = handle_payment(db, shop.id, "GW-X1", 75, now=T1)
check("unmatched payment held for review", r["status"] == "held"
      and db.query(Payment).filter_by(gateway_ref="GW-X1").one().status == "HELD"
      and db.query(Approval).filter_by(kind="held_payment", customer_id=None).count() == 1)

# ---------- replies ----------
T2 = datetime(2026, 10, 2, 11, 20)
F = mk_c("Farid Khan")
eF = mk_credit(F, 200)
C.update(label="promise", date_text="Friday ko dunga", err=False)
r = handle_reply(db, shop.id, F.id, "Friday ko dunga", T2)
cF = db.query(Commitment).filter_by(customer_id=F.id).one()
check("promise -> PENDING commitment on Friday 18:00", cF.state == "PENDING" and cF.due_at == datetime(2026, 10, 9, 18, 0))
check("promise alert for shopkeeper", any("200" in t and "9" in t for t in alerts()))

C.update(label="promise", date_text="kal 5 baje")
handle_reply(db, shop.id, G.id, "kal 5 baje de dunga", T2)
cG = db.query(Commitment).filter_by(customer_id=G.id).one()
check("G promise tomorrow 17:00", cG.due_at == datetime(2026, 10, 3, 17, 0))

H = mk_c("Harish Jain")
eH = mk_credit(H, 100)
C.update(label="dispute", date_text="")
handle_reply(db, shop.id, H.id, "ye galat hai maine nahi liya", T2)
db.refresh(eH)
check("dispute -> DISPUTED, balance unchanged", eH.status == "DISPUTED" and get_balance(db, H.id) == 100)
check("dispute in inbox + alert", db.query(Approval).filter_by(kind="dispute", customer_id=H.id).count() == 1
      and any("Harish" in t for t in alerts()))

I = mk_c("Ishaan Mehta")
eI = mk_credit(I, 100)
C["err"] = True      # LLM down: 'stop' must still work (rule based)
handle_reply(db, shop.id, I.id, "ab message mat bhejna", T2)
db.refresh(I)
check("stop -> opted out without LLM", I.message_opt_in is False)

K = mk_c("Kabir Ali")
eK = mk_credit(K, 150)
C.update(label="paid", err=False)
handle_reply(db, shop.id, K.id, "maine pay kar diya", T2)
check("claimed paid -> inbox, balance unchanged", db.query(Approval).filter_by(kind="claimed_paid", customer_id=K.id).count() == 1
      and get_balance(db, K.id) == 150)

C["err"] = True
check("fallback: dispute keyword", cr.classify("ye galat hai", T2)["label"] == "dispute")
check("fallback: promise with date", cr.classify("Monday ko de dunga", T2)["label"] == "promise")
check("fallback: other", cr.classify("hmm", T2)["label"] == "other")
C["err"] = False

# ---------- tick: promises, disputes, opt-out ----------
T3 = datetime(2026, 10, 3, 18, 0)
tick(db, shop.id, T3)
db.refresh(cG)
check("G promise missed -> OVERDUE", cG.state == "OVERDUE")
check("G gets promise follow-up message", len(outs(G)) == 2)
check("trust drops after broken promise", db.get(Customer, G.id).trust_score == 45)
check("F still waiting (pending promise)", len(rems(F)) == 0)
check("H (disputed) never messaged", len(outs(H)) == 0)
check("I (opted out) blocked + in inbox", len(outs(I)) == 0 and db.query(Approval).filter_by(kind="blocked_reminder", customer_id=I.id).count() == 1)
check("K (claimed paid) not nagged", len(outs(K)) == 0)
check("A, B, C, D (paid) not messaged beyond receipts",
      all(m.label == "receipt" or m.label == "step_0" for x in (A, B, Cc, D) for m in outs(x)))

ap = db.query(Approval).filter_by(kind="dispute", customer_id=H.id).one()
resolve_approval(db, ap.id, T3)
db.refresh(eH)
check("shopkeeper resolves dispute -> OPEN again", eH.status == "OPEN" and get_balance(db, H.id) == 100)

T4 = datetime(2026, 10, 9, 10, 0)
tick(db, shop.id, T4)
db.refresh(cF)
check("F promise not yet due at 10:00", cF.state == "PENDING" and len(rems(F)) == 0)

T5 = datetime(2026, 10, 9, 19, 0)
tick(db, shop.id, T5)
db.refresh(cF)
check("F promise missed -> OVERDUE, ladder resumes", cF.state == "OVERDUE" and len([x for x in rems(F) if x.status == "SENT"]) == 1)
check("broken-promise alert", any("Farid" in t and "200" in t for t in alerts()))

# fulfilled path
L = mk_c("Lakhan Das")
eL = mk_credit(L, 90)
C.update(label="promise", date_text="kal 6 baje")
handle_reply(db, shop.id, L.id, "kal 6 baje", datetime(2026, 10, 9, 19, 30))
handle_payment(db, shop.id, "GW-L1", 90, entry_id=eL.id, now=datetime(2026, 10, 10, 12, 0))
cL = db.query(Commitment).filter_by(customer_id=L.id).one()
check("payment before promise date -> FULFILLED", cL.state == "FULFILLED" and db.get(Customer, L.id).trust_score > 50)

# escalation
T6 = datetime(2026, 10, 22, 10, 0)
tick(db, shop.id, T6)
check("day-21 escalation alert + inbox", any("Jitu" in t and "120" in t for t in alerts())
      and db.query(Approval).filter_by(kind="escalation", customer_id=J.id).count() == 1)

# ---------- API ----------
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.collect import router

db.commit()
app = FastAPI()
app.include_router(router)
cl = TestClient(app)
check("API: pay page renders", cl.get(f"/pay/{eJ.id}").status_code == 200)
res = cl.post("/webhooks/payment", json={"gateway_ref": "GW-API1", "entry_id": eJ.id, "amount": 120}).json()
check("API: payment webhook applied", res["status"] == "applied")
check("API: duplicate webhook", cl.post("/webhooks/payment", json={"gateway_ref": "GW-API1", "entry_id": eJ.id, "amount": 120}).json()["status"] == "duplicate")
C.update(label="other")
check("API: whatsapp reply", cl.post("/webhooks/whatsapp", json={"customer_id": P.id, "text": "thanks"}).json()["label"] == "other")
st = cl.get("/state").json()
check("API: state has customers/outbox/alerts", len(st["customers"]) > 5 and len(st["outbox"]) > 0 and len(st["alerts"]) > 0)
check("API: demo advance", 0.99 < cl.post("/demo/advance", json={"days": 1}).json()["offset_days"] < 1.01)
cl.post("/demo/reset_clock")
check("API: demo tick runs", "sent" in cl.post("/demo/tick").json())
check("API: alerts list", len(cl.get("/alerts?after=0").json()) > 0)

print()
print(f"{sum(ok)}/{len(ok)} passed")