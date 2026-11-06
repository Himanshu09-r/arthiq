import re

KEYS = {"rb_credit_items", "rb_credit_amount", "rb_payment", "saved_credit",
        "saved_payment", "which_customer", "err_customer_unknown", "err_item_unknown",
        "err_low_stock", "err_limit", "err_overpay", "err_generic", "cancelled"}

TEMPLATES = {
 "en-IN": {
  "rb_credit_items": "{name}, {total} rupees on credit: {items}. Is that correct?",
  "rb_credit_amount": "{name}, {total} rupees on credit. Is that correct?",
  "rb_payment": "{name} paid {amount} rupees. {balance} rupees remaining. Is that correct?",
  "saved_credit": "Added {total} rupees to {name}'s account. Total due is {balance} rupees.",
  "saved_payment": "Recorded {amount} rupees from {name}. {balance} rupees remaining.",
  "which_customer": "Which {name}? {options}?",
  "err_customer_unknown": "I could not find a customer named {name}.",
  "err_item_unknown": "I could not find the item {name}.",
  "err_low_stock": "Only {have} of {item} left in stock.",
  "err_limit": "The credit limit is {limit} rupees. This would exceed it.",
  "err_overpay": "Only {balance} rupees is due.",
  "err_generic": "Sorry, I did not understand. Please say it again.",
  "cancelled": "Okay, cancelled. Please say it again."},
 "hi-IN": {
  "rb_credit_items": "{name}, {total} रुपये उधार: {items}. ठीक है?",
  "rb_credit_amount": "{name}, {total} रुपये उधार. ठीक है?",
  "rb_payment": "{name} ने {amount} रुपये दिए. बाकी {balance} रुपये. ठीक है?",
  "saved_credit": "{name} के खाते में {total} रुपये लिख दिए. कुल बाकी {balance} रुपये.",
  "saved_payment": "{name} के {amount} रुपये दर्ज हो गए. बाकी {balance} रुपये.",
  "which_customer": "कौन सा {name}? {options}?",
  "err_customer_unknown": "{name} नाम का ग्राहक नहीं मिला.",
  "err_item_unknown": "{name} सामान नहीं मिला.",
  "err_low_stock": "{item} सिर्फ {have} बचा है.",
  "err_limit": "उधार की सीमा {limit} रुपये है. इससे ज़्यादा नहीं हो सकता.",
  "err_overpay": "सिर्फ {balance} रुपये बाकी हैं.",
  "err_generic": "समझ नहीं आया. कृपया फिर से बोलिए.",
  "cancelled": "ठीक है, रद्द किया. फिर से बोलिए."},
 "mr-IN": {
  "rb_credit_items": "{name}, {total} रुपये उधार: {items}. बरोबर आहे का?",
  "rb_credit_amount": "{name}, {total} रुपये उधार. बरोबर आहे का?",
  "rb_payment": "{name} यांनी {amount} रुपये दिले. बाकी {balance} रुपये. बरोबर आहे का?",
  "saved_credit": "{name} यांच्या खात्यात {total} रुपये लिहिले. एकूण बाकी {balance} रुपये.",
  "saved_payment": "{name} यांचे {amount} रुपये नोंदवले. बाकी {balance} रुपये.",
  "which_customer": "कोणते {name}? {options}?",
  "err_customer_unknown": "{name} नावाचा ग्राहक सापडला नाही.",
  "err_item_unknown": "{name} वस्तू सापडली नाही.",
  "err_low_stock": "{item} फक्त {have} शिल्लक आहे.",
  "err_limit": "उधारीची मर्यादा {limit} रुपये आहे. यापेक्षा जास्त होऊ शकत नाही.",
  "err_overpay": "फक्त {balance} रुपये बाकी आहेत.",
  "err_generic": "समजले नाही. कृपया पुन्हा सांगा.",
  "cancelled": "ठीक आहे, रद्द केले. पुन्हा सांगा."},
 "gu-IN": {
  "rb_credit_items": "{name}, {total} રૂપિયા ઉધાર: {items}. બરાબર છે?",
  "rb_credit_amount": "{name}, {total} રૂપિયા ઉધાર. બરાબર છે?",
  "rb_payment": "{name} એ {amount} રૂપિયા આપ્યા. બાકી {balance} રૂપિયા. બરાબર છે?",
  "saved_credit": "{name} ના ખાતામાં {total} રૂપિયા લખ્યા. કુલ બાકી {balance} રૂપિયા.",
  "saved_payment": "{name} ના {amount} રૂપિયા નોંધાયા. બાકી {balance} રૂપિયા.",
  "which_customer": "કયા {name}? {options}?",
  "err_customer_unknown": "{name} નામનો ગ્રાહક મળ્યો નથી.",
  "err_item_unknown": "{name} વસ્તુ મળી નથી.",
  "err_low_stock": "{item} ફક્ત {have} બાકી છે.",
  "err_limit": "ઉધારની મર્યાદા {limit} રૂપિયા છે. તેનાથી વધુ થઈ શકતું નથી.",
  "err_overpay": "ફક્ત {balance} રૂપિયા બાકી છે.",
  "err_generic": "સમજાયું નહીં. કૃપા કરીને ફરી બોલો.",
  "cancelled": "ઠીક છે, રદ કર્યું. ફરી બોલો."},
 "bn-IN": {
  "rb_credit_items": "{name}, {total} টাকা ধার: {items}. ঠিক আছে?",
  "rb_credit_amount": "{name}, {total} টাকা ধার. ঠিক আছে?",
  "rb_payment": "{name} {amount} টাকা দিয়েছেন. বাকি {balance} টাকা. ঠিক আছে?",
  "saved_credit": "{name} এর খাতায় {total} টাকা লেখা হয়েছে. মোট বাকি {balance} টাকা.",
  "saved_payment": "{name} এর {amount} টাকা নথিভুক্ত হয়েছে. বাকি {balance} টাকা.",
  "which_customer": "কোন {name}? {options}?",
  "err_customer_unknown": "{name} নামে কোনো গ্রাহক পাওয়া যায়নি.",
  "err_item_unknown": "{name} জিনিসটি পাওয়া যায়নি.",
  "err_low_stock": "{item} মাত্র {have} আছে.",
  "err_limit": "ধারের সীমা {limit} টাকা. এর বেশি হবে না.",
  "err_overpay": "মাত্র {balance} টাকা বাকি আছে.",
  "err_generic": "বুঝতে পারিনি. আবার বলুন.",
  "cancelled": "ঠিক আছে, বাতিল করা হয়েছে. আবার বলুন."},
 "ta-IN": {
  "rb_credit_items": "{name}, {total} ரூபாய் கடன்: {items}. சரியா?",
  "rb_credit_amount": "{name}, {total} ரூபாய் கடன். சரியா?",
  "rb_payment": "{name} {amount} ரூபாய் கொடுத்தார். மீதி {balance} ரூபாய். சரியா?",
  "saved_credit": "{name} கணக்கில் {total} ரூபாய் எழுதப்பட்டது. மொத்த மீதி {balance} ரூபாய்.",
  "saved_payment": "{name} கொடுத்த {amount} ரூபாய் பதிவு செய்யப்பட்டது. மீதி {balance} ரூபாய்.",
  "which_customer": "எந்த {name}? {options}?",
  "err_customer_unknown": "{name} என்ற வாடிக்கையாளர் கிடைக்கவில்லை.",
  "err_item_unknown": "{name} என்ற பொருள் கிடைக்கவில்லை.",
  "err_low_stock": "{item} {have} மட்டுமே உள்ளது.",
  "err_limit": "கடன் வரம்பு {limit} ரூபாய். இதைவிட அதிகமாக முடியாது.",
  "err_overpay": "{balance} ரூபாய் மட்டுமே மீதி உள்ளது.",
  "err_generic": "புரியவில்லை. மீண்டும் சொல்லுங்கள்.",
  "cancelled": "சரி, ரத்து செய்யப்பட்டது. மீண்டும் சொல்லுங்கள்."},
 "te-IN": {
  "rb_credit_items": "{name}, {total} రూపాయలు అప్పు: {items}. సరైనదేనా?",
  "rb_credit_amount": "{name}, {total} రూపాయలు అప్పు. సరైనదేనా?",
  "rb_payment": "{name} {amount} రూపాయలు ఇచ్చారు. మిగిలినది {balance} రూపాయలు. సరైనదేనా?",
  "saved_credit": "{name} ఖాతాలో {total} రూపాయలు రాశాను. మొత్తం మిగిలినది {balance} రూపాయలు.",
  "saved_payment": "{name} ఇచ్చిన {amount} రూపాయలు నమోదు చేశాను. మిగిలినది {balance} రూపాయలు.",
  "which_customer": "ఏ {name}? {options}?",
  "err_customer_unknown": "{name} అనే కస్టమర్ దొరకలేదు.",
  "err_item_unknown": "{name} అనే వస్తువు దొరకలేదు.",
  "err_low_stock": "{item} {have} మాత్రమే ఉంది.",
  "err_limit": "అప్పు పరిమితి {limit} రూపాయలు. దీని కంటే ఎక్కువ కాదు.",
  "err_overpay": "{balance} రూపాయలు మాత్రమే మిగిలి ఉంది.",
  "err_generic": "అర్థం కాలేదు. దయచేసి మళ్లీ చెప్పండి.",
  "cancelled": "సరే, రద్దు చేశాను. మళ్లీ చెప్పండి."},
 "kn-IN": {
  "rb_credit_items": "{name}, {total} ರೂಪಾಯಿ ಸಾಲ: {items}. ಸರಿಯೇ?",
  "rb_credit_amount": "{name}, {total} ರೂಪಾಯಿ ಸಾಲ. ಸರಿಯೇ?",
  "rb_payment": "{name} {amount} ರೂಪಾಯಿ ಕೊಟ್ಟರು. ಬಾಕಿ {balance} ರೂಪಾಯಿ. ಸರಿಯೇ?",
  "saved_credit": "{name} ಖಾತೆಗೆ {total} ರೂಪಾಯಿ ಬರೆದಿದ್ದೇನೆ. ಒಟ್ಟು ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
  "saved_payment": "{name} ಕೊಟ್ಟ {amount} ರೂಪಾಯಿ ದಾಖಲಿಸಿದ್ದೇನೆ. ಬಾಕಿ {balance} ರೂಪಾಯಿ.",
  "which_customer": "ಯಾವ {name}? {options}?",
  "err_customer_unknown": "{name} ಎಂಬ ಗ್ರಾಹಕರು ಸಿಗಲಿಲ್ಲ.",
  "err_item_unknown": "{name} ಎಂಬ ವಸ್ತು ಸಿಗಲಿಲ್ಲ.",
  "err_low_stock": "{item} ಕೇವಲ {have} ಮಾತ್ರ ಇದೆ.",
  "err_limit": "ಸಾಲದ ಮಿತಿ {limit} ರೂಪಾಯಿ. ಇದಕ್ಕಿಂತ ಹೆಚ್ಚಾಗುವುದಿಲ್ಲ.",
  "err_overpay": "ಕೇವಲ {balance} ರೂಪಾಯಿ ಬಾಕಿ ಇದೆ.",
  "err_generic": "ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೆ ಹೇಳಿ.",
  "cancelled": "ಸರಿ, ರದ್ದು ಮಾಡಿದ್ದೇನೆ. ಮತ್ತೆ ಹೇಳಿ."},
 "ml-IN": {
  "rb_credit_items": "{name}, {total} രൂപ കടം: {items}. ശരിയാണോ?",
  "rb_credit_amount": "{name}, {total} രൂപ കടം. ശരിയാണോ?",
  "rb_payment": "{name} {amount} രൂപ നൽകി. ബാക്കി {balance} രൂപ. ശരിയാണോ?",
  "saved_credit": "{name} എന്നയാളുടെ അക്കൗണ്ടിൽ {total} രൂപ എഴുതി. ആകെ ബാക്കി {balance} രൂപ.",
  "saved_payment": "{name} നൽകിയ {amount} രൂപ രേഖപ്പെടുത്തി. ബാക്കി {balance} രൂപ.",
  "which_customer": "ഏത് {name}? {options}?",
  "err_customer_unknown": "{name} എന്ന പേരിൽ ഉപഭോക്താവിനെ കണ്ടില്ല.",
  "err_item_unknown": "{name} എന്ന സാധനം കണ്ടില്ല.",
  "err_low_stock": "{item} {have} മാത്രമേ ബാക്കിയുള്ളൂ.",
  "err_limit": "കടത്തിന്റെ പരിധി {limit} രൂപയാണ്. ഇതിൽ കൂടുതൽ പറ്റില്ല.",
  "err_overpay": "{balance} രൂപ മാത്രമേ ബാക്കിയുള്ളൂ.",
  "err_generic": "മനസ്സിലായില്ല. ദയവായി വീണ്ടും പറയൂ.",
  "cancelled": "ശരി, റദ്ദാക്കി. വീണ്ടും പറയൂ."},
 "pa-IN": {
  "rb_credit_items": "{name}, {total} ਰੁਪਏ ਉਧਾਰ: {items}. ਠੀਕ ਹੈ?",
  "rb_credit_amount": "{name}, {total} ਰੁਪਏ ਉਧਾਰ. ਠੀਕ ਹੈ?",
  "rb_payment": "{name} ਨੇ {amount} ਰੁਪਏ ਦਿੱਤੇ. ਬਾਕੀ {balance} ਰੁਪਏ. ਠੀਕ ਹੈ?",
  "saved_credit": "{name} ਦੇ ਖਾਤੇ ਵਿੱਚ {total} ਰੁਪਏ ਲਿਖ ਦਿੱਤੇ. ਕੁੱਲ ਬਾਕੀ {balance} ਰੁਪਏ.",
  "saved_payment": "{name} ਦੇ {amount} ਰੁਪਏ ਦਰਜ ਹੋ ਗਏ. ਬਾਕੀ {balance} ਰੁਪਏ.",
  "which_customer": "ਕਿਹੜਾ {name}? {options}?",
  "err_customer_unknown": "{name} ਨਾਮ ਦਾ ਗਾਹਕ ਨਹੀਂ ਮਿਲਿਆ.",
  "err_item_unknown": "{name} ਸਮਾਨ ਨਹੀਂ ਮਿਲਿਆ.",
  "err_low_stock": "{item} ਸਿਰਫ਼ {have} ਬਚਿਆ ਹੈ.",
  "err_limit": "ਉਧਾਰ ਦੀ ਹੱਦ {limit} ਰੁਪਏ ਹੈ. ਇਸ ਤੋਂ ਵੱਧ ਨਹੀਂ ਹੋ ਸਕਦਾ.",
  "err_overpay": "ਸਿਰਫ਼ {balance} ਰੁਪਏ ਬਾਕੀ ਹਨ.",
  "err_generic": "ਸਮਝ ਨਹੀਂ ਆਇਆ. ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਬੋਲੋ.",
  "cancelled": "ਠੀਕ ਹੈ, ਰੱਦ ਕੀਤਾ. ਦੁਬਾਰਾ ਬੋਲੋ."},
}


from app.voice.templates_customer import CUSTOMER_TEMPLATES, CUSTOMER_KEYS
for _l, _d in CUSTOMER_TEMPLATES.items():
    if _l in TEMPLATES:  # ignore deprecated Odia template data
        TEMPLATES[_l].update(_d)
KEYS = KEYS | CUSTOMER_KEYS


from app.voice.templates_confirm import CONFIRM_TEMPLATES, CONFIRM_KEYS
for _l, _d in CONFIRM_TEMPLATES.items():
    if _l in TEMPLATES:  # ignore deprecated Odia template data
        TEMPLATES[_l].update(_d)
KEYS = KEYS | CONFIRM_KEYS


for _l, _d in TEMPLATES.items():
    assert set(_d) == KEYS, f"template keys mismatch for {_l}: {set(_d) ^ KEYS}"


def say(lang: str, key: str, **kw) -> str:
    return TEMPLATES.get(lang, TEMPLATES["hi-IN"])[key].format(**kw)


def fmt(q) -> str:
    return str(int(q)) if float(q) == int(q) else str(q)


# ---- item names in the shop's script (romanised Indic hurts TTS quality) ----
_SCRIPT = {"hi-IN": (0x900, 0x97F), "mr-IN": (0x900, 0x97F), "bn-IN": (0x980, 0x9FF),
           "pa-IN": (0xA00, 0xA7F), "gu-IN": (0xA80, 0xAFF),
           "ta-IN": (0xB80, 0xBFF), "te-IN": (0xC00, 0xC7F), "kn-IN": (0xC80, 0xCFF),
           "ml-IN": (0xD00, 0xD7F)}


def _in_range(s, rng):
    return any(rng[0] <= ord(ch) <= rng[1] for ch in s)


def item_label(item, lang: str) -> str:
    if lang == "en-IN":
        return next((a for a in item.aliases if a.isascii()), item.name)
    for a in item.aliases:
        if lang in _SCRIPT and _in_range(a, _SCRIPT[lang]):
            return a
    for a in item.aliases:                      # fall back to Devanagari
        if _in_range(a, _SCRIPT["hi-IN"]):
            return a
    return item.name


# ---- yes / no words (deterministic, no LLM call needed) ----
_YES = {"yes", "y", "ok", "okay", "haan", "han", "ha", "haa", "theek", "thik", "sahi",
        "barobar", "हाँ", "हां", "हा", "ठीक", "सही", "बरोबर", "होय", "हो", "હા", "બરાબર",
        "ઠીક", "হ্যাঁ", "হাঁ", "ঠিক", "ஆமா", "ஆம்", "சரி", "అవును", "సరే", "ಹೌದು",
        "ಸರಿ", "അതെ", "ശരി", "ਹਾਂ", "ਠੀਕ"}
_NO = {"no", "nahi", "nahin", "nope", "galat", "नहीं", "नही", "नाही", "ना", "गलत",
       "चूक", "ના", "નહીં", "না", "নয়", "இல்லை", "இல்ல", "కాదు", "లేదు", "ಇಲ್ಲ",
       "അല്ല", "ഇല്ല", "ਨਹੀਂ"}


def _tokens(text):
    return {t for t in re.split(r"[\s,.;:!?।'\"-]+", text.lower()) if t}


def is_yes(text: str, lang=None) -> bool:
    from app.engine.confirmation import classify
    r = classify(text, lang)
    return r.has_yes and not r.has_no


def is_no(text: str, lang=None) -> bool:
    from app.engine.confirmation import classify
    return classify(text, lang).has_no