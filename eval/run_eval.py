"""Extraction eval. Real Sarvam LLM, throwaway eval.db. Run: python -m eval.run_eval
Checks only the fields each case specifies. Writes eval/results.md."""
import os
import re
import time
from collections import defaultdict

if os.path.exists("eval.db"):
    os.remove("eval.db")
os.environ["DATABASE_URL"] = "sqlite:///eval.db"
os.environ["ARTHIQ_SCHEDULER"] = "0"

from sqlalchemy import select

from app.agent.extract import extract
from app.db.models import Base, Customer, Item, Shop
from app.db.session import SessionLocal, engine

Base.metadata.create_all(engine)
db = SessionLocal()
shop = Shop(name="Sharma Kirana Store", language="hi-IN")
db.add(shop)
db.flush()
for n, nick in [("Ramesh Kumar", []), ("Ramesh Gupta", []), ("Sharma ji", ["Sharma"]),
                ("Sunita Deshmukh", []), ("Priya Patel", []), ("Anil Reddy", [])]:
    db.add(Customer(shop_id=shop.id, name=n, nicknames=nick))
for n, unit, price, al in [
        ("chawal", "kg", 60, ["rice", "चावल", "तांदूळ", "ચોખા"]),
        ("biscuit", "packet", 10, ["बिस्किट", "बिस्कीट"]),
        ("atta", "kg", 45, ["flour", "आटा", "पीठ"]),
        ("tel", "litre", 150, ["oil", "तेल"]),
        ("cheeni", "kg", 44, ["sugar", "चीनी", "साखर", "ખાંડ"]),
        ("chai patti", "packet", 120, ["tea", "चायपत्ती"])]:
    db.add(Item(shop_id=shop.id, name=n, unit=unit, price=price, aliases=al, stock_qty=50))
db.commit()

CANON = {
    "chawal": {"chawal", "rice", "चावल", "तांदूळ", "ચોખા", "arisi", "அரிசி", "chaawal"},
    "biscuit": {"biscuit", "biscuits", "बिस्किट", "बिस्कीट"},
    "atta": {"atta", "flour", "आटा", "पीठ", "aata"},
    "tel": {"tel", "oil", "तेल"},
    "cheeni": {"cheeni", "sugar", "चीनी", "साखर", "ખાંડ", "chini"},
    "chai patti": {"chai patti", "tea", "चायपत्ती", "chai", "chaipatti", "tea powder"},
}


def canon(name: str):
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    for k, v in CANON.items():
        if n in {x.lower() for x in v}:
            return k
    return n


# lang, sentence, expected fields
CASES = [
    ("hi", "Ramesh Kumar ne do kilo chawal aur ek biscuit ka packet udhar liya",
     dict(intent="add_credit", cust="ramesh kumar", items={"chawal": 2, "biscuit": 1})),
    ("hi", "Ramesh ne do kilo chawal udhar liya",
     dict(intent="add_credit", cust="ramesh", items={"chawal": 2})),
    ("hi", "Sharma ji ne 500 ka udhar liya", dict(intent="add_credit", cust="sharma", amount=500)),
    ("hi", "Sharma ji ne paanch sau rupaye diye", dict(intent="record_payment", cust="sharma", amount=500)),
    ("hi", "Ramesh Kumar ne 500 nahi, 300 diye",
     dict(intent="record_payment", cust="ramesh kumar", amount=300, corrected_from=500)),
    ("hi", "Sunita ne teen kilo atta udhar liya", dict(intent="add_credit", cust="sunita", items={"atta": 3})),
    ("hi", "Anil Reddy ne ek litre tel aur do packet chai patti udhar liya",
     dict(intent="add_credit", cust="anil", items={"tel": 1, "chai patti": 2})),
    ("hi", "Priya ne 200 rupaye de diye", dict(intent="record_payment", cust="priya", amount=200)),
    ("hi", "Sharma ji ne ek kilo cheeni udhar li", dict(intent="add_credit", cust="sharma", items={"cheeni": 1})),
    ("hi", "Anil ne 1000 nahi, 800 ka udhar liya",
     dict(intent="add_credit", cust="anil", amount=800, corrected_from=1000)),
    ("hi", "Ramesh Gupta ne 150 de diye", dict(intent="record_payment", cust="ramesh gupta", amount=150)),
    ("hi", "Sharma ji ne ek biscuit ka packet aur ek kilo atta udhar liya",
     dict(intent="add_credit", cust="sharma", items={"biscuit": 1, "atta": 1})),
    ("hi", "aaj mausam kaisa hai", dict(intent="other")),
    ("en", "Ramesh Kumar took two kilos of rice on credit",
     dict(intent="add_credit", cust="ramesh kumar", items={"chawal": 2})),
    ("en", "Priya paid 300 rupees", dict(intent="record_payment", cust="priya", amount=300)),
    ("en", "Sharma ji took 250 rupees on credit", dict(intent="add_credit", cust="sharma", amount=250)),
    ("en", "Sunita paid 400, no wait, 450",
     dict(intent="record_payment", cust="sunita", amount=450, corrected_from=400)),
    ("en", "What is the weather today", dict(intent="other")),
    ("mr", "सुनीता ने दोन किलो तांदूळ उधार घेतले", dict(intent="add_credit", cust="sunita", items={"chawal": 2})),
    ("mr", "सुनीता देशमुख ने ३०० रुपये दिले", dict(intent="record_payment", cust="sunita", amount=300)),
    ("mr", "शर्मा जी ने ५०० रुपयांची उधारी घेतली", dict(intent="add_credit", cust="sharma", amount=500)),
    ("mr", "अनिल ने एक लिटर तेल उधार घेतले", dict(intent="add_credit", cust="anil", items={"tel": 1})),
    ("gu", "પ્રિયા એ બે કિલો ખાંડ ઉધાર લીધી", dict(intent="add_credit", cust="priya", items={"cheeni": 2})),
    ("gu", "પ્રિયા પટેલ એ ૨૦૦ રૂપિયા આપ્યા", dict(intent="record_payment", cust="priya", amount=200)),
    ("gu", "શર્મા જી એ ૧ કિલો ચોખા ઉધાર લીધા", dict(intent="add_credit", cust="sharma", items={"chawal": 1})),
    ("ta", "அனில் இரண்டு கிலோ அரிசி கடனுக்கு வாங்கினார்",
     dict(intent="add_credit", cust="anil", items={"chawal": 2})),
    ("ta", "பிரியா 300 ரூபாய் கொடுத்தார்", dict(intent="record_payment", cust="priya", amount=300)),
]

FIELDS = ["intent", "customer", "items", "amount", "correction"]
tot = defaultdict(lambda: [0, 0])      # field -> [correct, checked]
bylang = defaultdict(lambda: [0, 0])   # lang -> [fully correct, cases]
rows, fails, times = [], [], []


def num(x):
    try:
        return None if x is None else int(float(x))
    except (TypeError, ValueError):
        return None


for lang, text, exp in CASES:
    t0 = time.time()
    res, err = {}, None
    try:
        ex = extract(db, shop.id, text)
        got_items = {}
        for ln in (ex.items or []):
            got_items[canon(ln.name)] = float(ln.qty) if ln.qty is not None else None
        got = {"intent": ex.intent, "customer": (ex.customer_ref or "").lower(), "items": got_items,
               "amount": num(ex.amount), "correction": num(ex.corrected_from)}
    except Exception as e:
        got, err = {}, f"{type(e).__name__}: {e}"
    dt = time.time() - t0
    times.append(dt)

    if "intent" in exp:
        res["intent"] = got.get("intent") == exp["intent"]
    if "cust" in exp:
        res["customer"] = exp["cust"] in got.get("customer", "")
    if "items" in exp:
        gi = got.get("items", {})
        res["items"] = set(gi) == set(exp["items"]) and all(
            gi[k] is not None and abs(gi[k] - v) < 0.01 for k, v in exp["items"].items())
    if "amount" in exp:
        res["amount"] = got.get("amount") == exp["amount"]
    if "corrected_from" in exp:
        res["correction"] = got.get("correction") == exp["corrected_from"]
    for f, v in res.items():
        tot[f][1] += 1
        tot[f][0] += int(v)
    full = bool(res) and all(res.values())
    bylang[lang][1] += 1
    bylang[lang][0] += int(full)
    rows.append((lang, text, full, dt))
    print(("PASS " if full else "FAIL ") + f"[{lang}] {text}  ({dt:.1f}s)")
    if not full:
        fails.append((lang, text, exp, got, err, res))
        print("      expected:", exp)
        print("      got     :", got or err)

n = len(CASES)
good = sum(1 for r in rows if r[2])
lines = [
    "# Arthiq extraction eval", "",
    f"{n} labelled sentences (Hinglish, English, Marathi, Gujarati, Tamil). "
    "Real Sarvam LLM (sarvam-105b), schema-validated extraction, before any validation or read-back.", "",
    f"**Fully correct: {good}/{n} ({100 * good // n}%)**   |   avg {sum(times) / n:.1f}s, max {max(times):.1f}s per sentence", "",
    "| Field | Correct | Checked | Accuracy |", "|---|---|---|---|",
]
for f in FIELDS:
    c, k = tot[f]
    if k:
        lines.append(f"| {f} | {c} | {k} | {100 * c // k}% |")
lines += ["", "| Language | Fully correct | Cases |", "|---|---|---|"]
for lg in ["hi", "en", "mr", "gu", "ta"]:
    c, k = bylang[lg]
    lines.append(f"| {lg} | {c} | {k} |")
if fails:
    lines += ["", "## Misses (kept for honesty)", ""]
    for lg, text, exp, got, err, res in fails:
        lines.append(f"- [{lg}] `{text}` -> failed fields: "
                     f"{[k for k, v in res.items() if not v] or err}")
lines += ["", "Read-back and a spoken 'yes' still stand between every extraction and the ledger, "
          "so a miss here is caught by the shopkeeper before anything is saved."]
os.makedirs("eval", exist_ok=True)
with open(os.path.join("eval", "results.md"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")

print()
print(f"Fully correct: {good}/{n}")
for f in FIELDS:
    c, k = tot[f]
    if k:
        print(f"  {f:<11} {c}/{k}")
print("Wrote eval\\results.md")