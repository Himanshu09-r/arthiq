import os, time
if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"

from app.db.seed import seed
from app.db.session import SessionLocal
from app.db.models import Shop
from app.agent.pipeline import handle

seed()


def run(title, lang, turns):
    print(f"\n=== {title} [{lang}] ===")
    with SessionLocal() as db:
        db.get(Shop, 1).language = lang
        db.commit()
        for t in turns:
            t0 = time.time()
            r = handle(db, 1, t)
            print(f"you: {t}\nbot: {r['reply']}   [{r['state']}, {time.time() - t0:.1f}s]")


run("Two Rameshes + items", "hi-IN",
    ["रमेश ने दो किलो चावल और एक बिस्किट का पैकेट उधार लिया", "कुमार", "haan"])
run("Amount-only credit", "hi-IN", ["सुनीता ने 500 का उधार लिया", "हाँ"])
run("Correction 500 nahi, 300", "hi-IN", ["सुनीता ने 500 नहीं 300 दिए", "हाँ"])
run("Marathi", "mr-IN", ["सुनीताने दोन किलो तांदूळ उधार घेतले", "होय"])
run("Gujarati", "gu-IN", ["પ્રિયાએ બે કિલો ચોખા ઉધાર લીધા", "હા"])
run("English", "en-IN", ["Anil took one litre oil on credit", "yes"])
run("Tamil read-back", "ta-IN", ["Anil took one litre oil on credit", "இல்லை"])
run("Errors", "hi-IN",
    ["अनिल ने 100 किलो चावल उधार लिया",
     "अनिल ने 5000 का उधार लिया",
     "रामू ने 100 का उधार लिया"])