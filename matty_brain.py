"""
matty_brain.py - Hybrid Cloud + Offline AI Brain with Rate Limit Failover
Uses free Groq endpoints for ultra-fast responses, and smoothly falls back
to offline local processing if API rate limits or network issues occur.
"""

import os
import json
import sys
import time
import re
from openai import OpenAI
import matty_actions
import matty_config

# Console safety: replies may contain ₹, Hindi, Arabic or Chinese. Windows
# consoles are often cp1252 and would raise UnicodeEncodeError on print().
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

# Load .env before anything reads a key, so GROQ_API_KEY is available even when
# it was never exported in the shell. Real environment variables still win.
matty_config.load_env()

KEYFILE = os.path.expanduser("~/.matty/free.key")
LEGACY_KEYFILE = os.path.expanduser("~/.openjarvis/free.key")
# Models are tried in order. A model can be retired or throttled on its own,
# so the list is a failover chain. "qwen/qwen3.8-27b" was not a real Groq model
# and made every request fail, so the list now only contains live models.
MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]

_client = None
_history = []
_cooldown_until = 0.0
_last_error = ""  # last cloud failure, shown to the user instead of a guess

SYSTEM_PROMPT = """You are Matty, a fast, highly capable AI executive assistant running on the user's computer.
Respond concisely in 1-2 sentences. Be direct, helpful, and natural. Do not use filler or formal corporate jargon.

LANGUAGE RULE: always answer in the SAME language the user just used.
Hindi -> Hindi, Hinglish -> Hinglish, Spanish -> Spanish, Arabic -> Arabic, and so on.
Never translate the user's words into English unless they explicitly ask you to.
If the user mixes languages, reply in the same mix.
"""


def _clean_key(key):
    """Trim pasted whitespace/quotes and drop stray non-ASCII characters."""
    key = key.strip().strip("\"'").strip()
    key = "".join(ch for ch in key if ch.isascii() and ch.isprintable())
    return key or None


def _get_api_key():
    """Look for the Groq key in this order:

    STEP 1  GROQ_API_KEY environment variable (set by .env or the shell)
    STEP 2  ~/.matty/free.key      (legacy location, read-only fallback)
    STEP 3  ~/.openjarvis/free.key (older legacy location)

    Returns None when no key exists -> Matty runs in offline mode.
    """
    if os.environ.get("GROQ_API_KEY"):
        return _clean_key(os.environ["GROQ_API_KEY"])
    for keyfile in (KEYFILE, LEGACY_KEYFILE):
        if os.path.exists(keyfile):
            with open(keyfile, encoding="utf-8", errors="ignore") as f:
                return _clean_key(f.read())
    return None


def ready():
    """Returns True if the cloud brain is active and not currently rate-limited."""
    key = _get_api_key()
    if not key:
        return False
    return time.time() >= _cooldown_until


def _is_rate_limited(e):
    status = getattr(e, "status_code", None)
    if status == 429:
        return True
    s = str(e).lower()
    return any(w in s for w in ("429", "rate limit", "too many requests", "rate_limit", "exceeded"))


def _retry_after_seconds(e, default=60):
    s = str(e).lower()
    m = re.search(r"try again in\s*(\d+)m\s*([0-9]+(?:\.[0-9]+)?)s", s)
    if m:
        return int(float(m.group(1)) * 60 + float(m.group(2))) + 2
    m = re.search(r"try again in\s*([0-9]+(?:\.[0-9]+)?)s", s)
    if m:
        return int(float(m.group(1))) + 2
    return default


def _set_cooldown(secs):
    global _cooldown_until
    _cooldown_until = max(_cooldown_until, time.time() + float(secs))


def _local_fallback(q):
    """Answer without the cloud model, and say WHY the cloud was not used.

    Three different situations used to produce the same misleading sentence
    ("Cloud API is cooling down"), which made a missing API key look like a
    rate limit. Each case now gets its own honest message.
    """
    # 1. Local actions still work even with no key at all.
    action_res = matty_actions.try_action(q)
    if action_res:
        return action_res

    # 2. No key configured -> tell the user how to fix it.
    if not _get_api_key():
        return (
            "I don't have a Groq API key yet, so I can only run local commands. "
            "Click SET KEY in the HUD and paste your free key from "
            "console.groq.com/keys."
        )

    # 3. Key exists but the model is rate limited right now.
    if time.time() < _cooldown_until:
        left = int(_cooldown_until - time.time())
        return (
            f"The cloud model is rate limited for another {left} seconds. "
            "Local commands still work meanwhile."
        )

    # 4. Key exists, no cooldown, but every model call failed.
    detail = f" Last error: {_last_error[:160]}" if _last_error else ""
    return (
        "I couldn't reach the cloud model just now. Local commands still work - "
        "try 'open chrome', 'lock my laptop' or 'stock market report'."
        + detail
    )


def cloud_test():
    """Make one tiny real API call and return the exact result or error.

    This is the TEST CLOUD button: it removes all guessing about whether the
    key is valid, the model name is right, or the network is blocked.
    """
    key = _get_api_key()
    if not key:
        return "No API key found. Click SET KEY and paste your gsk_... key."

    try:
        client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model=MODELS[0],
            messages=[{"role": "user", "content": "Reply with the single word OK"}],
            max_tokens=5,
        )
        answer = (resp.choices[0].message.content or "").strip()
        return f"Cloud OK - {MODELS[0]} replied: {answer}"
    except Exception as exc:
        return f"Cloud FAILED - {type(exc).__name__}: {exc}"


def save_api_key(key):
    """Validate and store a Groq key in .env, then reset the client.

    Called by the SET KEY button in the HUD, so the key can be added without
    touching the console (the voice thread must never block on input()).
    The key is written to .env as GROQ_API_KEY - never to a JSON file.
    """
    global _client, _cooldown_until

    key = _clean_key(key or "")
    if not key:
        return "No key received. Nothing changed."
    if not key.startswith("gsk_"):
        return "That does not look like a Groq key - it should start with gsk_."

    path = matty_config.save_env_value("GROQ_API_KEY", key)

    # Drop the cached client and any cooldown so the next question uses it.
    _client = None
    _cooldown_until = 0.0
    return f"Groq API key saved to {os.path.basename(path)}. Cloud answers are enabled now."


def cloud_status():
    """Small status dict for the HUD footer (ONLINE / OFFLINE)."""
    key = _get_api_key()
    left = max(0, int(_cooldown_until - time.time()))
    return {"has_key": bool(key), "cooldown": left, "ready": bool(key) and left == 0}


def think(q):
    """Turn one spoken/typed command into a reply string.

    The order matters, and it is the reason Matty feels instant:

    STEP 1  Local actions first. "lock my laptop", "open chrome", "play x on
            YouTube" etc. are executed by matty_actions with no network call.
    STEP 2  If there is no API key, or the last call hit a rate limit and the
            cooldown has not expired, answer from _local_fallback() instead of
            showing an error.
    STEP 3  Otherwise ask the cloud model, trying each model in MODELS in turn
            (a model can be retired or throttled individually).
    STEP 4  A 429 / rate-limit error is not a crash: remember how long the
            limit lasts, then fall back locally.
    STEP 5  Any other model error just moves on to the next model.
    """
    global _client, _history, _last_error

    # STEP 1 - instant offline actions
    local_done = matty_actions.try_action(q)
    if local_done:
        return local_done

    # STEP 2 - no key / still cooling down -> local answer
    key = _get_api_key()
    if not key or time.time() < _cooldown_until:
        return _local_fallback(q)

    # STEP 3 - build the request: system prompt + short memory + new command
    if _client is None:
        _client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + _history[-6:] + [{"role": "user", "content": q}]

    for model in MODELS:
        try:
            resp = _client.chat.completions.create(
                model=model,
                messages=msgs,
                max_tokens=350,
                temperature=0.6,
            )
            answer = resp.choices[0].message.content.strip()
            _history += [{"role": "user", "content": q}, {"role": "assistant", "content": answer}]
            return answer
        except Exception as e:
            # STEP 4 - rate limit: cool down, then answer locally
            if _is_rate_limited(e):
                wait_sec = _retry_after_seconds(e)
                _set_cooldown(wait_sec)
                print(f"[Rate-limit triggered: cooldown for {wait_sec}s]", flush=True)
                return _local_fallback(q)
            # STEP 5 - model specific problem: try the next model
            _last_error = f"{model}: {type(e).__name__}: {e}"
            print(f"[Model {model} failed: {e}]", flush=True)

    return _local_fallback(q)


if __name__ == "__main__":
    print("Testing Matty Brain...")
    print(think("what time is it"))
    print(think("how are you"))
