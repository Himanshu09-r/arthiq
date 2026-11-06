"""Clean demo state. STOP uvicorn first (Windows locks the db file).
   python demo_reset.py         -> seed + demo history (cash 8000, stock alerts)
   python demo_reset.py plain   -> seed only (original stock numbers)"""
import os
import subprocess
import sys

DB = "arthiq.db"
if os.path.exists(DB):
    try:
        os.remove(DB)
    except PermissionError:
        print("Cannot delete arthiq.db. Stop uvicorn (Ctrl+C) and run this again.")
        sys.exit(1)


def run(args):
    if subprocess.run([sys.executable] + args).returncode != 0:
        print("FAILED:", " ".join(args))
        sys.exit(1)


run(["-c", "from app.db.models import Base; from app.db.session import engine; Base.metadata.create_all(engine)"])
run(["-m", "app.db.seed"])
if "plain" not in sys.argv:
    run(["demo_history.py"])
print("\nDemo state ready. Start the server: uvicorn app.api.main:app --reload")
print("(the demo clock resets whenever the server restarts)")