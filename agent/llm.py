import json, os, re
from dotenv import load_dotenv
from sarvamai import SarvamAI

load_dotenv()
MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")
_client = None


class LLMError(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        _client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
    return _client


def _parse_json(text: str):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in reply")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str, max_tokens: int = 1500, attempts: int = 2) -> dict:
    """Ask the LLM for a JSON object. Reasoning is OFF for speed."""
    last = None
    for _ in range(attempts):
        try:
            r = _get_client().chat.completions(
                model=MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens, temperature=0.1, reasoning_effort=None)
            return _parse_json(r.choices[0].message.content or "")
        except Exception as e:
            last = e
    raise LLMError(str(last))