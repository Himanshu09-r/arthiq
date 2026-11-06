import os, sys, base64
from dotenv import load_dotenv
from sarvamai import SarvamAI
from app.languages import SUPPORTED, get_language

load_dotenv()
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

SAMPLES = {
    "hi-IN": "रमेश ने दो किलो चावल और एक बिस्किट का पैकेट उधार लिया",
    "mr-IN": "रमेशने दोन किलो तांदूळ आणि एक बिस्किट पुडा उधार घेतला",
    "gu-IN": "રમેશે બે કિલો ચોખા અને એક બિસ્કિટ પેકેટ ઉધાર લીધું",
    "en-IN": "Ramesh took two kilos of rice and one packet of biscuits on credit",
}

code = sys.argv[1] if len(sys.argv) > 1 else "hi-IN"
lang = get_language(code)
text = SAMPLES.get(code, SAMPLES["hi-IN"])
path = f"data/test_{code}.wav"
print(f"Language: {lang.name} ({code})")

try:  # 1. Text to speech
    tts = client.text_to_speech.convert(
        text=text, language_code=code, model="bulbul:v3", speaker=lang.speaker)
    with open(path, "wb") as f:
        f.write(base64.b64decode(tts.audios[0]))
    print("TTS OK ->", path)
except Exception as e:
    print("TTS FAILED:", e); sys.exit(1)

try:  # 2. Speech to text
    stt = client.speech_to_text.transcribe(
        file=open(path, "rb"), model="saaras:v4", mode="codemix")
    print("STT OK:", stt.transcript, "| detected:", stt.language_code)
except Exception as e:
    print("STT FAILED:", e)

try:  # 3. LLM
    r = client.chat.completions(
        model=os.getenv("SARVAM_LLM_MODEL", "sarvam-105b"),
        messages=[{"role": "user", "content": 'Reply with only this JSON: {"ok": true}'}],
        max_tokens=100)
    print("LLM OK:", r.choices[0].message.content)
except Exception as e:
    print("LLM FAILED:", e)