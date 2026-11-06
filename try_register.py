import os
if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"

from app.db.seed import seed
from app.db.session import SessionLocal, engine
from app.db.models import Shop, Customer, Item
from app.tools import ledger_tools as L
from app.engine.customer_rules import normalize_phone
from app.engine.registration import check_registration
from app.agent.pipeline import handle

seed()
ok = []


def check(name, cond):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name)


def turn(db, text):
    r = handle(db, 1, text)
    print(f"  you: {text}\n  bot: {r['reply']}   [{r['state']}]")
    return r


# ---------- 1. rules and tools (no LLM) ----------
print("== rules and tools ==")
check("phone spaces", normalize_phone("98765 43210") == "9876543210")
check("phone +91", normalize_phone("+91 98765-43210") == "9876543210")
check("phone devanagari digits", normalize_phone("९८७६५४३२१०") == "9876543210")
check("phone too short rejected", normalize_phone("12345") is None)

with SessionLocal() as db:
    c = check_registration(db, 1, "aryan chouhan", "patel nagar", None, None, None, "hi-IN")
    check("new customer is ready, title-cased", c.status == "ready" and c.name == "Aryan Chouhan")
    check("default limit 2000, shop language", c.credit_limit == 2000 and c.language == "hi-IN")
    r1 = L.register_customer(db, 1, c.name, c.locality, None, c.language, c.credit_limit, "req-1")
    r2 = L.register_customer(db, 1, c.name, c.locality, None, c.language, c.credit_limit, "req-1")
    check("retry returns same customer", r1["customer_id"] == r2["customer_id"] and r2["replay"])
    check("auto customer code", r1["customer_code"] == f"CUST-{r1['customer_id']:04d}")
    check("exactly one row created", db.query(Customer).filter(Customer.name == "Aryan Chouhan").count() == 1)
    check("spelling variant is a duplicate",
          check_registration(db, 1, "Aryan Chauhan", "Patel Nagar", None, None, None, "hi-IN").status == "duplicate")
    check("same name, other locality is allowed",
          check_registration(db, 1, "Aryan Chouhan", "Civil Lines", None, None, None, "hi-IN").status == "ready")
    check("bad phone rejected",
          check_registration(db, 1, "Rohit Sharma", None, "12345", None, None, "hi-IN").code == "err_bad_phone")
    L.register_customer(db, 1, "Meena Jadhav", "Shivaji Nagar", "9123456780", "mr-IN", 3000, "req-2")
    check("same phone, different name = duplicate",
          check_registration(db, 1, "Someone Else", None, "9123456780", None, None, "hi-IN").status == "duplicate")
    check("custom limit and language kept",
          db.query(Customer).filter_by(name="Meena Jadhav").one().credit_limit == 3000)

# ---------- 2. the conversation ----------
print("\n== conversation: register, then first purchase ==")
with SessionLocal() as db:
    db.get(Shop, 1).language = "hi-IN"
    db.commit()
    r = turn(db, "ARTHIQ, add a new customer Rajesh Mehra, Gandhi Nagar wale.")
    check("registration read-back", r["state"] == "confirm" and "Gandhi Nagar" in r["reply"])
    check("nothing saved before yes", db.query(Customer).filter_by(name="Rajesh Mehra").count() == 0)
    r = turn(db, "yes")
    check("asks what he took", r["state"] == "ask")
    cust = db.query(Customer).filter_by(name="Rajesh Mehra").first()
    check("customer saved with locality", cust is not None and cust.locality == "Gandhi Nagar")
    check("no credit yet (separate operation)", L.get_balance(db, cust.id) == 0)
    r = turn(db, "do kilo chawal aur ek biscuit")
    check("purchase read-back total 130", r["state"] == "confirm" and "130" in r["reply"])
    r = turn(db, "yes")
    check("credit saved, balance 130", r["state"] == "saved" and L.get_balance(db, cust.id) == 130)
    check("rice stock reduced", db.query(Item).filter_by(name="chawal").one().stock_qty == 38)

    print("\n== same sentence: customer + purchase + phone ==")
    turn(db, "naya customer Neha Verma, Sector Five, phone 9876543210, ek kilo cheeni udhar")
    r = turn(db, "yes")
    check("purchase read-back right after registration", r["state"] == "confirm" and "44" in r["reply"])
    r = turn(db, "yes")
    neha = db.query(Customer).filter_by(name="Neha Verma").first()
    check("Neha saved with phone and credit 44",
          neha is not None and neha.phone == "9876543210" and L.get_balance(db, neha.id) == 44)

    print("\n== duplicate and bad phone ==")
    r = turn(db, "new customer Rajesh Mehra, Gandhi Nagar")
    check("duplicate detected", r["state"] == "ask")
    r = turn(db, "no")
    check("duplicate declined", r["state"] == "cancelled")
    r = turn(db, "new customer Rohit Sharma, Sector 5, phone 12345")
    check("bad phone message", r["state"] == "error")
    check("Rohit not created", db.query(Customer).filter_by(name="Rohit Sharma").count() == 0)

    print("\n== Marathi ==")
    db.get(Shop, 1).language = "mr-IN"
    db.commit()
    turn(db, "नवीन ग्राहक सुरेश पाटील, शिवाजी नगर")
    r = turn(db, "होय")
    check("Marathi asks what he took", r["state"] == "ask")
    r = turn(db, "नाही")
    check("declined purchase closes politely",
          db.query(Customer).filter_by(name="Suresh Patil").count() == 1)

# ---------- 3. persistence ----------
print("\n== persistence ==")
engine.dispose()                                  # drop every connection, like a restart
with SessionLocal() as db2:
    names = {c.name for c in db2.query(Customer).all()}
    check("customers survive restart", {"Aryan Chouhan", "Rajesh Mehra", "Neha Verma"} <= names)
    h = L.customer_history(db2, 1, db2.query(Customer).filter_by(name="Rajesh Mehra").one().id)
    check("history after restart", h["balance"] == 130 and len(h["entries"]) == 1)

print(f"\n{sum(ok)}/{len(ok)} passed")