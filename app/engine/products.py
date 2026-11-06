"""Dynamic Product Catalogue Service.
Handles dynamic product registration, SKU management, category organization,
multilingual alias enrichment, and product updates.
"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import select
from rapidfuzz import fuzz

from app.db.models import Item, Shop, Supplier, ActionAudit
from app.engine.matching import _norm


class ProductError(Exception):
    def __init__(self, code: str, message: str, **info):
        super().__init__(message)
        self.code = code
        self.message = message
        self.info = info


def generate_sku(shop_id: int, name: str, category: Optional[str] = None) -> str:
    """Generate a clean human-readable SKU if none is provided."""
    prefix = (category or "GEN")[:3].upper()
    clean_name = "".join(ch for ch in name if ch.isalnum()).upper()[:4]
    ts = datetime.now().strftime("%f")[:3]
    return f"{prefix}-{clean_name}-{shop_id}{ts}"


def find_existing_product(
    db,
    shop_id: int,
    name: str,
    sku: Optional[str] = None,
    unit: Optional[str] = None
) -> Optional[Item]:
    """Find if product already exists by exact SKU or exact/high-confidence name match."""
    if sku:
        item = db.scalar(select(Item).where(Item.shop_id == shop_id, Item.sku == sku))
        if item:
            return item

    q_norm = _norm(name)
    items = db.scalars(select(Item).where(Item.shop_id == shop_id, Item.status != "deleted")).all()
    for it in items:
        # Check SKU match
        if sku and it.sku and it.sku.upper() == sku.upper():
            return it
        # Check name or aliases exact match
        for alias in [it.name] + list(it.aliases or []):
            if _norm(alias) == q_norm:
                if not unit or not it.unit or unit.lower() == it.unit.lower():
                    return it
    return None


def register_product(
    db,
    shop_id: int,
    name: str,
    unit: str,
    price: int,
    cost_price: int = 0,
    sku: Optional[str] = None,
    category: str = "General",
    pack_size: Optional[str] = None,
    stock_qty: float = 0.0,
    reorder_level: float = 5.0,
    aliases: Optional[list] = None,
    multilingual_names: Optional[dict] = None,
    preferred_supplier_id: Optional[int] = None,
    expiry_date: Optional[date] = None,
    allow_existing: bool = True,
    commit: bool = True
) -> Item:
    """Register a new product in the shop catalogue without modifying seed.py.
    Recognizes existing products to prevent duplicates."""
    shop = db.get(Shop, shop_id)
    if not shop:
        raise ProductError("shop_not_found", f"Shop {shop_id} does not exist")

    clean_name = (name or "").strip()
    if not clean_name:
        raise ProductError("invalid_name", "Product name cannot be empty")

    clean_unit = (unit or "").strip().lower()
    if not clean_unit:
        raise ProductError("invalid_unit", "Unit is required (e.g. kg, packet, litre)")

    price = int(price)
    cost_price = int(cost_price)
    if price < 0 or cost_price < 0:
        raise ProductError("invalid_price", "Prices cannot be negative")

    # Check for existing product
    existing = find_existing_product(db, shop_id, clean_name, sku, clean_unit)
    if existing:
        if allow_existing:
            return existing
        raise ProductError("product_exists", f"Product '{existing.name}' already exists (id={existing.id})", item_id=existing.id)

    # Validate supplier if provided
    if preferred_supplier_id:
        supplier = db.get(Supplier, preferred_supplier_id)
        if not supplier or supplier.shop_id != shop_id:
            preferred_supplier_id = None

    # Merge multilingual names into aliases for fuzzy matching
    alias_list = list(aliases or [])
    ml_dict = dict(multilingual_names or {})
    for lang_code, trans_name in ml_dict.items():
        if trans_name and trans_name not in alias_list:
            alias_list.append(trans_name)

    # Ensure lowercase name is in aliases if not already
    if clean_name.lower() not in [a.lower() for a in alias_list]:
        alias_list.append(clean_name.lower())

    final_sku = sku.strip() if sku else generate_sku(shop_id, clean_name, category)
    now = datetime.now()

    item = Item(
        shop_id=shop_id,
        name=clean_name,
        aliases=alias_list,
        unit=clean_unit,
        price=price,
        cost_price=cost_price,
        stock_qty=float(stock_qty),
        reorder_level=float(reorder_level),
        sku=final_sku,
        category=category.strip() if category else "General",
        pack_size=pack_size.strip() if pack_size else None,
        multilingual_names=ml_dict,
        preferred_supplier_id=preferred_supplier_id,
        expiry_date=expiry_date,
        status="active",
        created_at=now,
        updated_at=now
    )
    db.add(item)
    db.flush()

    # If initial stock > 0, record initial baseline movement
    if float(stock_qty) > 0:
        from app.db.models import InventoryMovement
        db.add(InventoryMovement(
            shop_id=shop_id,
            item_id=item.id,
            movement_type="STOCK_IN",
            quantity=float(stock_qty),
            previous_stock=0.0,
            new_stock=float(stock_qty),
            unit=clean_unit,
            purchase_price=cost_price,
            reference_tx_id=f"initial_reg_{item.id}",
            source="manual_adjustment",
            idempotency_key=f"init_stock_{item.id}",
            audit_info={"reason": "Initial stock at product registration"},
            timestamp=now
        ))

    db.add(ActionAudit(
        shop_id=shop_id,
        actor="system",
        tool="register_product",
        arguments={"item_id": item.id, "name": item.name, "sku": item.sku, "price": item.price, "stock": item.stock_qty},
        rule_decision="allowed",
        timestamp=now
    ))
    if commit:
        db.commit()
    return item


def update_product(
    db,
    item_id: int,
    shop_id: int,
    name: Optional[str] = None,
    price: Optional[int] = None,
    cost_price: Optional[int] = None,
    unit: Optional[str] = None,
    category: Optional[str] = None,
    pack_size: Optional[str] = None,
    sku: Optional[str] = None,
    reorder_level: Optional[float] = None,
    aliases: Optional[list] = None,
    multilingual_names: Optional[dict] = None,
    preferred_supplier_id: Optional[int] = None,
    expiry_date: Optional[date] = None,
    status: Optional[str] = None
) -> Item:
    """Update product details while keeping price and cost price separate."""
    item = db.get(Item, item_id)
    if not item or item.shop_id != shop_id:
        raise ProductError("product_not_found", f"Product {item_id} not found in shop {shop_id}")

    if name is not None:
        clean_name = name.strip()
        if clean_name:
            item.name = clean_name
    if price is not None:
        item.price = max(0, int(price))
    if cost_price is not None:
        item.cost_price = max(0, int(cost_price))
    if unit is not None:
        item.unit = unit.strip().lower()
    if category is not None:
        item.category = category.strip()
    if pack_size is not None:
        item.pack_size = pack_size.strip()
    if sku is not None:
        item.sku = sku.strip()
    if reorder_level is not None:
        item.reorder_level = max(0.0, float(reorder_level))
    if aliases is not None:
        item.aliases = list(aliases)
    if multilingual_names is not None:
        item.multilingual_names = dict(multilingual_names)
        # merge into aliases
        for _, t in item.multilingual_names.items():
            if t and t not in (item.aliases or []):
                item.aliases.append(t)
    if preferred_supplier_id is not None:
        item.preferred_supplier_id = preferred_supplier_id
    if expiry_date is not None:
        item.expiry_date = expiry_date
    if status is not None:
        item.status = status

    now = datetime.now()
    item.updated_at = now
    db.add(ActionAudit(
        shop_id=shop_id,
        actor="shopkeeper",
        tool="update_product",
        arguments={"item_id": item.id, "name": item.name, "price": item.price, "cost_price": item.cost_price},
        rule_decision="allowed",
        timestamp=now
    ))
    db.commit()
    return item


def list_products(
    db,
    shop_id: int,
    category: Optional[str] = None,
    status: str = "active",
    query: Optional[str] = None,
    limit: int = 100
) -> list[Item]:
    """Retrieve catalog products with optional filters."""
    stmt = select(Item).where(Item.shop_id == shop_id)
    if status:
        stmt = stmt.where(Item.status == status)
    if category:
        stmt = stmt.where(Item.category == category)
    if query:
        q_norm = _norm(query)
        items = db.scalars(stmt).all()
        scored = []
        for it in items:
            best = max(fuzz.ratio(q_norm, _norm(a)) for a in [it.name] + list(it.aliases or []))
            if best >= 60:
                scored.append((best, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:limit]]

    return list(db.scalars(stmt.order_by(Item.name).limit(limit)).all())

