"""9Router client — the only AI entry point (replaces Groq/Gemini/Ollama chain).

OpenAI-compatible chat completions over plain requests; no SDK dependency.
Config from clipper/.env (NINEROUTER_BASE_URL, NINEROUTER_API_KEY).
"""
import json
import os
import sys
import time

import requests

_BASE = os.path.dirname(os.path.abspath(__file__))


def _load_env():
    """Tiny .env loader — no python-dotenv dependency for two variables."""
    path = os.path.join(_BASE, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()
BASE_URL = os.environ.get("NINEROUTER_BASE_URL", "http://localhost:20128/v1")
API_KEY = os.environ.get("NINEROUTER_API_KEY", "")
MODEL = os.environ.get("NINEROUTER_MODEL", "ds/deepseek-v4-pro")
# When the primary model is rate-limited, the work is not wrong — the queue is
# full. Swapping to a second combo costs one retry and saves the whole job.
FALLBACK_MODEL = os.environ.get("NINEROUTER_FALLBACK_MODEL", "")
# A transcript review sends 400+ words and waits for all of them back, which
# ran past the old 120s ceiling and silently cost a render its caption fixes.
# Configurable because the right value depends on the model behind the router.
TIMEOUT = int(os.environ.get("NINEROUTER_TIMEOUT", "300"))
# PRD §5 (rate-limit awareness): a tunnel hiccup or a 5xx from the router is
# transient, and one of them used to fail a whole task. Retry with backoff;
# 4xx is a bad request and is raised straight away — except 429, which is a
# queue signal rather than a malformed request and gets the same treatment as
# a 5xx.
RETRIES = int(os.environ.get("NINEROUTER_RETRIES", "3"))
BACKOFF = float(os.environ.get("NINEROUTER_BACKOFF", "2.0"))


def _is_rate_limit(exc):
    """True for the router's 'slow down' signals, as opposed to a bad request."""
    resp = getattr(exc, "response", None)
    if resp is not None and resp.status_code == 429:
        return True
    return "429" in str(exc) or "rate" in str(exc).lower()


def _post(system, user, model, temperature):
    """POST one completion, retrying transport errors, 5xx and 429 with backoff."""
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            last = e
        else:
            # 429 is not a client mistake: the request was fine and the queue
            # was not. Treat it like a 5xx so it reaches the backoff below
            # rather than failing the job on the first try.
            if resp.status_code == 429:
                last = requests.HTTPError("429 rate limited by router",
                                          response=resp)
            elif resp.status_code < 500:
                resp.raise_for_status()
                return resp
            else:
                last = requests.HTTPError(f"{resp.status_code} from router",
                                          response=resp)
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF * (2 ** attempt))
    raise last


def chat_json(system, user, model=MODEL, temperature=0.7):
    """One chat completion that must return a JSON object. Returns parsed dict.

    A rate-limited primary model falls back to FALLBACK_MODEL once before
    giving up: the request was well formed, so a different queue is far more
    likely to answer it than a fourth attempt at the same one.
    Raises on transport error or unparseable output — caller decides fallback.
    """
    try:
        resp = _post(system, user, model, temperature)
    except Exception as e:
        if not (_is_rate_limit(e) and FALLBACK_MODEL and FALLBACK_MODEL != model):
            raise
        print("  ai: %s rate limited, switching to %s" % (model, FALLBACK_MODEL),
              file=sys.stderr)
        resp = _post(system, user, FALLBACK_MODEL, temperature)
    # 9Router labels the reply text/event-stream with no charset, so requests
    # would guess ISO-8859-1 and mangle emoji — decode UTF-8 explicitly. It
    # also appends "data: [DONE]" after the JSON body, so raw_decode takes the
    # first object.
    body, _ = json.JSONDecoder().raw_decode(resp.content.decode("utf-8").strip())
    text = body["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):  # some models still fence despite json mode
        text = text.strip("`")
        text = text[4:] if text.startswith("json") else text
    return json.loads(text)


if __name__ == "__main__":
    # Live check (needs tunnel on PC): list models + one tiny JSON completion.
    r = requests.get(f"{BASE_URL}/models",
                     headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
    print("models:", r.status_code, str(r.json())[:200] if r.ok else r.text[:200])
    out = chat_json("Reply as JSON.", 'Return {"ok": true} exactly.')
    assert out.get("ok") is True, out
    print("chat_json OK:", out)
