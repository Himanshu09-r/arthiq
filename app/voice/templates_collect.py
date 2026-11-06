"""Fixed templates for collection: shop voice alerts, customer reminder fallbacks, receipt.
Written for hi, en, mr, gu. Other languages fall back to Hindi (needs native-speaker packs)."""

LANG_NAMES = {
    "hi-IN": "Hindi", "en-IN": "English", "mr-IN": "Marathi", "gu-IN": "Gujarati",
    "bn-IN": "Bengali", "ta-IN": "Tamil", "te-IN": "Telugu", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "pa-IN": "Punjabi",
}

CX = {
    "hi-IN": {
        "pay_full": "{name} ने {amount} रुपये दे दिए। खाता साफ हो गया।",
        "pay_part": "{name} ने {amount} रुपये दे दिए। बाकी {balance} रुपये।",
        "pay_adv": "{name} ने {amount} रुपये दिए, {extra} रुपये एडवांस रखे हैं।",
        "pay_held": "{amount} रुपये का एक पेमेंट आया है, पर किसी खाते से नहीं मिला। इनबॉक्स देखिए।",
        "promise_new": "{name} ने {day} तारीख को {amount} रुपये देने का वादा किया है।",
        "promise_broken": "{name} ने वादा पूरा नहीं किया। {amount} रुपये अब भी बाकी हैं।",
        "dispute": "{name} को हिसाब पर आपत्ति है। मैसेज रोक दिए हैं, आप देख लीजिए।",
        "escalation": "{name} के {amount} रुपये {days} दिन से बाकी हैं। आप खुद देख लीजिए।",
        "claimed_paid": "{name} कह रहे हैं कि उन्होंने पैसे दे दिए हैं। कृपया जांच लीजिए।",
        "pay_line": "आप यहाँ से आसानी से पे कर सकते हैं: {link}",
        "rem_gentle": "नमस्ते {cust} जी, {shop} की तरफ से एक छोटी सी याद दिलानी थी: आपके ₹{amount} बाकी हैं{items_part}। {pay_line} धन्यवाद!",
        "rem_split": "नमस्ते {cust} जी, {shop} की तरफ से याद दिलानी थी: आपके ₹{amount} बाकी हैं{items_part}। एक साथ देना मुश्किल हो तो दो हिस्सों में दे सकते हैं। {pay_line} धन्यवाद!",
        "rem_last": "नमस्ते {cust} जी, {shop} की तरफ से यह आखिरी विनम्र याद है: आपके ₹{amount} बाकी हैं{items_part}। {pay_line} अगर पैसे दे चुके हैं तो इस संदेश को अनदेखा करें। धन्यवाद!",
        "rcpt": "धन्यवाद {cust} जी! {shop} को ₹{amount} मिल गए। बाकी: ₹{balance}।",
    },
    "en-IN": {
        "pay_full": "{name} paid {amount} rupees. The account is clear.",
        "pay_part": "{name} paid {amount} rupees. {balance} rupees are still pending.",
        "pay_adv": "{name} paid {amount} rupees, and {extra} rupees are kept as advance.",
        "pay_held": "A payment of {amount} rupees arrived but did not match any account. Please check the inbox.",
        "promise_new": "{name} has promised to pay {amount} rupees on {mon} {day}.",
        "promise_broken": "{name} did not keep the promise. {amount} rupees are still pending.",
        "dispute": "{name} disputes the balance. Messages are stopped, please review.",
        "escalation": "{name} has owed {amount} rupees for {days} days. Please take a look.",
        "claimed_paid": "{name} says the money was paid. Please verify.",
        "pay_line": "You can pay easily here: {link}",
        "rem_gentle": "Hello {cust}, a small reminder from {shop}: ₹{amount} is pending{items_part}. {pay_line} Thank you!",
        "rem_split": "Hello {cust}, a reminder from {shop}: ₹{amount} is pending{items_part}. If paying at once is hard, you can pay in two parts. {pay_line} Thank you!",
        "rem_last": "Hello {cust}, this is a last polite reminder from {shop}: ₹{amount} is pending{items_part}. {pay_line} If you have already paid, please ignore this message. Thank you!",
        "rcpt": "Thank you {cust}! {shop} received ₹{amount}. Balance: ₹{balance}.",
    },
    "mr-IN": {
        "pay_full": "{name} यांनी {amount} रुपये दिले. खाते स्पष्ट झाले.",
        "pay_part": "{name} यांनी {amount} रुपये दिले. उरलेले {balance} रुपये.",
        "pay_adv": "{name} यांनी {amount} रुपये दिले, {extra} रुपये अॅडव्हान्स म्हणून ठेवले आहेत.",
        "pay_held": "{amount} रुपयांचे एक पेमेंट आले आहे, पण कोणत्याही खात्याशी जुळले नाही. इनबॉक्स पहा.",
        "promise_new": "{name} यांनी {day} तारखेला {amount} रुपये देण्याचे वचन दिले आहे.",
        "promise_broken": "{name} यांनी वचन पाळले नाही. {amount} रुपये अजून बाकी आहेत.",
        "dispute": "{name} यांना हिशोबावर हरकत आहे. मेसेज थांबवले आहेत, तुम्ही पाहून घ्या.",
        "escalation": "{name} यांचे {amount} रुपये {days} दिवसांपासून बाकी आहेत. कृपया तुम्ही पाहा.",
        "claimed_paid": "{name} म्हणतात की त्यांनी पैसे दिले आहेत. कृपया तपासा.",
        "pay_line": "तुम्ही इथून सहज पैसे भरू शकता: {link}",
        "rem_gentle": "नमस्कार {cust}, {shop} कडून एक छोटीशी आठवण: तुमचे ₹{amount} बाकी आहेत{items_part}. {pay_line} धन्यवाद!",
        "rem_split": "नमस्कार {cust}, {shop} कडून आठवण: तुमचे ₹{amount} बाकी आहेत{items_part}. एकदम देणे कठीण असेल तर दोन हप्त्यांत देऊ शकता. {pay_line} धन्यवाद!",
        "rem_last": "नमस्कार {cust}, {shop} कडून ही शेवटची नम्र आठवण: तुमचे ₹{amount} बाकी आहेत{items_part}. {pay_line} पैसे आधीच दिले असतील तर हा संदेश दुर्लक्षित करा. धन्यवाद!",
        "rcpt": "धन्यवाद {cust}! {shop} ला ₹{amount} मिळाले. बाकी: ₹{balance}.",
    },
    "gu-IN": {
        "pay_full": "{name} એ {amount} રૂપિયા આપી દીધા. ખાતું સાફ થઈ ગયું.",
        "pay_part": "{name} એ {amount} રૂપિયા આપ્યા. બાકી {balance} રૂપિયા.",
        "pay_adv": "{name} એ {amount} રૂપિયા આપ્યા, {extra} રૂપિયા એડવાન્સ તરીકે રાખ્યા છે.",
        "pay_held": "{amount} રૂપિયાનું એક પેમેન્ટ આવ્યું છે, પણ કોઈ ખાતા સાથે મળ્યું નથી. ઇનબોક્સ જુઓ.",
        "promise_new": "{name} એ {day} તારીખે {amount} રૂપિયા આપવાનો વાયદો કર્યો છે.",
        "promise_broken": "{name} એ વાયદો પાળ્યો નથી. {amount} રૂપિયા હજી બાકી છે.",
        "dispute": "{name} ને હિસાબ સામે વાંધો છે. મેસેજ બંધ કર્યા છે, તમે જોઈ લો.",
        "escalation": "{name} ના {amount} રૂપિયા {days} દિવસથી બાકી છે. કૃપા કરીને તમે જુઓ.",
        "claimed_paid": "{name} કહે છે કે તેમણે પૈસા આપી દીધા છે. કૃપા કરીને તપાસો.",
        "pay_line": "તમે અહીંથી સરળતાથી ચૂકવી શકો છો: {link}",
        "rem_gentle": "નમસ્તે {cust}, {shop} તરફથી એક નાનકડી યાદ: તમારા ₹{amount} બાકી છે{items_part}. {pay_line} આભાર!",
        "rem_split": "નમસ્તે {cust}, {shop} તરફથી યાદ: તમારા ₹{amount} બાકી છે{items_part}. એકસાથે આપવું મુશ્કેલ હોય તો બે હપ્તામાં આપી શકો છો. {pay_line} આભાર!",
        "rem_last": "નમસ્તે {cust}, {shop} તરફથી આ છેલ્લી નમ્ર યાદ છે: તમારા ₹{amount} બાકી છે{items_part}. {pay_line} જો ચુકવણી થઈ ગઈ હોય તો આ સંદેશ અવગણજો. આભાર!",
        "rcpt": "આભાર {cust}! {shop} ને ₹{amount} મળી ગયા. બાકી: ₹{balance}.",
    },
}

KEYS = set(CX["hi-IN"])
for _lang, _d in CX.items():
    assert set(_d) == KEYS, f"template keys mismatch in {_lang}: {set(_d) ^ KEYS}"


def lang_used(lang: str) -> str:
    return lang if lang in CX else "hi-IN"


def cx(lang: str, key: str, **kw) -> str:
    return CX[lang_used(lang)][key].format(**kw)