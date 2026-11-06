import re
import unicodedata
from dataclasses import dataclass

# nasal marks, nukta and zero-width characters are dropped so spelling variants match
_STRIP = {chr(c) for c in (
    0x0901, 0x0902, 0x093C, 0x0981, 0x0982, 0x09BC, 0x0A01, 0x0A02, 0x0A3C,
    0x0A81, 0x0A82, 0x0ABC, 0x0B01, 0x0B02, 0x0B3C, 0x0C01, 0x0C02, 0x0C82,
    0x0D02, 0x200C, 0x200D)}
_SPLIT = re.compile(r"[\s.,;:!?।॥'\"“”‘’()\[\]{}\-–—/\\|…]+")


def canon(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return "".join(ch for ch in s if ch not in _STRIP)


def tokens(text: str) -> list:
    return [t for t in _SPLIT.split(canon(text)) if t]


def _set(words: str) -> frozenset:
    return frozenset(canon(w) for w in words.split())


@dataclass(frozen=True)
class Vocab:
    yes: frozenset
    no: frozenset
    filler: frozenset
    weak: frozenset      # "ji" alone means yes, but "Ramesh ji" must not


# accepted in every language (English, Hinglish, core Hindi)
COMMON_YES = _set(
    "yes yeah yep yup ok okay sure correct right confirm confirmed absolutely definitely "
    "haan haa han hanji hanjee ha hn theek thik sahi bilkul pakka barobar hoy hoye acha accha achha "
    "avunu avunnu aamam amam houdu hauda "
    "हाँ हां हा ठीक सही बिल्कुल बिलकुल पक्का ओके")
COMMON_NO = _set(
    "no nope nah nahi nahin nahee nhi nahiin galat wrong incorrect cancel stop mat nako "
    "illa illai ledu vaddu beda bedi नहीं नही गलत मत")
COMMON_FILLER = _set(
    "please it that is thats s go ahead save enter add record thanks thank you the sir "
    "kar karo kardo kijiye likh likho likhdo dijiye hai hain bhai bas ye yeh woh to "
    "arthiq arthik artiq aahe kara")
COMMON_WEAK = _set("ji jee जी")

# words that signal "yes, but ..." / "no, but ..." (always treated as a correction)
BUT = _set(
    "but however lekin lekn magar parantu par पर लेकिन मगर परंतु परन्तु पण પણ কিন্তু "
    "ஆனால் కానీ ಆದರೆ പക്ഷേ ਪਰ କିନ୍ତୁ")

# language: (yes, no, filler, weak)
_LANG = {
    "hi-IN": ("हांजी अच्छा", "रद्द कैंसल रुको रहने",
              "है हैं कर करो करदो दीजिए दीजिये कीजिए कीजिये लिख लिखो लिखदो भाई सर बस ये यह वो तो", ""),
    "en-IN": ("", "", "", ""),
    "mr-IN": ("होय हो बरोबर ठीक ओके बरं", "नाही नको चूक चुकीचे चुकीचं चुकीचा रद्द थांबा थांब",
              "आहे आहेत करा कर लिहा लिही द्या साहेब भाऊ", ""),
    "gu-IN": ("હા હાં બરાબર ઠીક સાચું સાચુ સાચી ચોક્કસ ભલે", "ના નહીં નહિ ખોટું ખોટુ ખોટી રદ બંધ",
              "છે કરો કર કરી દે નાખો લખો લખી આપો ભાઈ સાહેબ", "જી"),
    "bn-IN": ("হ্যাঁ হ্যা হাঁ ঠিক ওকে ঠিকই", "না নয় ভুল বাতিল থাক",
              "আছে হয় করো কর করুন দাও দিন লিখো লেখো লিখুন", "জি"),
    "ta-IN": ("ஆமா ஆமாம் ஆம் சரி சரிதான் சரியே ஓகே", "இல்லை இல்ல வேண்டாம் தவறு ரத்து",
              "செய் செய்யுங்கள் செய்யுங்க பண்ணுங்க பண்ணு எழுதுங்க எழுது போடுங்க தான்", ""),
    "te-IN": ("అవును ఔను అవునండి సరే సరి ఓకే అలాగే", "కాదు లేదు వద్దు తప్పు రద్దు",
              "చేయండి చెయ్యండి చేయి చెయ్యి రాయండి రాసేయండి అండి ఉంది ఇది", ""),
    "kn-IN": ("ಹೌದು ಹೌದಪ್ಪ ಸರಿ ಓಕೆ ಆಯ್ತು", "ಇಲ್ಲ ಬೇಡ ತಪ್ಪು ರದ್ದು ಅಲ್ಲ",
              "ಮಾಡಿ ಮಾಡು ಬರೆಯಿರಿ ಬರೆ ಇದೆ ಆಗಿದೆ", ""),
    "ml-IN": ("അതെ ശരി ശരിയാണ് ഓക്കേ ഉവ്വ്", "അല്ല ഇല്ല വേണ്ട തെറ്റ് റദ്ദാക്കുക",
              "ചെയ്യൂ ചെയ്യുക എഴുതൂ ആണ് ഉണ്ട്", ""),
    "pa-IN": ("ਹਾਂ ਹਾਂਜੀ ਠੀਕ ਸਹੀ ਬਿਲਕੁਲ ਓਕੇ ਪੱਕਾ", "ਨਹੀਂ ਨਹੀ ਨਾ ਨਾਂ ਗਲਤ ਗ਼ਲਤ ਰੱਦ",
              "ਹੈ ਹਨ ਕਰ ਕਰੋ ਦਿਓ ਲਿਖ ਲਿਖੋ", "ਜੀ"),
}

_CACHE: dict = {}


def vocab_for(lang):
    """Vocabulary for one language (+ common words). lang=None or unknown -> all languages."""
    key = lang if lang in _LANG else None
    if key not in _CACHE:
        parts = [_LANG[key]] if key else list(_LANG.values())
        yes, no, fil, weak = set(COMMON_YES), set(COMMON_NO), set(COMMON_FILLER), set(COMMON_WEAK)
        for y, n, f, w in parts:
            yes |= _set(y); no |= _set(n); fil |= _set(f); weak |= _set(w)
        _CACHE[key] = Vocab(frozenset(yes), frozenset(no), frozenset(fil), frozenset(weak))
    return _CACHE[key]