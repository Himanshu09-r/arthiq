"""Preview/apply the bundled demo kirana catalogue to a shop.

Example:
  python import_catalogue.py --shop-id 1                 # preview only
  python import_catalogue.py --shop-id 1 --apply         # add missing products
  python import_catalogue.py --shop-id 1 --apply --update-prices

The CSV uses the exact six-column format. SKU, category, pack size and aliases live in
an adjacent JSON metadata file, not in extra CSV columns. This catalogue loader seeds
product metadata only; use the dashboard stock-import flow to record received quantities.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.db.session import SessionLocal, init_db
from app.db.models import Shop
from app.engine.products import find_existing_product, register_product

DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "arthiq_item_price_list.csv"
CSV_HEADERS = ["name", "unit", "price", "cost_price", "stock_qty", "reorder_level"]


def _number(value: str, field: str, line: int, required: bool = False, default=None):
    raw = (value or "").strip().replace(",", "")
    if not raw:
        if required:
            raise ValueError(f"Row {line}: {field} is required")
        return default
    try:
        number = float(raw)
    except ValueError as exc:
        raise ValueError(f"Row {line}: {field} must be numeric") from exc
    if number < 0 or (required and number <= 0):
        raise ValueError(f"Row {line}: {field} must be {'greater than zero' if required else 'zero or greater'}")
    return number


def _metadata_path(path: Path) -> Path:
    return path.with_name(path.stem + "_metadata.json")


def load_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [str(h or "").strip().lower() for h in (reader.fieldnames or [])]
        if headers != CSV_HEADERS:
            raise ValueError("CSV headers must be exactly, and in order: " + ",".join(CSV_HEADERS))
        metadata_path = _metadata_path(path)
        metadata = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError(f"{metadata_path.name} must contain a JSON object")
        rows = []
        seen_names = set()
        for line, raw in enumerate(reader, start=2):
            row = {str(k).strip().lower(): (v or "").strip() for k, v in (raw or {}).items() if k}
            if not any(row.values()):
                continue
            name = row["name"]
            unit = row["unit"].strip().lower()
            if not name or not unit:
                raise ValueError(f"Row {line}: name and unit are required")
            key = name.casefold()
            if key in seen_names:
                raise ValueError(f"Row {line}: duplicate product name '{name}'")
            seen_names.add(key)
            selling = _number(row["price"], "price", line, required=True)
            cost = _number(row["cost_price"], "cost_price", line, default=0)
            incoming = _number(row["stock_qty"], "stock_qty", line, default=0)
            reorder = _number(row["reorder_level"], "reorder_level", line, default=5)
            if incoming:
                raise ValueError(f"Row {line}: bundled catalogue stock_qty must be blank or 0; use the stock-import screen to receive stock")
            extra = metadata.get(key, {})
            if not isinstance(extra, dict):
                raise ValueError(f"Metadata for '{name}' must be an object")
            aliases = extra.get("aliases", [])
            if not isinstance(aliases, list) or any(not isinstance(x, str) for x in aliases):
                raise ValueError(f"Metadata aliases for '{name}' must be a list of strings")
            rows.append({
                "item_name": name, "unit": unit, "selling_price": str(int(round(selling))),
                "purchase_price": str(int(round(cost))), "reorder_level": str(reorder),
                "stock_qty": "", "sku": extra.get("sku"),
                "category": extra.get("category") or "General", "pack_size": extra.get("pack_size"),
                "aliases": "|".join(aliases), "supplier_name": extra.get("supplier_name"),
                "expiry_date": extra.get("expiry_date"),
            })
        if not rows:
            raise ValueError("CSV has no product rows")
        return rows


def run(shop_id: int, path: Path, apply: bool, update_prices: bool) -> dict:
    rows = load_rows(path)
    init_db()
    with SessionLocal() as db:
        if not db.get(Shop, shop_id):
            raise ValueError(f"Shop {shop_id} does not exist")
        created = updated = skipped = 0
        preview = []
        try:
            for row in rows:
                aliases = [part.strip() for part in row["aliases"].split("|") if part.strip()]
                item = find_existing_product(db, shop_id, row["item_name"], row["sku"], row["unit"])
                if item is None:
                    # Check for a same-name SKU/unit mismatch before registering a duplicate.
                    name_match = find_existing_product(db, shop_id, row["item_name"], None, None)
                    if name_match is not None:
                        preview.append(f"SKIP unit mismatch: {row['item_name']} ({name_match.unit} vs {row['unit']})")
                        skipped += 1
                        continue
                    preview.append(f"NEW {row['item_name']} — ₹{row['selling_price']} / unit")
                    if apply:
                        register_product(
                            db, shop_id, row["item_name"], row["unit"], int(float(row["selling_price"])),
                            cost_price=int(float(row["purchase_price"] or 0)), sku=row["sku"],
                            category=row["category"] or "General", pack_size=row["pack_size"] or None,
                            stock_qty=0, reorder_level=float(row["reorder_level"] or 5), aliases=aliases,
                            allow_existing=False, commit=False,
                        )
                    created += 1
                else:
                    if item.unit.casefold() != row["unit"].casefold():
                        preview.append(f"SKIP unit mismatch: {row['item_name']} ({item.unit} vs {row['unit']})")
                        skipped += 1
                        continue
                    preview.append(f"EXISTS {item.name} — stock remains {item.stock_qty} {item.unit}")
                    if apply:
                        item.aliases = list(dict.fromkeys((item.aliases or []) + aliases))
                        item.sku = item.sku or row["sku"]
                        item.category = row["category"] or item.category
                        item.pack_size = item.pack_size or row["pack_size"] or None
                        item.reorder_level = float(row["reorder_level"] or item.reorder_level or 5)
                        if update_prices:
                            item.price = int(float(row["selling_price"]))
                            if row["purchase_price"]:
                                item.cost_price = int(float(row["purchase_price"]))
                    updated += 1
            if apply:
                db.commit()
        except Exception:
            db.rollback()
            raise
        return {"total": len(rows), "created": created, "matched": updated,
                "skipped": skipped, "preview": preview}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=int, default=1)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--apply", action="store_true", help="commit changes; otherwise preview only")
    parser.add_argument("--update-prices", action="store_true", help="also apply CSV prices to matched items")
    args = parser.parse_args()
    result = run(args.shop_id, args.csv, args.apply, args.update_prices)
    print(("APPLIED" if args.apply else "PREVIEW ONLY") + f": {result['total']} rows")
    print(f"New: {result['created']} | Matched: {result['matched']} | Skipped: {result['skipped']}")
    for line in result["preview"]:
        print("- " + line)
    if not args.apply:
        print("No database changes made. Add --apply after reviewing the preview.")


if __name__ == "__main__":
    main()
