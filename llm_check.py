import os
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
r = client.chat.completions(
    model=os.getenv("SARVAM_LLM_MODEL", "sarvam-105b"),
    messages=[{"role": "user", "content": 'Reply with only this JSON: {"ok": true}'}],
    max_tokens=1000)
print(r.choices[0].finish_reason)
print(r.choices[0].message)
print(r.usage)