"""One-time, non-destructive copy from an existing ARTHIQ SQLite DB to Neon/PostgreSQL.

Set SOURCE_DATABASE_URL=sqlite:////absolute/path/to/arthiq.db and DATABASE_URL=your Neon URL.
The destination must be empty. Run after installing requirements with: python migrate_sqlite_to_postgres.py
"""
import os
from sqlalchemy import create_engine, select, func, text, Integer
from app.db.models import Base
from app.db.migrate import run_migrations


def normalize(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def main():
    source_url = os.getenv("SOURCE_DATABASE_URL", "sqlite:///arthiq.db")
    target_url = os.getenv("DATABASE_URL", "")
    if not target_url:
        raise SystemExit("ERROR: Set DATABASE_URL to your Neon PostgreSQL connection string.")
    source = create_engine(source_url, connect_args={"check_same_thread": False} if source_url.startswith("sqlite") else {})
    target = create_engine(normalize(target_url), pool_pre_ping=True)

    # Bring both sides to the current model schema using the project's safe migrations.
    # This is additive/backfill work; it does not drop existing tables or rows.
    run_migrations(source)
    Base.metadata.create_all(target)
    run_migrations(target)
    tables = [t for t in Base.metadata.sorted_tables if t.name != "schema_migrations"]

    with target.connect() as conn:
        nonempty = []
        for table in tables:
            if table.name in conn.dialect.get_table_names(conn):
                count = conn.execute(select(func.count()).select_from(table)).scalar_one()
                if count:
                    nonempty.append(f"{table.name} ({count})")
        if nonempty:
            raise SystemExit("Destination is not empty; refusing to overwrite/duplicate data: " + ", ".join(nonempty))

    copied = {}
    with source.connect() as src, target.begin() as dst:
        for table in tables:
            if not src.dialect.has_table(src, table.name):
                continue
            rows = src.execute(select(table)).mappings().all()
            if rows:
                dst.execute(table.insert(), [dict(row) for row in rows])
            copied[table.name] = len(rows)

    # Explicitly copied integer IDs must advance PostgreSQL identity/serial sequences.
    quote = target.dialect.identifier_preparer.quote
    with target.begin() as conn:
        for table in tables:
            pk_cols = list(table.primary_key.columns)
            if len(pk_cols) != 1:
                continue
            pk = pk_cols[0]
            if pk.name != "id" or not isinstance(pk.type, Integer):
                continue
            table_q, col_q = quote(table.name), quote(pk.name)
            try:
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                    f"COALESCE(MAX({col_q}), 1), MAX({col_q}) IS NOT NULL) FROM {table_q}"
                ))
            except Exception:
                # Tables without a serial sequence (e.g. string primary keys) need no adjustment.
                pass

    print("SQLite → PostgreSQL copy completed:")
    for name, count in copied.items():
        if count:
            print(f"  {name}: {count} rows")
    print("Keep the original SQLite file unchanged until the Neon deployment is verified.")
    source.dispose(); target.dispose()

if __name__ == "__main__":
    main()
