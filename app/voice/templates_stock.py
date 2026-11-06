"""Voice wording for stock-in confirmation and inventory clarifications."""


def n(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(x)) if x.is_integer() else f"{x:.2f}".rstrip("0").rstrip(".")


_UNITS = {
    "hi-IN": {"kg": "किलो", "g": "ग्राम", "litre": "लीटर", "ml": "मिलीलीटर", "piece": "पीस",
              "packet": "पैकेट", "dozen": "दर्जन", "bottle": "बोतल", "box": "डिब्बे", "bag": "बोरी", "jar": "जार"},
    "en-IN": {"kg": "kg", "g": "g", "litre": "litres", "ml": "ml", "piece": "pieces",
              "packet": "packets", "dozen": "dozen", "bottle": "bottles", "box": "boxes", "bag": "bags", "jar": "jars"},
    "mr-IN": {"kg": "किलो", "g": "ग्रॅम", "litre": "लिटर", "ml": "मिलीलीटर", "piece": "नग", "packet": "पॅकेट", "dozen": "डझन", "bottle": "बाटल्या", "box": "बॉक्स", "bag": "पिशव्या", "jar": "जार"},
    "gu-IN": {"kg": "કિલો", "g": "ગ્રામ", "litre": "લિટર", "ml": "મિલીલીટર", "piece": "નંગ", "packet": "પેકેટ", "dozen": "ડઝન", "bottle": "બોટલ", "box": "બોક્સ", "bag": "થેલી", "jar": "જાર"},
}

_TEXT = {
    "hi-IN": {
        "st_ask_items": "कौन सा सामान आया है और कितनी मात्रा में?",
        "st_err_qty": "{name} की मात्रा सही नहीं है। कृपया दोबारा बताइए।",
        "st_err_unit_unknown": "माप की इकाई {unit} समझ नहीं आई। किलो, ग्राम, लीटर या पैकेट में बताइए।",
        "st_err_unit": "{item} का स्टॉक {unit} में रखा जाता है, लेकिन आपने {spoken} कहा। मात्रा और इकाई फिर से बताइए।",
        "st_ask_maybe": "क्या आपका मतलब {option} है?",
        "st_ask_which": "{name} से आपका मतलब कौन सा सामान है: {options}?",
        "st_ask_unknown": "{name} कैटलॉग में नहीं मिला। क्या यह नया प्रोडक्ट है? हाँ या नहीं बताइए।",
        "st_ask_newprice": "नया सामान {name} किस इकाई में रखना है और उसका बिक्री मूल्य कितना है? उदाहरण: पैकेट, 20 रुपये।",
        "st_x_approx": " (लगभग {spoken}, इसे {unit} में बदला है)",
        "st_x_price": " (खरीद रेट {price} रुपये प्रति {unit})",
        "st_x_new": " (नया सामान, बिक्री मूल्य {price} रुपये प्रति {unit})",
        "st_x_supplier": " सप्लायर {supplier} से।",
        "st_one": "{item} के {qty} {unit} आए हैं। पहले स्टॉक {prev} था, अब {new} होगा।{extra} क्या इसे दर्ज कर दूँ?",
        "st_line": "{item}: {qty} {unit}; पहले {prev}, अब {new}",
        "st_many": "{n} सामान आए हैं। {lines}।{extra} क्या सब दर्ज कर दूँ?",
        "st_saved_one": "{item} का स्टॉक अपडेट हो गया है। अब कुल {new} {unit} हैं।",
        "st_sline": "{item} अब {new} {unit}",
        "st_saved_many": "{n} सामान का स्टॉक अपडेट हो गया है। {lines}।",
        "st_failed": "स्टॉक अपडेट नहीं हो पाया। कृपया दोबारा कोशिश करें।",
    },
    "en-IN": {
        "st_ask_items": "Which items arrived, and in what quantities?",
        "st_err_qty": "The quantity for {name} is invalid. Please say it again.",
        "st_err_unit_unknown": "I did not recognise the unit {unit}. Please use kg, gram, litre or packet.",
        "st_err_unit": "{item} is tracked in {unit}, but you said {spoken}. Please repeat the quantity and unit.",
        "st_ask_maybe": "Did you mean {option}?",
        "st_ask_which": "Which product did you mean by {name}: {options}?",
        "st_ask_unknown": "I could not find {name} in the catalogue. Is this a new product?",
        "st_ask_newprice": "What unit should I use for {name}, and what is its selling price? For example: packet, 20 rupees.",
        "st_x_approx": " (converted approximately from {spoken} to {unit})",
        "st_x_price": " (purchase rate {price} rupees per {unit})",
        "st_x_new": " (new product, selling price {price} rupees per {unit})",
        "st_x_supplier": " Supplier: {supplier}.",
        "st_one": "Received {qty} {unit} of {item}. Previous stock was {prev}; it will become {new}.{extra} Should I record it?",
        "st_line": "{item}: {qty} {unit}; previous {prev}, new {new}",
        "st_many": "Received {n} items. {lines}.{extra} Should I record all of them?",
        "st_saved_one": "Stock updated for {item}. The new total is {new} {unit}.",
        "st_sline": "{item}: now {new} {unit}",
        "st_saved_many": "Stock updated for {n} items. {lines}.",
        "st_failed": "I could not update the stock. Please try again.",
    },
}


def unit_say(lang, unit):
    language = lang if lang in _UNITS else "hi-IN"
    key = str(unit or "").strip().lower()
    return _UNITS[language].get(key, key)


def ts(lang, key, **kwargs):
    language = lang if lang in _TEXT else "hi-IN"
    template = _TEXT[language][key]
    return template.format(**kwargs)
