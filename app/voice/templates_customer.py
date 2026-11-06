CUSTOMER_KEYS = {"rb_register", "ask_items", "registered", "err_duplicate", "err_bad_phone"}

CUSTOMER_TEMPLATES = {
 "en-IN": {
  "rb_register": "New customer: {details}. Credit limit {limit} rupees. Register?",
  "ask_items": "What did {name} take?",
  "registered": "Customer {name} registered.",
  "err_duplicate": "{details} is already registered. Use the existing account?",
  "err_bad_phone": "That phone number is not valid. Please say all 10 digits."},
 "hi-IN": {
  "rb_register": "नया ग्राहक: {details}. उधार सीमा {limit} रुपये. दर्ज करूँ?",
  "ask_items": "{name} ने क्या लिया?",
  "registered": "ग्राहक {name} दर्ज हो गया.",
  "err_duplicate": "{details} पहले से दर्ज हैं. उन्हीं के खाते में लिखूँ?",
  "err_bad_phone": "फ़ोन नंबर सही नहीं है. कृपया पूरे दस अंक बताइए."},
 "mr-IN": {
  "rb_register": "नवीन ग्राहक: {details}. उधारीची मर्यादा {limit} रुपये. नोंदवू का?",
  "ask_items": "{name} यांनी काय घेतले?",
  "registered": "ग्राहक {name} नोंदवला गेला.",
  "err_duplicate": "{details} आधीच नोंदवलेले आहेत. त्यांच्याच खात्यात लिहू का?",
  "err_bad_phone": "फोन नंबर बरोबर नाही. कृपया पूर्ण दहा अंक सांगा."},
 "gu-IN": {
  "rb_register": "નવા ગ્રાહક: {details}. ઉધારની મર્યાદા {limit} રૂપિયા. નોંધું?",
  "ask_items": "{name} એ શું લીધું?",
  "registered": "ગ્રાહક {name} નોંધાઈ ગયા.",
  "err_duplicate": "{details} પહેલેથી નોંધાયેલા છે. તેમના જ ખાતામાં લખું?",
  "err_bad_phone": "ફોન નંબર સાચો નથી. કૃપા કરીને પૂરા દસ અંક બોલો."},
 "bn-IN": {
  "rb_register": "নতুন গ্রাহক: {details}. ধারের সীমা {limit} টাকা. নথিভুক্ত করব?",
  "ask_items": "{name} কী নিয়েছেন?",
  "registered": "গ্রাহক {name} নথিভুক্ত হয়েছে.",
  "err_duplicate": "{details} আগে থেকেই নথিভুক্ত আছেন. তাঁর খাতাতেই লিখব?",
  "err_bad_phone": "ফোন নম্বর ঠিক নয়. পুরো দশ সংখ্যা বলুন."},
 "ta-IN": {
  "rb_register": "புதிய வாடிக்கையாளர்: {details}. கடன் வரம்பு {limit} ரூபாய். பதிவு செய்யவா?",
  "ask_items": "{name} என்ன வாங்கினார்?",
  "registered": "வாடிக்கையாளர் {name} பதிவு செய்யப்பட்டார்.",
  "err_duplicate": "{details} ஏற்கனவே பதிவு செய்யப்பட்டுள்ளார். அவர் கணக்கிலேயே எழுதவா?",
  "err_bad_phone": "தொலைபேசி எண் சரியில்லை. பத்து இலக்கங்களையும் சொல்லுங்கள்."},
 "te-IN": {
  "rb_register": "కొత్త కస్టమర్: {details}. అప్పు పరిమితి {limit} రూపాయలు. నమోదు చేయమంటారా?",
  "ask_items": "{name} ఏం తీసుకున్నారు?",
  "registered": "కస్టమర్ {name} నమోదు అయ్యారు.",
  "err_duplicate": "{details} ఇప్పటికే నమోదై ఉన్నారు. వారి ఖాతాలోనే రాయమంటారా?",
  "err_bad_phone": "ఫోన్ నంబర్ సరిగా లేదు. పది అంకెలూ చెప్పండి."},
 "kn-IN": {
  "rb_register": "ಹೊಸ ಗ್ರಾಹಕ: {details}. ಸಾಲದ ಮಿತಿ {limit} ರೂಪಾಯಿ. ನೋಂದಣಿ ಮಾಡಲೇ?",
  "ask_items": "{name} ಏನು ತೆಗೆದುಕೊಂಡರು?",
  "registered": "ಗ್ರಾಹಕ {name} ನೋಂದಣಿಯಾಗಿದ್ದಾರೆ.",
  "err_duplicate": "{details} ಈಗಾಗಲೇ ನೋಂದಣಿಯಾಗಿದ್ದಾರೆ. ಅವರ ಖಾತೆಗೇ ಬರೆಯಲೇ?",
  "err_bad_phone": "ಫೋನ್ ಸಂಖ್ಯೆ ಸರಿಯಿಲ್ಲ. ದಯವಿಟ್ಟು ಹತ್ತು ಅಂಕೆಗಳನ್ನೂ ಹೇಳಿ."},
 "ml-IN": {
  "rb_register": "പുതിയ ഉപഭോക്താവ്: {details}. കടത്തിന്റെ പരിധി {limit} രൂപ. രജിസ്റ്റർ ചെയ്യട്ടെ?",
  "ask_items": "{name} എന്താണ് വാങ്ങിയത്?",
  "registered": "ഉപഭോക്താവ് {name} രജിസ്റ്റർ ചെയ്തു.",
  "err_duplicate": "{details} ഇതിനകം രജിസ്റ്റർ ചെയ്തിട്ടുണ്ട്. അവരുടെ അക്കൗണ്ടിൽ തന്നെ എഴുതട്ടെ?",
  "err_bad_phone": "ഫോൺ നമ്പർ ശരിയല്ല. പത്ത് അക്കങ്ങളും പറയൂ."},
 "pa-IN": {
  "rb_register": "ਨਵਾਂ ਗਾਹਕ: {details}. ਉਧਾਰ ਦੀ ਹੱਦ {limit} ਰੁਪਏ. ਦਰਜ ਕਰਾਂ?",
  "ask_items": "{name} ਨੇ ਕੀ ਲਿਆ?",
  "registered": "ਗਾਹਕ {name} ਦਰਜ ਹੋ ਗਿਆ.",
  "err_duplicate": "{details} ਪਹਿਲਾਂ ਹੀ ਦਰਜ ਹਨ. ਉਨ੍ਹਾਂ ਦੇ ਖਾਤੇ ਵਿੱਚ ਹੀ ਲਿਖਾਂ?",
  "err_bad_phone": "ਫ਼ੋਨ ਨੰਬਰ ਸਹੀ ਨਹੀਂ ਹੈ. ਕਿਰਪਾ ਕਰਕੇ ਪੂਰੇ ਦਸ ਅੰਕ ਦੱਸੋ."},
 "od-IN": {
  "rb_register": "ନୂଆ ଗ୍ରାହକ: {details}. ଉଧାର ସୀମା {limit} ଟଙ୍କା. ଦାଖଲ କରିବି?",
  "ask_items": "{name} କ'ଣ ନେଲେ?",
  "registered": "ଗ୍ରାହକ {name} ଦାଖଲ ହେଲେ.",
  "err_duplicate": "{details} ଆଗରୁ ଦାଖଲ ଅଛନ୍ତି. ସେମାନଙ୍କ ଖାତାରେ ଲେଖିବି?",
  "err_bad_phone": "ଫୋନ ନମ୍ବର ଠିକ୍ ନୁହେଁ. ଦୟାକରି ପୂରା ଦଶ ଅଙ୍କ କୁହନ୍ତୁ."},
}