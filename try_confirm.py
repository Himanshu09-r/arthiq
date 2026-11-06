import os
if os.path.exists("test.db"):
    os.remove("test.db")
os.environ["DATABASE_URL"] = "sqlite:///test.db"

from app.db.seed import seed
from app.db.session import SessionLocal
from app.db.models import Shop, Customer
from app.languages import SUPPORTED
from app.engine.confirmation import classify
from app.voice.confirm_vocab import vocab_for
from app.voice.templates import say
from app.agent.pipeline import handle, SESSIONS
from app.tools.ledger_tools import get_balance

seed()
ok = []


def check(name, cond, extra=""):
    ok.append(bool(cond))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if (extra and not cond) else ""))


# ---------- 1. vocabulary in all 11 languages (no LLM) ----------
print("== spoken yes / no / correction, 11 languages ==")
CASES = {  # lang: (yes phrases, no phrases, correction phrases)
 "en-IN": (["Yes.", "yeah, go ahead", "ok"], ["No.", "nope", "wrong"], ["no, make it 300"]),
 "hi-IN": (["हाँ", "haan ji", "हां जी, ठीक है", "हाँ कर दो"], ["नहीं", "नहीं नहीं", "ठीक नहीं है", "गलत"],
           ["नहीं, तीन किलो चावल", "haan lekin 300 nahi 500"]),
 "mr-IN": (["होय", "हो, बरोबर आहे", "ठीक आहे"], ["नाही", "नको", "चूक"], ["नाही, तीन किलो तांदूळ"]),
 "gu-IN": (["હા", "હા, બરાબર છે", "ઠીક છે"], ["ના", "નહીં", "ખોટું"], ["ના, ત્રણ કિલો ચોખા"]),
 "bn-IN": (["হ্যাঁ", "হ্যাঁ, ঠিক আছে", "ঠিক"], ["না", "নয়", "ভুল"], ["না, তিন কিলো চাল"]),
 "ta-IN": (["ஆமா", "ஆம், சரி", "சரிதான்"], ["இல்லை", "வேண்டாம்", "தவறு"], ["இல்லை, மூன்று கிலோ அரிசி"]),
 "te-IN": (["అవును", "అవును, సరే", "సరే"], ["కాదు", "లేదు", "వద్దు"], ["కాదు, మూడు కిలోలు బియ్యం"]),
 "kn-IN": (["ಹೌದು", "ಹೌದು, ಸರಿ", "ಸರಿ"], ["ಇಲ್ಲ", "ಬೇಡ", "ತಪ್ಪು"], ["ಇಲ್ಲ, ಮೂರು ಕಿಲೋ ಅಕ್ಕಿ"]),
 "ml-IN": (["അതെ", "അതെ, ശരി", "ശരി"], ["അല്ല", "വേണ്ട", "തെറ്റ്"], ["അല്ല, മൂന്ന് കിലോ അരി"]),
 "pa-IN": (["ਹਾਂ", "ਹਾਂ ਜੀ, ਠੀਕ ਹੈ", "ਠੀਕ"], ["ਨਹੀਂ", "ਨਾ", "ਗਲਤ"], ["ਨਹੀਂ, ਤਿੰਨ ਕਿਲੋ ਚੌਲ"]),
 "od-IN": (["ହଁ", "ହଁ, ଠିକ୍ ଅଛି", "ଠିକ୍"], ["ନା", "ନାହିଁ", "ଭୁଲ"], ["ନା, ତିନି କିଲୋ ଚାଉଳ"]),
}
check("all 11 languages covered", set(CASES) == set(SUPPORTED))
for lang, (ys, ns, cs) in CASES.items():
    by = [t for t in ys if classify(t, lang).kind != "yes"]
    bn = [t for t in ns if classify(t, lang).kind != "no"]
    bc = [t for t in cs if classify(t, lang).kind != "correction"]
    check(f"{lang}: yes words", not by, by)
    check(f"{lang}: no words", not bn, bn)
    check(f"{lang}: corrections", not bc, bc)
    v = vocab_for(lang)
    check(f"{lang}: no word is both yes and no", not (v.yes & v.no))
check("union vocab has no yes/no clash", not (vocab_for(None).yes & vocab_for(None).no))
check("answer in another language is accepted", classify("అవును", "hi-IN").kind == "yes")
check("'Ramesh ji' is not a yes", classify("Ramesh ji", "hi-IN").kind == "other")
check("'ji' alone is a yes", classify("जी", "hi-IN").kind == "yes")
check("'haan lekin ...' is a correction", classify("haan lekin teen kilo", "hi-IN").kind == "correction")
check("silence is empty", classify("  ...  ", "hi-IN").kind == "empty")


def turn(db, text):
    r = handle(db, 1, text)
    print(f"  you: {text}\n  bot: {r['reply']}   [{r['state']}]")
    return r


# ---------- 2. conversation ----------
with SessionLocal() as db:
    anil = db.query(Customer).filter_by(name="Anil Reddy").one().id
    sunita = db.query(Customer).filter_by(name="Sunita Deshmukh").one().id
    db.get(Shop, 1).language = "hi-IN"
    db.commit()

    print("\n== say no, then yes, then yes again ==")
    r = turn(db, "Anil Reddy ने 200 रुपये का उधार लिया")
    check("read-back asks for confirmation", r["state"] == "confirm" and "200" in r["reply"])
    check("client is told to listen", r.get("listen") is True and r.get("confirmation_id"))
    r = turn(db, "नहीं")
    check("'nahi' cancels", r["state"] == "cancelled" and get_balance(db, anil) == 0)
    turn(db, "Anil Reddy ने 200 रुपये का उधार लिया")
    r = turn(db, "हाँ")
    check("'haan' commits", r["state"] == "saved" and get_balance(db, anil) == 200)
    r = turn(db, "हाँ")
    check("second 'haan' does not double-save",
          r["reply"] == say("hi-IN", "already_saved") and get_balance(db, anil) == 200)
    SESSIONS[1].last_commit = None
    r = turn(db, "नहीं")
    check("answer with nothing pending", r["reply"] == say("hi-IN", "nothing_pending"))

    print("\n== spoken correction: no, 300 ==")
    turn(db, "Sunita Deshmukh ने 500 का उधार लिया")
    r = turn(db, "नहीं, 300")
    check("correction re-reads 300", r["state"] == "confirm" and "300" in r["reply"] and "500" not in r["reply"])
    r = turn(db, "haan")
    check("corrected amount saved", r["state"] == "saved" and get_balance(db, sunita) == 300)

    print("\n== unclear answers (depends on the LLM) ==")
    turn(db, "Sunita Deshmukh ने 100 का उधार लिया")
    r = turn(db, "hmm")
    check("first unclear -> asks again", r["state"] == "confirm" and say("hi-IN", "reprompt") in r["reply"])
    turn(db, "umm")
    r = turn(db, "uh")
    check("third unclear -> cancelled, nothing saved", r["state"] == "cancelled" and get_balance(db, sunita) == 300)

    print("\n== timeout ==")
    turn(db, "Anil Reddy ने 50 रुपये का उधार लिया")
    SESSIONS[1].pending["_t"] -= 1000            # pretend 1000 seconds passed
    r = turn(db, "हाँ")
    check("late 'haan' is rejected", r["reply"] == say("hi-IN", "expired") and get_balance(db, anil) == 200)

    print("\n== registration confirmed by voice ==")
    turn(db, "new customer Rajesh Mehra, Gandhi Nagar")
    r = turn(db, "हाँ")
    check("yes registers, then asks what he took", r["state"] == "ask")
    turn(db, "नहीं")
    check("customer was saved", db.query(Customer).filter_by(name="Rajesh Mehra").count() == 1)

    print("\n== yes and no in every language ==")
    before = get_balance(db, anil)
    for lang, (ys, ns, _) in CASES.items():
        db.get(Shop, 1).language = lang
        db.commit()
        SESSIONS.pop(1, None)
        print(f"-- {lang}")
        r = turn(db, "Anil Reddy took 50 rupees on credit")
        r = turn(db, ys[0])
        check(f"{lang}: spoken yes saves", r["state"] == "saved")
        turn(db, "Anil Reddy took 50 rupees on credit")
        r = turn(db, ns[0])
        check(f"{lang}: spoken no cancels", r["state"] == "cancelled")
    check("11 yes-es saved exactly 11 times", get_balance(db, anil) == before + 11 * 50)

print(f"\n{sum(ok)}/{len(ok)} passed")