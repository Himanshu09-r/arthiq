"""Daily Business Intelligence Engine.
Computes comprehensive daily financial reports, distinguishes top debtors from today's top buyers,
analyzes gross margins, top products, stock warnings, and prepares bulk collection reminder approvals.
Supports all 10 official Indian languages.
"""
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Shop, Customer, Item, LedgerEntry, SaleLog, OutboxMessage, ActionAudit, Purchase, PurchaseItem
from app.engine import clock
from app.engine.ladder import outstanding
from app.tools.ledger_tools import get_balance

SUMMARY_TEMPLATES: Dict[str, Dict[str, str]] = {
    "hi-IN": {
        "title": "आज का बिज़नेस सारांश",
        "intro": "आज ₹{collected} जमा हुए और ₹{credit} का उधार दिया गया.",
        "debtor": "सबसे ज़्यादा कुल बकाया {debtor_name} का ₹{debtor_amt} है.",
        "top_buyer": "आज सबसे ज़्यादा उधार {buyer_name} ने ₹{buyer_amt} का लिया.",
        "top_product": "आज सबसे ज़्यादा {product_name} ({qty} {unit}) बिका.",
        "margin": "कुल बिक्री ₹{sales}, अनुमानित मुनाफ़ा ₹{margin}.",
        "stock_alert": "स्टॉक अलर्ट: {items} का स्टॉक कम है.",
        "stock_healthy": "सभी मुख्य सामान का स्टॉक ठीक है.",
        "reminder_ask": "आज {count} ग्राहकों का पेमेंट पेंडिंग है. क्या मैं उन सबको WhatsApp रिमाइंडर भेज दूं?",
        "reminders_sent": "सभी {count} ग्राहकों को WhatsApp रिमाइंडर भेज दिए गए हैं.",
        "no_pending": "आज किसी भी ग्राहक का पेमेंट पेंडिंग नहीं है."
    },
    "en-IN": {
        "title": "Today's Business Summary",
        "intro": "Today ₹{collected} collected and ₹{credit} credit extended.",
        "debtor": "Highest total outstanding is {debtor_name} at ₹{debtor_amt}.",
        "top_buyer": "Most credit taken today by {buyer_name} at ₹{buyer_amt}.",
        "top_product": "Top-selling product today: {product_name} ({qty} {unit} sold).",
        "margin": "Total sales ₹{sales}, estimated gross margin ₹{margin}.",
        "stock_alert": "Stock warning: {items} running low.",
        "stock_healthy": "Stock levels are healthy.",
        "reminder_ask": "{count} customers have pending payments today. Should I send WhatsApp reminders to all of them?",
        "reminders_sent": "WhatsApp reminders have been queued for all {count} customers.",
        "no_pending": "No pending customer collections today."
    },
    "mr-IN": {
        "title": "आजचा व्यवसाय सारांश",
        "intro": "आज ₹{collected} जमा झाले आणि ₹{credit} उधारी दिली गेली.",
        "debtor": "सर्वात जास्त बाकी {debtor_name} यांची ₹{debtor_amt} आहे.",
        "top_buyer": "आज सर्वात जास्त उधारी {buyer_name} यांनी ₹{buyer_amt} घेतली.",
        "top_product": "आज सर्वाधिक विक्री: {product_name} ({qty} {unit}).",
        "margin": "एकूण विक्री ₹{sales}, नफा ₹{margin}.",
        "stock_alert": "स्टॉक अलर्ट: {items} चा साठा कमी आहे.",
        "stock_healthy": "स्टॉक चांगला आहे.",
        "reminder_ask": "आज {count} ग्राहकांचे पेमेंट बाकी आहे. मी सर्वांना WhatsApp रिमाइंडर पाठवू का?",
        "reminders_sent": "सर्व {count} ग्राहकांना WhatsApp रिमाइंडर पाठवले आहेत.",
        "no_pending": "आज कोणाचीही उधारी बाकी नाही."
    },
    "gu-IN": {
        "title": "આજનો બિઝનેસ રિપોર્ટ",
        "intro": "આજે ₹{collected} જમા થયા અને ₹{credit} ઉધાર અપાયા.",
        "debtor": "સૌથી વધુ બાકી {debtor_name} ના ₹{debtor_amt} છે.",
        "top_buyer": "આજે સૌથી વધુ ઉધાર {buyer_name} એ ₹{buyer_amt} લીધું.",
        "top_product": "આજે સૌથી વધુ વેચાણ: {product_name} ({qty} {unit}).",
        "margin": "કુલ વેચાણ ₹{sales}, નફો ₹{margin}.",
        "stock_alert": "સ્ટોક ચેતવણી: {items} નો સ્ટોક ઓછો છે.",
        "stock_healthy": "સ્ટોક બરાબર છે.",
        "reminder_ask": "આજે {count} ગ્રાહકોનું પેમેન્ટ બાકી છે. શું હું બધાને WhatsApp રિમાઇન્ડર મોકલી દઉં?",
        "reminders_sent": "બધા {count} ગ્રાહકોને WhatsApp રિમાઇન્ડર મોકલી દીધા છે.",
        "no_pending": "આજે કોઈનું પેમેન્ટ બાકી નથી."
    },
    "bn-IN": {
        "title": "আজকের ব্যবসায়িক সারাংশ",
        "intro": "আজ ₹{collected} জমা হয়েছে এবং ₹{credit} ধার দেওয়া হয়েছে.",
        "debtor": "সর্বোচ্চ বকেয়া {debtor_name} এর ₹{debtor_amt}.",
        "top_buyer": "আজ সবচেয়ে বেশি ধার নিয়েছেন {buyer_name} ₹{buyer_amt}.",
        "top_product": "আজ সর্বোচ্চ বিক্রিত পণ্য: {product_name} ({qty} {unit}).",
        "margin": "মোট বিক্রি ₹{sales}, আনুমানিক লাভ ₹{margin}.",
        "stock_alert": "স্টক সতর্কতা: {items} এর স্টক কম.",
        "stock_healthy": "স্টক পর্যাপ্ত রয়েছে.",
        "reminder_ask": "আজ {count} জন গ্রাহকের পেমেন্ট বাকি আছে. সবাইকে কি WhatsApp রিমাইন্ডার পাঠিয়ে দেব?",
        "reminders_sent": "সকল {count} জন গ্রাহককে WhatsApp রিমাইন্ডার পাঠানো হয়েছে.",
        "no_pending": "আজ কোনো বকেয়া পেমেন্ট নেই."
    },
    "ta-IN": {
        "title": "இன்றைய வணிக சுருக்கம்",
        "intro": "இன்று ₹{collected} வசூலானது மற்றும் ₹{credit} கடன் கொடுக்கப்பட்டது.",
        "debtor": "அதிகபட்ச நிலுவை {debtor_name} இடம் ₹{debtor_amt} உள்ளது.",
        "top_buyer": "இன்று அதிக கடன் வாங்கியவர் {buyer_name} ₹{buyer_amt}.",
        "top_product": "அதிக விற்பனையான பொருள்: {product_name} ({qty} {unit}).",
        "margin": "மொத்த விற்பனை ₹{sales}, லாபம் ₹{margin}.",
        "stock_alert": "எச்சரிக்கை: {items} இருப்பு குறைவாக உள்ளது.",
        "stock_healthy": "பொருட்கள் போதுமான அளவில் உள்ளன.",
        "reminder_ask": "இன்று {count} வாடிக்கையாளர்களின் பணம் நிலுவையில் உள்ளது. அனைவருக்கும் WhatsApp நினைவூட்டல் அனுப்பவா?",
        "reminders_sent": "{count} வாடிக்கையாளர்களுக்கும் நினைவூட்டல் அனுப்பப்பட்டது.",
        "no_pending": "இன்று நிலுவை ஏதுமில்லை."
    },
    "te-IN": {
        "title": "ఈరోజు వ్యాపార సారాంశం",
        "intro": "ఈరోజు ₹{collected} వసూలు అయ్యాయి మరియు ₹{credit} అప్పు ఇవ్వబడింది.",
        "debtor": "అత్యధిక బకాయి {debtor_name} నుండి ₹{debtor_amt}.",
        "top_buyer": "ఈరోజు అత్యధికంగా అప్పు తీసుకున్నది {buyer_name} ₹{buyer_amt}.",
        "top_product": "ఎక్కువగా అమ్ముడైన వస్తువు: {product_name} ({qty} {unit}).",
        "margin": "మొత్తం అమ్మకాలు ₹{sales}, లాభం ₹{margin}.",
        "stock_alert": "స్టాక్ హెచ్చరిక: {items} తక్కువగా ఉంది.",
        "stock_healthy": "స్టాక్ సరిపడా ఉంది.",
        "reminder_ask": "ఈరోజు {count} మంది కస్టమర్ల పేమెంట్ పెండింగ్‌లో ఉంది. అందరికీ WhatsApp రిమైండర్ పంపమంటారా?",
        "reminders_sent": "{count} మంది కస్టమర్లకు రిమైండర్ పంపబడింది.",
        "no_pending": "ఈరోజు పెండింగ్ బకాయిలు లేవు."
    },
    "kn-IN": {
        "title": "ಇಂದಿನ ವ್ಯವಹಾರ ಸಾರಾಂಶ",
        "intro": "ಇಂದು ₹{collected} ವಸೂಲಿಯಾಗಿದೆ ಮತ್ತು ₹{credit} ಸಾಲ ನೀಡಲಾಗಿದೆ.",
        "debtor": "ಅತ್ಯಧಿಕ ಬಾಕಿ {debtor_name} ಅವರಿಂದ ₹{debtor_amt}.",
        "top_buyer": "ಇಂದು ಅತಿ ಹೆಚ್ಚು ಸಾಲ ಪಡೆದವರು {buyer_name} ₹{buyer_amt}.",
        "top_product": "ಹೆಚ್ಚು ಮಾರಾಟವಾದ ವಸ್ತು: {product_name} ({qty} {unit}).",
        "margin": "ಒಟ್ಟು ಮಾರಾಟ ₹{sales}, ಲಾಭ ₹{margin}.",
        "stock_alert": "ಸ್ಟಾಕ್ ಎಚ್ಚರಿಕೆ: {items} ಸಂಗ್ರಹ ಕಡಿಮೆಯಾಗಿದೆ.",
        "stock_healthy": "ಸ್ಟಾಕ್ ಉತ್ತಮವಾಗಿದೆ.",
        "reminder_ask": "ಇಂದು {count} ಗ್ರಾಹಕರ ಪಾವತಿ ಬಾಕಿ ಇದೆ. ಎಲ್ಲರಿಗೂ WhatsApp ಸಂದೇಶ ಕಳುಹಿಸಬೇಕೆ?",
        "reminders_sent": "ಎಲ್ಲಾ {count} ಗ್ರಾಹಕರಿಗೆ ಸಂದೇಶ ಕಳುಹಿಸಲಾಗಿದೆ.",
        "no_pending": "ಯಾವುದೇ ಬಾಕಿ ಪಾವತಿಗಳಿಲ್ಲ."
    },
    "ml-IN": {
        "title": "ഇന്നത്തെ ബിസിനസ്സ് സംഗ്രഹം",
        "intro": "ഇന്ന് ₹{collected} ലഭിച്ചു, ₹{credit} കടം നൽകി.",
        "debtor": "ഏറ്റവും കൂടുതൽ ബാക്കി {debtor_name} ₹{debtor_amt}.",
        "top_buyer": "ഇന്ന് ഏറ്റവും കൂടുതൽ കടമെടുത്തത് {buyer_name} ₹{buyer_amt}.",
        "top_product": "കൂടുതൽ വിറ്റഴിച്ച സാധനം: {product_name} ({qty} {unit}).",
        "margin": "ആകെ വിൽപ്പന ₹{sales}, ലാഭം ₹{margin}.",
        "stock_alert": "സ്റ്റോക്ക് കുറവാണ്: {items}.",
        "stock_healthy": "സ്റ്റോക്ക് തൃപ്തികരമാണ്.",
        "reminder_ask": "ഇന്ന് {count} പേരുടെ പേയ്‌മെന്റ് ബാക്കിയുണ്ട്. എല്ലാവർക്കും WhatsApp ഓർമ്മപ്പെടുത്തൽ അയക്കണോ?",
        "reminders_sent": "{count} പേർക്കും ഓർമ്മപ്പെടുത്തൽ അയച്ചു.",
        "no_pending": "ഇന്ന് കുടിശ്ശിക പേയ്‌മെന്റുകൾ ഇല്ല."
    },
    "pa-IN": {
        "title": "ਅੱਜ ਦਾ ਵਪਾਰ ਸੰਖੇਪ",
        "intro": "ਅੱਜ ₹{collected} ਇਕੱਠੇ ਹੋਏ ਅਤੇ ₹{credit} ਉਧਾਰ ਦਿੱਤਾ ਗਿਆ.",
        "debtor": "ਸਭ ਤੋਂ ਵੱਧ ਬਕਾਇਆ {debtor_name} ਦਾ ₹{debtor_amt} ਹੈ.",
        "top_buyer": "ਅੱਜ ਸਭ ਤੋਂ ਵੱਧ ਉਧਾਰ {buyer_name} ਨੇ ₹{buyer_amt} ਲਿਆ.",
        "top_product": "ਸਭ ਤੋਂ ਵੱਧ ਵਿਕਣ ਵਾਲਾ ਸਮਾਨ: {product_name} ({qty} {unit}).",
        "margin": "ਕੁੱਲ ਵਿਕਰੀ ₹{sales}, ਅਨੁਮਾਨਿਤ ਮੁਨਾਫਾ ₹{margin}.",
        "stock_alert": "ਸਟਾਕ ਚੇਤਾਵਨੀ: {items} ਦਾ ਸਟਾਕ ਘੱਟ ਹੈ.",
        "stock_healthy": "ਸਟਾਕ ਸਹੀ ਹੈ.",
        "reminder_ask": "ਅੱਜ {count} ਗਾਹਕਾਂ ਦਾ ਭੁਗਤਾਨ ਬਕਾਇਆ ਹੈ. ਕੀ ਮੈਂ ਸਾਰਿਆਂ ਨੂੰ WhatsApp ਸੁਨੇਹਾ ਭੇਜ ਦੇਵਾਂ?",
        "reminders_sent": "ਸਾਰੇ {count} ਗਾਹਕਾਂ ਨੂੰ WhatsApp ਸੁਨੇਹਾ ਭੇਜ ਦਿੱਤਾ ਗਿਆ ਹੈ.",
        "no_pending": "ਅੱਜ ਕੋਈ ਬਕਾਇਆ ਭੁਗਤਾਨ ਨਹੀਂ ਹੈ."
    }
}


SUMMARY_DETAIL_TEXT = {
    "hi-IN": "नकद बिक्री {cash} रुपये और उधार बिक्री {credit} रुपये रही। कुल बिक्री {sales} रुपये है। ग्राहकों से कुल {outstanding} रुपये बकाया हैं। आज {stock_lines} स्टॉक-इन लाइनें दर्ज हुईं, खरीद मूल्य {stock_amount} रुपये। {overdue_count} ग्राहकों का {overdue_amount} रुपये समय से बकाया है।",
    "en-IN": "Cash sales were ₹{cash} and credit sales were ₹{credit}, making total sales ₹{sales}. Customers currently owe ₹{outstanding}. Today {stock_lines} stock-in lines worth ₹{stock_amount} were recorded. {overdue_count} customers have ₹{overdue_amount} overdue.",
    "mr-IN": "आजची रोख विक्री {cash} रुपये आणि उधारी विक्री {credit} रुपये होती; एकूण विक्री {sales} रुपये झाली. ग्राहकांकडून एकूण {outstanding} रुपये येणे बाकी आहे. आज {stock_lines} स्टॉक-इन नोंदी झाल्या; खरेदी मूल्य {stock_amount} रुपये. {overdue_count} ग्राहकांचे {overdue_amount} रुपये मुदतीनंतर बाकी आहेत.",
    "gu-IN": "આજનું રોકડ વેચાણ {cash} રૂપિયા અને ઉધાર વેચાણ {credit} રૂપિયા રહ્યું; કુલ વેચાણ {sales} રૂપિયા છે. ગ્રાહકો પાસેથી કુલ {outstanding} રૂપિયા લેવાના બાકી છે. આજે {stock_lines} સ્ટોક-ઇન નોંધાયા, ખરીદી કિંમત {stock_amount} રૂપિયા. {overdue_count} ગ્રાહકોના {overdue_amount} રૂપિયા સમયમર્યાદા બાદ બાકી છે.",
    "bn-IN": "আজ নগদ বিক্রি {cash} টাকা এবং বাকি বিক্রি {credit} টাকা; মোট বিক্রি {sales} টাকা। গ্রাহকদের কাছ থেকে মোট {outstanding} টাকা পাওনা। আজ {stock_lines}টি স্টক-ইন লাইন নথিভুক্ত হয়েছে, ক্রয়মূল্য {stock_amount} টাকা। {overdue_count} জন গ্রাহকের {overdue_amount} টাকা মেয়াদোত্তীর্ণ বকেয়া রয়েছে।",
    "ta-IN": "இன்றைய ரொக்க விற்பனை {cash} ரூபாய், கடன் விற்பனை {credit} ரூபாய்; மொத்த விற்பனை {sales} ரூபாய். வாடிக்கையாளர்களிடமிருந்து மொத்தம் {outstanding} ரூபாய் வரவேண்டும். இன்று {stock_lines} சரக்கு வரவு பதிவுகள், கொள்முதல் மதிப்பு {stock_amount} ரூபாய். {overdue_count} வாடிக்கையாளர்களுக்கு {overdue_amount} ரூபாய் காலதாமத நிலுவை உள்ளது.",
    "te-IN": "ఈరోజు నగదు అమ్మకాలు {cash} రూపాయలు, క్రెడిట్ అమ్మకాలు {credit} రూపాయలు; మొత్తం అమ్మకాలు {sales} రూపాయలు. కస్టమర్ల నుంచి మొత్తం {outstanding} రూపాయలు రావాలి. ఈరోజు {stock_lines} స్టాక్-ఇన్ లైన్లు నమోదయ్యాయి; కొనుగోలు విలువ {stock_amount} రూపాయలు. {overdue_count} మంది కస్టమర్లకు {overdue_amount} రూపాయలు గడువు దాటిన బాకీ ఉంది.",
    "kn-IN": "ಇಂದಿನ ನಗದು ಮಾರಾಟ {cash} ರೂಪಾಯಿ ಮತ್ತು ಸಾಲ ಮಾರಾಟ {credit} ರೂಪಾಯಿ; ಒಟ್ಟು ಮಾರಾಟ {sales} ರೂಪಾಯಿ. ಗ್ರಾಹಕರಿಂದ ಒಟ್ಟು {outstanding} ರೂಪಾಯಿ ಬರಬೇಕಿದೆ. ಇಂದು {stock_lines} ಸ್ಟಾಕ್-ಇನ್ ದಾಖಲೆಗಳು, ಖರೀದಿ ಮೌಲ್ಯ {stock_amount} ರೂಪಾಯಿ. {overdue_count} ಗ್ರಾಹಕರಿಗೆ {overdue_amount} ರೂಪಾಯಿ ಅವಧಿ ಮೀರಿದ ಬಾಕಿ ಇದೆ.",
    "ml-IN": "ഇന്നത്തെ പണവിൽപ്പന {cash} രൂപയും കടവിൽപ്പന {credit} രൂപയും; ആകെ വിൽപ്പന {sales} രൂപയാണ്. ഉപഭോക്താക്കളിൽ നിന്ന് ആകെ {outstanding} രൂപ ലഭിക്കാനുണ്ട്. ഇന്ന് {stock_lines} സ്റ്റോക്ക്-ഇൻ വരികൾ രേഖപ്പെടുത്തി; വാങ്ങൽ മൂല്യം {stock_amount} രൂപ. {overdue_count} ഉപഭോക്താക്കൾക്ക് {overdue_amount} രൂപ കാലാവധി കഴിഞ്ഞ കുടിശ്ശികയുണ്ട്.",
    "pa-IN": "ਅੱਜ ਨਕਦ ਵਿਕਰੀ {cash} ਰੁਪਏ ਅਤੇ ਉਧਾਰ ਵਿਕਰੀ {credit} ਰੁਪਏ ਰਹੀ; ਕੁੱਲ ਵਿਕਰੀ {sales} ਰੁਪਏ ਹੈ। ਗਾਹਕਾਂ ਤੋਂ ਕੁੱਲ {outstanding} ਰੁਪਏ ਲੈਣੇ ਬਾਕੀ ਹਨ। ਅੱਜ {stock_lines} ਸਟਾਕ-ਇਨ ਲਾਈਨਾਂ ਦਰਜ ਹੋਈਆਂ, ਖਰੀਦ ਮੁੱਲ {stock_amount} ਰੁਪਏ। {overdue_count} ਗਾਹਕਾਂ ਦੇ {overdue_amount} ਰੁਪਏ ਮਿਆਦ ਤੋਂ ਬਾਅਦ ਬਾਕੀ ਹਨ।",
}


def compute_daily_summary(db: Session, shop_id: int, lang: Optional[str] = None) -> Dict[str, Any]:
    """Compute accurate daily financial report from SQL database."""
    shop = db.get(Shop, shop_id)
    language = lang or (shop.language if shop else "hi-IN")
    if language not in SUMMARY_TEMPLATES:
        language = "hi-IN"
    t = SUMMARY_TEMPLATES[language]

    now = clock.now()
    start_today = datetime.combine(now.date(), time.min)
    end_today = start_today + timedelta(days=1)

    # 1. Money collected today
    payments_today = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id,
        LedgerEntry.type == "payment",
        LedgerEntry.created_at >= start_today,
        LedgerEntry.created_at < end_today
    )).all()
    money_collected = sum(p.amount for p in payments_today)

    # 2. Credit given today
    credit_today_entries = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id,
        LedgerEntry.type == "credit",
        LedgerEntry.created_at >= start_today,
        LedgerEntry.created_at < end_today
    )).all()
    credit_given_today = sum(c.amount for c in credit_today_entries)

    # 3. Cash sales today
    cash_sales = db.scalars(select(SaleLog).where(
        SaleLog.shop_id == shop_id,
        SaleLog.sold_at >= start_today,
        SaleLog.sold_at < end_today
    )).all()
    cash_sales_amount = sum(s.amount for s in cash_sales)
    total_sales = cash_sales_amount + credit_given_today

    # 4. Customers mapping & balances
    all_customers = db.scalars(select(Customer).where(Customer.shop_id == shop_id)).all()
    cust_map = {c.id: c.name for c in all_customers}

    # Highest total outstanding debtor (overall)
    highest_debtor_name = "None"
    highest_debtor_amt = 0
    pending_customers = []
    outstanding_total = 0
    for c in all_customers:
        bal = get_balance(db, c.id)
        if bal > 0:
            outstanding_total += bal
            pending_customers.append({"id": c.id, "name": c.name, "balance": bal, "phone": c.phone})
            if bal > highest_debtor_amt:
                highest_debtor_amt = bal
                highest_debtor_name = c.name

    # 5. Customer who took the most credit TODAY (distinct from overall highest debtor)
    today_credit_by_cust = {}
    for entry in credit_today_entries:
        today_credit_by_cust[entry.customer_id] = today_credit_by_cust.get(entry.customer_id, 0) + entry.amount

    top_buyer_name = "None"
    top_buyer_amt = 0
    if today_credit_by_cust:
        top_cid = max(today_credit_by_cust, key=today_credit_by_cust.get)
        top_buyer_amt = today_credit_by_cust[top_cid]
        top_buyer_name = cust_map.get(top_cid, f"Customer #{top_cid}")
    else:
        top_buyer_name = highest_debtor_name
        top_buyer_amt = 0

    # 6. Top-selling product today & estimated gross margin
    items_sold = {}  # item_id -> total qty
    cogs = 0
    for entry in credit_today_entries:
        for ln in (entry.items_json or []):
            iid = ln.get("item_id")
            qty = float(ln.get("qty", 0))
            if iid:
                items_sold[iid] = items_sold.get(iid, 0) + qty
                it = db.get(Item, iid)
                if it and it.cost_price:
                    cogs += qty * it.cost_price

    for s in cash_sales:
        items_sold[s.item_id] = items_sold.get(s.item_id, 0) + s.qty
        it = db.get(Item, s.item_id)
        if it and it.cost_price:
            cogs += s.qty * it.cost_price

    top_product_name = "Various items"
    top_product_qty = 0
    top_product_unit = "units"
    if items_sold:
        top_item_id = max(items_sold, key=items_sold.get)
        it = db.get(Item, top_item_id)
        if it:
            top_product_name = it.name
            top_product_qty = round(items_sold[top_item_id], 1)
            top_product_unit = it.unit

    gross_margin = max(0, int(total_sales - cogs))

    # 7. Stock warnings
    all_items = db.scalars(select(Item).where(Item.shop_id == shop_id)).all()
    low_stock = [i for i in all_items if i.stock_qty <= i.reorder_level]
    stock_warnings = [{"name": i.name, "stock": i.stock_qty, "reorder": i.reorder_level, "unit": i.unit} for i in low_stock]
    out_of_stock_count = sum(float(i.stock_qty or 0) <= 0 for i in all_items)

    overdue_entries = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id,
        LedgerEntry.type == "credit",
        LedgerEntry.status.in_(["OPEN", "PARTIAL"]),
        LedgerEntry.due_date.is_not(None),
        LedgerEntry.due_date < now.date()
    )).all()
    overdue_balances = [outstanding(e) for e in overdue_entries]
    overdue_amount = sum(b for b in overdue_balances if b > 0)
    overdue_count = len({e.customer_id for e, b in zip(overdue_entries, overdue_balances) if b > 0})

    received_purchases = db.scalars(select(Purchase).where(
        Purchase.shop_id == shop_id,
        Purchase.created_at >= start_today,
        Purchase.created_at < end_today,
        Purchase.status == "RECEIVED"
    )).all()
    purchase_ids = [p.id for p in received_purchases]
    stock_in_lines = (db.query(PurchaseItem).filter(PurchaseItem.purchase_id.in_(purchase_ids)).count()
                      if purchase_ids else 0)
    stock_in_amount = sum(int(p.total_amount or 0) for p in received_purchases)

    # Build spoken narrative sentence by sentence. Summary is read-only; reminders remain
    # a separate, explicitly approved dashboard action and are never triggered by narration.
    spoken_parts = []
    spoken_parts.append(t["intro"].format(collected=money_collected, credit=credit_given_today))
    
    if highest_debtor_amt > 0:
        spoken_parts.append(t["debtor"].format(debtor_name=highest_debtor_name, debtor_amt=highest_debtor_amt))
    
    if top_buyer_amt > 0:
        spoken_parts.append(t["top_buyer"].format(buyer_name=top_buyer_name, buyer_amt=top_buyer_amt))
    
    if top_product_qty > 0:
        spoken_parts.append(t["top_product"].format(product_name=top_product_name, qty=top_product_qty, unit=top_product_unit))

    if total_sales > 0:
        spoken_parts.append(t["margin"].format(sales=total_sales, margin=gross_margin))

    if low_stock:
        item_names = ", ".join(i.name for i in low_stock[:3])
        spoken_parts.append(t["stock_alert"].format(items=item_names))
    else:
        spoken_parts.append(t["stock_healthy"])

    pending_count = len(pending_customers)
    detail_template = SUMMARY_DETAIL_TEXT.get(language, SUMMARY_DETAIL_TEXT["hi-IN"])
    spoken_parts.append(detail_template.format(
        cash=int(cash_sales_amount), credit=int(credit_given_today), sales=int(total_sales),
        outstanding=int(outstanding_total), stock_lines=int(stock_in_lines),
        stock_amount=int(stock_in_amount), overdue_count=int(overdue_count),
        overdue_amount=int(overdue_amount),
    ))
    spoken_narrative = " ".join(spoken_parts)

    return {
        "title": t["title"],
        "language": language,
        "date": now.strftime("%d %B %Y"),
        "spoken_text": spoken_narrative,
        "money_collected": money_collected,
        "credit_given_today": credit_given_today,
        "cash_sales": cash_sales_amount,
        "credit_sales": credit_given_today,
        "outstanding_total": outstanding_total,
        "overdue_count": overdue_count,
        "overdue_amount": overdue_amount,
        "stock_in_lines": stock_in_lines,
        "stock_in_amount": stock_in_amount,
        "low_stock_count": len(low_stock),
        "out_of_stock_count": out_of_stock_count,
        "total_sales": total_sales,
        "gross_margin": gross_margin,
        "highest_debtor": {
            "name": highest_debtor_name,
            "amount": highest_debtor_amt
        },
        "today_top_buyer": {
            "name": top_buyer_name,
            "amount": top_buyer_amt
        },
        "top_product": {
            "name": top_product_name,
            "quantity": top_product_qty,
            "unit": top_product_unit
        },
        "stock_warnings": stock_warnings,
        "pending_collections_count": pending_count,
        "pending_customers": pending_customers,
        "reminder_prompt": t["reminder_ask"].format(count=pending_count) if pending_count > 0 else None
    }


def send_bulk_whatsapp_reminders(db: Session, shop_id: int, pending_customers: list) -> int:
    """Send simulated WhatsApp reminders to all customers with pending balance."""
    shop = db.get(Shop, shop_id)
    sent_count = 0
    now = datetime.now()
    for c in pending_customers:
        cid = c.get("id")
        bal = c.get("balance", 0)
        c_name = c.get("name", "Customer")
        msg_text = f"Namaste {c_name} ji, Sharma Kirana Store se aapka ₹{bal} ka hisab pending hai. Kripya samay par jama karein. Dhanyawad."
        outbox_row = OutboxMessage(
            shop_id=shop_id,
            customer_id=cid,
            direction="out",
            channel="whatsapp",
            text=msg_text,
            link=f"/pay/{cid}",
            label="bulk_reminder",
            created_at=now
        )
        db.add(outbox_row)
        sent_count += 1

    db.add(ActionAudit(
        shop_id=shop_id,
        actor="voice_assistant",
        tool="send_bulk_reminders",
        arguments={"count": sent_count, "recipients": [c.get("name") for c in pending_customers]}
    ))
    db.commit()
    return sent_count

