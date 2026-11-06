from pydantic import ValidationError
from app.db.models import Customer, Item
from app.agent.llm import chat_json, LLMError
from app.agent.schema import Extraction
from app.languages import SUPPORTED

PROMPT = """You extract shop ledger commands from a shopkeeper's spoken sentence.
The sentence is a speech transcript and may be Hindi, Hinglish, Marathi, Gujarati,
another Indian language, or English. It may start with the word "Arthiq". Ignore that.
Reply with ONE JSON object only. No other text.

{
 "intent": "add_credit" | "record_payment" | "add_customer" | "stock_in" | "other",
 "customer_ref": string or null,
 "items": [ {"name": string, "qty": number, "unit": string or null, "price": number or null} ],
 "supplier": string or null,
 "amount": integer or null,
 "corrected_from": integer or null,
 "locality": string or null,
 "phone": string or null,
 "language": string or null,
 "credit_limit": integer or null
}

Rules:
- add_credit: a customer took goods or money on credit (udhar / udhaar / उधार / ઉધાર ...).
- stock_in: the shopkeeper received goods for inventory (aaya / aaye / stock mein add / received / माल आया).
  Extract every received product, its quantity and unit. This is NOT a customer sale or credit transaction.
  Set supplier only when the supplier is explicitly named. Set items[].price only when a purchase rate is explicitly spoken.
- record_payment: a customer paid money back (de diye / diye / दिले / આપ્યા ...).
- add_customer: the shopkeeper wants to REGISTER A NEW customer (naya customer, add a new
  customer, नया ग्राहक जोड़ो, नवीन ग्राहक, નવો ગ્રાહક ...).
  * customer_ref = the new person's full name in Roman letters.
  * locality = the area, colony or neighbourhood in Roman letters (e.g. "Patel Nagar"),
    without words like wale, wali, ke paas, ला, ના. null if not said.
  * phone = the digits exactly as spoken. null if not said.
  * language = one of the language codes below, only if the shopkeeper names the language
    to use with this customer. Otherwise null.
  * credit_limit = integer, only if a limit is stated.
  * items / amount: only if goods or money on credit are ALSO mentioned in the same sentence.
  * IMPORTANT: if the sentence says "new customer" / "naya customer" the intent is
    add_customer even when items are also mentioned.
- customer_ref (other intents): the person's name in Roman letters without endings like
  ji, ne, ने, ला, એ. If the surname is spoken, include it.
- items[].name: the best matching name from the CATALOGUE below (use the first name listed
  for the item). Do not invent items for credit sales; for a stock_in command, preserve an unknown
  spoken product name so the shopkeeper can confirm whether it is a new product.
- Convert number words to digits (do=2, ek=1, aadha=0.5, paanch sau=500, दोन=2, બે=2).
- amount: the rupee amount if one is stated, else null.
- If the speaker corrects themselves ("500 nahi, 300"), amount is the FINAL value (300)
  and corrected_from is the earlier value (500).
- If unsure about a field, use null. If the sentence is none of the above, intent is "other".
<<HINT>>
LANGUAGE CODES: <<LANGS>>

CUSTOMERS: <<CUSTOMERS>>

CATALOGUE (name (aliases) unit):
<<ITEMS>>
"""


def _context(db, shop_id):
    custs = db.query(Customer).filter_by(shop_id=shop_id).all()
    items = db.query(Item).filter_by(shop_id=shop_id).all()
    c_txt = ", ".join(f"{c.name} ({c.locality})" if getattr(c, "locality", None) else c.name
                      for c in custs)
    i_txt = "\n".join(f"- {i.name} ({', '.join(i.aliases)}) {i.unit}" for i in items)
    return c_txt, i_txt


def extract(db, shop_id: int, transcript: str, hint: str = "") -> Extraction:
    c_txt, i_txt = _context(db, shop_id)
    langs = ", ".join(f"{l.code}={l.name}" for l in SUPPORTED.values())
    system = (PROMPT.replace("<<CUSTOMERS>>", c_txt).replace("<<ITEMS>>", i_txt)
              .replace("<<LANGS>>", langs)
              .replace("<<HINT>>", ("\nCONTEXT: " + hint) if hint else ""))
    for _ in range(2):
        try:
            return Extraction.model_validate(chat_json(system, transcript))
        except (ValidationError, LLMError):
            continue
    return Extraction(intent="other")