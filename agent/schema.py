from typing import Optional
from pydantic import BaseModel, field_validator


class ItemLine(BaseModel):
    name: str
    qty: float = 1
    unit: Optional[str] = None


class Extraction(BaseModel):
    intent: str = "other"          # add_credit | record_payment | add_customer | other
    customer_ref: Optional[str] = None
    items: Optional[list[ItemLine]] = None
    amount: Optional[int] = None
    corrected_from: Optional[int] = None
    locality: Optional[str] = None
    phone: Optional[str] = None
    language: Optional[str] = None
    credit_limit: Optional[int] = None

    @field_validator("phone", mode="before")
    @classmethod
    def _phone_to_str(cls, v):
        return None if v is None else str(v)