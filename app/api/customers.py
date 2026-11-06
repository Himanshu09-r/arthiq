import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Shop, Customer, ActionAudit
from app.engine.registration import check_registration
from app.tools import ledger_tools as L

router = APIRouter()


def _row(db, c):
    return {"id": c.id, "customer_code": c.customer_code, "name": c.name, "locality": c.locality,
            "phone": c.phone, "language": c.preferred_language, "credit_limit": c.credit_limit,
            "balance": L.get_balance(db, c.id)}


@router.get("/customers-ui")
def customers_ui():
    return FileResponse("web/customers.html")


@router.get("/customers")
def list_customers(shop_id: int = 1, db: Session = Depends(get_db)):
    rows = db.query(Customer).filter_by(shop_id=shop_id).order_by(Customer.id).all()
    return [_row(db, c) for c in rows]


@router.get("/customers/{cid}/history")
def history(cid: int, shop_id: int = 1, db: Session = Depends(get_db)):
    try:
        return L.customer_history(db, shop_id, cid)
    except L.ToolError:
        raise HTTPException(404, "Customer not found")


class NewCustomer(BaseModel):
    shop_id: int = 1
    name: str
    locality: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    credit_limit: Optional[int] = None


@router.post("/customers")
def create_customer(body: NewCustomer, db: Session = Depends(get_db)):
    shop = db.get(Shop, body.shop_id)
    if not shop:
        raise HTTPException(404, "Shop not found")
    chk = check_registration(db, body.shop_id, body.name, body.locality, body.phone,
                             body.language, body.credit_limit, shop.language)
    if chk.status == "error":
        raise HTTPException(400, chk.code)
    if chk.status == "duplicate":
        raise HTTPException(409, {"duplicate_of": chk.duplicate.id, "name": chk.duplicate.name,
                                  "locality": chk.duplicate.locality})
    r = L.register_customer(db, body.shop_id, chk.name, chk.locality, chk.phone,
                            chk.language, chk.credit_limit, uuid.uuid4().hex)
    return _row(db, db.get(Customer, r["customer_id"]))


class LimitIn(BaseModel):
    limit: int


@router.patch("/customers/{cid}/limit")
def set_limit(cid: int, body: LimitIn, shop_id: int = 1, db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if not c or c.shop_id != shop_id:
        raise HTTPException(404, "Customer not found")
    if not 100 <= body.limit <= 100000:
        raise HTTPException(400, "Limit must be between 100 and 100000")
    old, c.credit_limit = c.credit_limit, body.limit
    db.add(ActionAudit(shop_id=shop_id, actor="shopkeeper", tool="set_credit_limit",
                       arguments={"customer_id": cid, "from": old, "to": body.limit}))
    db.commit()
    return _row(db, c)