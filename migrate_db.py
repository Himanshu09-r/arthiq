import json, os, sqlite3
from datetime import datetime, date
from sqlalchemy import create_engine
from app.db.models import Base

url = os.getenv("DATABASE_URL", "sqlite:///arthiq.db")
path = url.replace("sqlite:///", "")
engine = create_engine(url)

Base.metadata.create_all(engine)          # creates any missing TABLES only
con = sqlite3.connect(path)

added = 0
for table in Base.metadata.sorted_tables:
    existing = {r[1] for r in con.execute(f"PRAGMA table_info({table.name})")}
    for col in table.columns:
        if col.name in existing:
            continue
        ddl = col.type.compile(dialect=engine.dialect)
        con.execute(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}")
        added += 1
        print(f"added column: {table.name}.{col.name} ({ddl})")
        d = col.default                    # fill old rows with the model's default
        if d is not None and not col.primary_key:
            val = d.arg(None) if d.is_callable else d.arg
            if isinstance(val, (dict, list)):
                val = json.dumps(val)
            elif isinstance(val, datetime):
                val = val.isoformat(sep=" ")
            elif isinstance(val, date):
                val = val.isoformat()
            con.execute(f"UPDATE {table.name} SET {col.name} = ? WHERE {col.name} IS NULL", (val,))

con.execute("UPDATE customers SET customer_code = printf('CUST-%04d', id) WHERE customer_code IS NULL")
con.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_code ON customers(customer_code)")
con.commit()

print(f"\ndone: {added} column(s) added")
print("customers:", con.execute("SELECT id, name, customer_code, status FROM customers").fetchall())