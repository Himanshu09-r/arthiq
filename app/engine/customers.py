"""Dynamic Customer Management Service.
Handles dynamic customer registration, duplicate detection, profile updates,
and customer disambiguation without modifying seed.py.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import select, or_, func
from rapidfuzz import fuzz

from app.db.models import Customer, Shop, ActionAudit
from app.engine.matching import _norm


class CustomerError(Exception):
    def __init__(self, code: str, message: str, **info):
        super().__init__(message)
        self.code = code
        self.message = message
        self.info = info


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Clean phone string to standard digits only."""
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits if digits else None


def check_duplicate_customer(
    db,
    shop_id: int,
    name: str,
    phone: Optional[str] = None,
    locality: Optional[str] = None,
    nicknames: Optional[list] = None
) -> dict:
    """Detect potential duplicate customers considering normalized name, phone, and locality.
    Similar names are identified as potential matches but NEVER automatically merged."""
    clean_phone = normalize_phone(phone)
    q_name = _norm(name)
    q_loc = _norm(locality) if locality else ""

    candidates = []
    custs = db.scalars(select(Customer).where(Customer.shop_id == shop_id, Customer.status != "deleted")).all()

    for c in custs:
        c_phone = normalize_phone(c.phone)
        alt_phone = normalize_phone(c.alternate_phone)
        c_loc = _norm(c.locality) if c.locality else ""

        # 1. Exact phone match -> High confidence duplicate
        if clean_phone and (clean_phone == c_phone or clean_phone == alt_phone):
            candidates.append({
                "customer_id": c.id,
                "name": c.name,
                "phone": c.phone,
                "locality": c.locality,
                "confidence": 100,
                "reason": "phone_exact_match"
            })
            continue

        # 2. Fuzzy name match
        all_names = [c.name] + list(c.nicknames or [])
        name_scores = [fuzz.ratio(q_name, _norm(n)) for n in all_names if n]
        best_name_score = max(name_scores) if name_scores else 0

        # If name is a close match (e.g. >= 85)
        if best_name_score >= 85:
            # Check locality
            loc_match = False
            if q_loc and c_loc:
                loc_score = fuzz.ratio(q_loc, c_loc)
                if loc_score >= 80:
                    loc_match = True

            if loc_match:
                candidates.append({
                    "customer_id": c.id,
                    "name": c.name,
                    "phone": c.phone,
                    "locality": c.locality,
                    "confidence": 90,
                    "reason": "name_and_locality_match"
                })
            elif best_name_score >= 95 and not clean_phone and not c_phone:
                # Same name and neither has phone
                candidates.append({
                    "customer_id": c.id,
                    "name": c.name,
                    "phone": c.phone,
                    "locality": c.locality,
                    "confidence": 80,
                    "reason": "identical_name_without_phone"
                })
            else:
                # Similar name in same shop: note as potential similar, but distinct
                candidates.append({
                    "customer_id": c.id,
                    "name": c.name,
                    "phone": c.phone,
                    "locality": c.locality,
                    "confidence": 60,
                    "reason": "similar_name"
                })

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    is_duplicate = any(c["confidence"] >= 85 for c in candidates)

    return {
        "is_duplicate": is_duplicate,
        "highest_confidence": candidates[0]["confidence"] if candidates else 0,
        "candidates": candidates
    }


def register_customer(
    db,
    shop_id: int,
    name: str,
    phone: Optional[str] = None,
    locality: Optional[str] = None,
    alternate_phone: Optional[str] = None,
    preferred_language: str = "hi-IN",
    nicknames: Optional[list] = None,
    credit_limit: int = 2000,
    message_opt_in: bool = True,
    check_duplicates: bool = True,
    allow_duplicate: bool = False
) -> Customer:
    """Register a new customer dynamically. IDs are generated automatically."""
    shop = db.get(Shop, shop_id)
    if not shop:
        raise CustomerError("shop_not_found", f"Shop {shop_id} does not exist")

    clean_name = (name or "").strip()
    if not clean_name:
        raise CustomerError("invalid_name", "Customer name cannot be empty")

    clean_phone = normalize_phone(phone)
    clean_alt_phone = normalize_phone(alternate_phone)

    if check_duplicates and not allow_duplicate:
        dup_result = check_duplicate_customer(db, shop_id, clean_name, clean_phone, locality, nicknames)
        if dup_result["is_duplicate"]:
            top = dup_result["candidates"][0]
            raise CustomerError(
                "duplicate_detected",
                f"Potential duplicate customer detected ({top['name']}, id={top['customer_id']}) by {top['reason']}",
                candidates=dup_result["candidates"]
            )

    # Build initial nicknames list (ensures first name is included)
    nicks = list(nicknames or [])
    first_name = clean_name.split()[0].lower()
    if first_name not in [n.lower() for n in nicks]:
        nicks.append(first_name)

    now = datetime.now()
    cust = Customer(
        shop_id=shop_id,
        name=clean_name,
        phone=clean_phone,
        alternate_phone=clean_alt_phone,
        locality=locality.strip() if locality else None,
        preferred_language=preferred_language or shop.language,
        nicknames=nicks,
        credit_limit=max(0, int(credit_limit)),
        message_opt_in=bool(message_opt_in),
        status="active",
        trust_score=50,
        paused=False,
        created_at=now,
        updated_at=now
    )
    db.add(cust)
    db.flush()

    db.add(ActionAudit(
        shop_id=shop_id,
        actor="system",
        tool="register_customer",
        arguments={
            "customer_id": cust.id,
            "name": cust.name,
            "phone": cust.phone,
            "locality": cust.locality,
            "credit_limit": cust.credit_limit
        },
        rule_decision="allowed",
        timestamp=now
    ))
    db.commit()
    return cust


def get_customer_by_id(db, customer_id: int):
    """Retrieve a customer by its primary key.
    Returns the Customer ORM instance or raises CustomerError if not found.
    """
    cust = db.get(Customer, customer_id)
    if not cust:
        raise CustomerError("customer_not_found", f"Customer {customer_id} not found")
    return cust


def update_customer(
    db,
    customer_id: int,
    shop_id: int,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    locality: Optional[str] = None,
    alternate_phone: Optional[str] = None,
    preferred_language: Optional[str] = None,
    nicknames: Optional[list] = None,
    credit_limit: Optional[int] = None,
    message_opt_in: Optional[bool] = None,
    paused: Optional[bool] = None,
    status: Optional[str] = None
) -> Customer:
    """Update existing customer details while preserving audit and consent rules."""
    cust = db.get(Customer, customer_id)
    if not cust or cust.shop_id != shop_id:
        raise CustomerError("customer_not_found", f"Customer {customer_id} not found in shop {shop_id}")

    if name is not None:
        clean_name = name.strip()
        if clean_name:
            cust.name = clean_name
    if phone is not None:
        cust.phone = normalize_phone(phone)
    if alternate_phone is not None:
        cust.alternate_phone = normalize_phone(alternate_phone)
    if locality is not None:
        cust.locality = locality.strip() if locality else None
    if preferred_language is not None:
        cust.preferred_language = preferred_language
    if nicknames is not None:
        cust.nicknames = list(nicknames)
    if credit_limit is not None:
        cust.credit_limit = max(0, int(credit_limit))
    if message_opt_in is not None:
        cust.message_opt_in = bool(message_opt_in)
    if paused is not None:
        cust.paused = bool(paused)
    if status is not None:
        cust.status = status

    now = datetime.now()
    cust.updated_at = now
    db.add(ActionAudit(
        shop_id=shop_id,
        actor="shopkeeper",
        tool="update_customer",
        arguments={"customer_id": cust.id, "name": cust.name, "credit_limit": cust.credit_limit},
        rule_decision="allowed",
        timestamp=now
    ))
    db.commit()
    return cust


def list_customers(
    db,
    shop_id: int,
    query: Optional[str] = None,
    locality: Optional[str] = None,
    status: str = "active",
    limit: int = 100
) -> list[Customer]:
    """Search and retrieve customers with optional filtering."""
    stmt = select(Customer).where(Customer.shop_id == shop_id)
    if status:
        stmt = stmt.where(Customer.status == status)
    if locality:
        stmt = stmt.where(Customer.locality.ilike(f"%{locality}%"))
    if query:
        q_norm = _norm(query)
        custs = db.scalars(stmt).all()
        scored = []
        for c in custs:
            s_name = max(fuzz.ratio(q_norm, _norm(n)) for n in [c.name] + list(c.nicknames or []))
            s_phone = 100 if query in (c.phone or "") else 0
            best = max(s_name, s_phone)
            if best >= 60:
                scored.append((best, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]

    return list(db.scalars(stmt.order_by(Customer.name).limit(limit)).all())

