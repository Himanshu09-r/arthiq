"""Voice alerts for the shopkeeper. Stored in the append-only audit table (tool='shop_alert')."""
from app.db.models import ActionAudit
from app.engine import clock
from app.voice.templates_collect import cx, lang_used


def push_alert(db, shop, key: str, now=None, **kw) -> str:
    text = cx(shop.language, key, **kw)
    db.add(ActionAudit(shop_id=shop.id, actor="system", tool="shop_alert",
                       arguments={"key": key, "text": text, "lang": lang_used(shop.language)},
                       rule_decision="allowed", timestamp=now or clock.now()))
    return text