from app.db.session import SessionLocal
from app.agent.extract import extract

db = SessionLocal()
for t in ["ARTHIQ, add a new customer Rajesh Mehra, Gandhi Nagar wale.",
          "naya customer Neha Verma, Sector Five, ek kilo cheeni udhar"]:
    print(t)
    print("  ->", extract(db, 1, t), "\n")