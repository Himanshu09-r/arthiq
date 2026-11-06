import os
from datetime import datetime, timedelta

if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"
os.environ["ARTHIQ_SCHEDULER"] = "0"

from app.db.models import (Base, Shop, Customer, Item, LedgerEntry, SaleLog, Approval, ActionAudit)
from app.db.session import engine, SessionLocal
from app.tools.ledger_tools import add_credit_amount, record_payment
from app.engine.stock import compute_stock, alerts, nightly, set_cash
from app.engine.cash_guardian import cash_guardian, collection_priorities
from app.engine import orders
import app.engine.briefing as br
from app.engine.briefing import briefing

Base.metadata.create_all(engine)
db = SessionLocal()
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name)


NOW = datetime.now()
shop = Shop(name="Test Kirana", language="hi-IN")
db.add(shop)
db.flush()


def mk_item(name, price, cost, stock, unit="kg", **kw):
    it = Item(shop_id=shop.id, name=name, unit=unit, price=price, cost_price=cost, stock_qty=stock, aliases=[], **kw)
    db.add(it)
    db.flush()
    return it


chawal = mk_item("chawal", 60, 48, 12)
atta = mk_item("atta", 45, 36, 10)
cheeni = mk_item("cheeni", 44, 38, 5)
biscuit = mk_item("biscuit", 10, 0, 60, "packet", expiry_date=(NOW + timedelta(days=5)).date())
tel = mk_item("tel", 150, 125, 40, "litre")
chai = mk_item("chai patti", 120, 95, 10, "packet")

for it, daily in [(chawal, 15), (atta, 6), (cheeni, 5), (biscuit, 8), (tel, 2)]:
    for d in range(30):
        db.add(SaleLog(shop_id=shop.id, item_id=it.id, qty=daily, amount=daily * it.price,
                       sold_at=NOW - timedelta(days=d, minutes=5), source="test"))
db.add(SaleLog(shop_id=shop.id, item_id=chai.id, qty=3, amount=360, sold_at=NOW - timedelta(days=45), source="test"))
db.commit()

# ---------- stock ----------
st = {s["item_id"]: s for s in compute_stock(db, shop.id, NOW)}
check("sales speed chawal = 15/day", abs(st[chawal.id]["daily"] - 15) < 0.01)
check("reorder point chawal = 15*3 + 15*2 = 75", st[chawal.id]["reorder_point"] == 75)
check("chawal low, days left 0.8", st[chawal.id]["low"] and abs(st[chawal.id]["days_left"] - 0.8) < 0.01)
check("biscuit not low but near expiry", not st[biscuit.id]["low"] and st[biscuit.id]["near_expiry"])
check("tel healthy", not st[tel.id]["low"] and not st[tel.id]["near_expiry"])
check("chai is dead stock (45 days)", st[chai.id]["dead"] and st[chai.id]["dead_days"] == 45)
check("no history -> default reorder level", st[chai.id]["reorder_point"] == 5)

al = alerts(db, shop.id, NOW, limit=3)
check("alerts limited to top 3", len(al) == 3)
check("alerts ranked: chawal first", al[0]["item_id"] == chawal.id and all(a["kind"] == "low" for a in al))
al5 = alerts(db, shop.id, NOW, limit=5)
kinds = {a["item_id"]: a["kind"] for a in al5}
check("expiry + dead alerts exist", kinds.get(biscuit.id) == "expiry" and kinds.get(chai.id) == "dead")
en = alerts(db, shop.id, NOW, limit=5, lang="en-IN")
check("english alert text", any("Only 12 kg of" in a["text"] for a in en) and any("expires in 5 days" in a["text"] for a in en))
check("hindi alert has native script", any("\u0900" <= ch <= "\u097f" for ch in al[0]["text"]))

# ---------- customers + dues ----------
def mk_c(name):
    c = Customer(shop_id=shop.id, name=name, credit_limit=100000)
    db.add(c)
    db.commit()
    return c


R, S, P = mk_c("Ramesh Kumar"), mk_c("Sharma ji"), mk_c("Priya Patel")
add_credit_amount(db, shop.id, R.id, 1500, request_id="s1")
add_credit_amount(db, shop.id, S.id, 1800, request_id="s2")
add_credit_amount(db, shop.id, P.id, 900, request_id="s3")
eR = db.query(LedgerEntry).filter_by(customer_id=R.id, type="credit").one()
eR.due_date = (NOW - timedelta(days=1)).date()
db.query(LedgerEntry).filter_by(customer_id=P.id, type="credit").one().status = "DISPUTED"
db.commit()

# ---------- cash guardian ----------
g = cash_guardian(db, shop.id, NOW)
check("cash unknown -> asks once", g["need_cash"] is True and "कैश" in g["text"])
set_cash(db, shop.id, cash=8000, payables=0, lead_time_days=3)
g = cash_guardian(db, shop.id, NOW)
check("all 3 low items fit in 8000", len(g["buy"]) == 3 and g["skipped"] == [] and g["need"] == 6756)
check("most urgent first: chawal 93 kg = 4464", g["buy"][0]["item_id"] == chawal.id and g["buy"][0]["qty"] == 93 and g["buy"][0]["cost"] == 4464)
check("budget = cash, dues NOT counted as cash", g["budget"] == 8000 and g["receivable"] == 4200)
check("spoken text has cash and need", "8000" in g["text"] and "6756" in g["text"])

pr = collection_priorities(db, shop.id, NOW, 3)
check("overdue customer chased first", pr[0]["name"] == "Ramesh Kumar" and pr[0]["overdue"] == 1500)
check("disputed customer never chased", all(p["name"] != "Priya Patel" for p in pr))

set_cash(db, shop.id, cash=4000)
g = cash_guardian(db, shop.id, NOW)
check("4000: greedy skips chawal, buys atta+cheeni", [b["item_id"] for b in g["buy"]] == [atta.id, cheeni.id]
      and [b["item_id"] for b in g["skipped"]] == [chawal.id])
check("what-if: dues from 2 customers unlock chawal", g["whatif"] and g["whatif"]["items"] == [chawal.id] and len(g["whatif"]["names"]) == 2)
check("spoken what-if present", "Ramesh" in g["text"] and "Sharma" in g["text"])

set_cash(db, shop.id, cash=1000)
g = cash_guardian(db, shop.id, NOW)
check("1000: nothing fits -> collect first", g["buy"] == [] and len(g["skipped"]) == 3 and "वसूली" in g["text"])

set_cash(db, shop.id, cash=8000, payables=3000)
g = cash_guardian(db, shop.id, NOW)
check("payables reduce budget (5000 -> only chawal)", g["budget"] == 5000 and [b["item_id"] for b in g["buy"]] == [chawal.id])
set_cash(db, shop.id, cash=8000, payables=0)

# ---------- nightly ----------
check("reorder level default before nightly", db.get(Item, chawal.id).reorder_level == 5)
r = nightly(db, shop.id, NOW)
db.refresh(chawal)
check("nightly saves reorder point (75)", r["status"] == "done" and chawal.reorder_level == 75)
check("nightly runs once per day", nightly(db, shop.id, NOW)["status"] == "already_ran")
db.refresh(chai)
check("nightly leaves no-history items alone", chai.reorder_level == 5)

# ---------- supplier orders ----------
d1 = orders.create_draft(db, shop.id, NOW)
check("draft created for 6756", d1["status"] == "created" and d1["total"] == 6756)
check("draft message has qty and last price", "93" in d1["message"] and "₹48" in d1["message"] and "kg" in d1["message"])
check("nothing sent before approval", db.query(ActionAudit).filter_by(tool="supplier_send").count() == 0)
check("same draft not duplicated", orders.create_draft(db, shop.id, NOW)["approval_id"] == d1["approval_id"])

set_cash(db, shop.id, cash=4000)
d2 = orders.create_draft(db, shop.id, NOW)
check("new budget -> new draft, old rejected", d2["status"] == "created" and d2["total"] == 2292
      and db.get(Approval, d1["approval_id"]).status == "REJECTED"
      and db.query(Approval).filter_by(kind="supplier_order", status="PENDING").count() == 1)
check("approve sends (simulated) and audits", orders.approve(db, d2["approval_id"], NOW)["status"] == "done"
      and db.get(Approval, d2["approval_id"]).status == "DONE"
      and db.query(ActionAudit).filter_by(tool="supplier_send").count() == 1)
check("approve twice ignored", orders.approve(db, d2["approval_id"], NOW)["status"] == "not_pending")

d3 = orders.create_draft(db, shop.id, NOW)
check("voice 'nahi' rejects", orders.answer(db, d3["approval_id"], "nahi", NOW)["status"] == "rejected")
d4 = orders.create_draft(db, shop.id, NOW)
check("voice 'haan' approves", orders.answer(db, d4["approval_id"], "haan", NOW)["status"] == "done")
d5 = orders.create_draft(db, shop.id, NOW)
check("unclear answer changes nothing", orders.answer(db, d5["approval_id"], "hmm", NOW)["status"] == "unclear"
      and db.get(Approval, d5["approval_id"]).status == "PENDING")

# ---------- briefing ----------
record_payment(db, shop.id, R.id, 300, request_id="b1")
exp_sales = (sum(e.amount for e in db.query(LedgerEntry).filter_by(type="credit") if e.created_at.date() == NOW.date())
             + sum(s.amount for s in db.query(SaleLog) if s.sold_at.date() == NOW.date()))
b = briefing(db, shop.id, NOW, use_llm=False)
d = b["data"]
check("briefing sales from SQL", d["sales"] == exp_sales)
check("briefing collected = 300", d["collected"] == 300)
check("briefing overdue = 1 customer, 1200", d["overdue_count"] == 1 and d["overdue_amount"] == 1200)
check("briefing template numbers in text", "300" in b["text"] and "1200" in b["text"] and b["source"] == "template")
check("briefing tip = reorder top item", d["tip"][0] == "buy")

import json
M = {"mode": "good"}


def fake_smooth(system, user, **kw):
    t = json.loads(user)["text"]
    if M["mode"] == "error":
        raise RuntimeError("down")
    if M["mode"] == "badnum":
        return {"text": t.replace("300", "500")}
    return {"text": t}


br.chat_json = fake_smooth
check("LLM smoothing accepted when numbers match", briefing(db, shop.id, NOW)["source"] == "llm")
M["mode"] = "badnum"
bb = briefing(db, shop.id, NOW)
check("LLM changed a number -> template used", bb["source"] == "template" and "300" in bb["text"] and "500" not in bb["text"])
M["mode"] = "error"
check("LLM down -> template used", briefing(db, shop.id, NOW)["source"] == "template")

# ---------- API ----------
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.insights import router

app = FastAPI()
app.include_router(router)
cl = TestClient(app)
s = cl.get("/stock/status").json()
check("API: stock status", len(s["items"]) == 6 and len(s["alerts"]) == 3)
check("API: set cash", cl.post("/cash", json={"cash": 8000, "payables": 0}).json()["cash"] == 8000)
check("API: guardian", len(cl.get("/cash/guardian").json()["buy"]) == 3)
dr = cl.post("/orders/draft").json()
check("API: draft", dr["status"] in ("created", "exists"))
check("API: pending orders", len(cl.get("/orders/pending").json()) == 1)
check("API: answer yes", cl.post(f"/approvals/{dr['approval_id']}/answer", json={"text": "haan"}).json()["status"] == "done")
check("API: briefing", "text" in cl.get("/briefing/today?smooth=0").json())
check("API: page", cl.get("/insights").status_code == 200)

print()
print(f"{sum(ok)}/{len(ok)} passed")