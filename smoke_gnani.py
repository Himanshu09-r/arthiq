import os, sys, time
from dotenv import load_dotenv
load_dotenv()


from app.voice import gnani
from app.voice.provider import GNANI_LANGS, provider_for, main_provider
from app.voice.templates import say

os.makedirs("data", exist_ok=True)
print("SPEECH_PROVIDER =", main_provider(), "| Odia is routed to:", provider_for("od-IN"))

for code in (sys.argv[1:] or sorted(GNANI_LANGS)):
    text = say(code, "rb_credit_amount", name="Ramesh", total=130)
    print(f"\n== {code}\n  text: {text}")
    try:
        t0 = time.time()
        wav = gnani.tts(text, code)
        open(f"data/gnani_{code}.wav", "wb").write(wav)
        print(f"  TTS OK: {len(wav) // 1024} KB, {time.time() - t0:.1f}s -> data\\gnani_{code}.wav")
    except Exception as e:
        print("  TTS FAILED:", e)
        continue
    try:
        t0 = time.time()
        tr, det = gnani.stt(wav, code)
        print(f"  STT OK: {tr}  | detected: {det}, {time.time() - t0:.1f}s")
    except Exception as e:
        print("  STT FAILED:", e)
