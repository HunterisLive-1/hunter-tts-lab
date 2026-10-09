"""Script polishing with the user's own Google Gemini key.

The key is typed by the user on the Settings page, kept in data\\config.json
on their PC, and sent to one place only: Google's Gemini API. This file is
the only one that talks to it.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from jobs import UserError

class ModelUnavailable(UserError):
    """This model cannot be used right now (its free limit is used up, or Google
    withdrew it). Another model may well work, so the caller can try one."""


API = "https://generativelanguage.googleapis.com/v1beta"
MAX_INPUT = 12000

# Models that are not for rewriting text.
_NOT_TEXT = ("embedding", "imagen", "image", "banana", "tts", "audio", "live", "veo", "aqa", "vision", "robotics", "computer-use",
             "learnlm", "lyria", "transcribe", "deep-research", "antigravity")  # fmt: skip


def _call(key: str, path: str, body: dict | None = None, timeout: float = 90):
    req = urllib.request.Request(
        f"{API}/{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"x-goog-api-key": key, "Content-Type": "application/json", "User-Agent": "HunterTTSLab/1.0"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
        except ValueError:
            said = ""
        if e.code in (400, 401, 403) and re.search(r"api key|permission|credential|unauthori", said, re.I):
            raise UserError("Google did not accept this API key. Check that it was copied whole, with no spaces.") from e
        if e.code == 429:
            raise ModelUnavailable("This model's free limit is used up for now. Wait a minute, or pick another model in Settings.") from e
        if e.code == 404:
            raise ModelUnavailable("Google no longer offers this model. Pick another one in Settings.") from e
        if e.code >= 500:
            raise UserError("Google's service is having trouble right now. Try again in a minute.") from e
        raise UserError(f"Google refused the request: {said[:200] or e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UserError("Could not reach Google. Check the internet connection.") from e


def usually_free(model_id: str) -> bool:
    """Google decides what is free and changes it; the Flash, Flash-Lite and
    Gemma families are the ones its free tier has covered."""
    return any(w in model_id for w in ("flash", "gemma"))


def list_models(key: str) -> list[dict]:
    """Text models this key can use, the usually-free ones first, newest first."""
    found, token = [], ""
    for _ in range(5):
        page = _call(key, "models?pageSize=200" + (f"&pageToken={token}" if token else ""), timeout=30)
        for m in page.get("models", []):
            mid = m.get("name", "").removeprefix("models/")
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if any(w in mid for w in _NOT_TEXT):
                continue
            found.append({"id": mid, "name": m.get("displayName") or mid, "free": usually_free(mid)})
        token = page.get("nextPageToken", "")
        if not token:
            break

    def version(mid: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)", mid)
        return float(m.group(1)) if m else 0.0

    def rank(mid: str) -> int:
        """The order to offer them in: the plain Gemini Flash models are the
        best free ones for rewriting Hindi, so the newest of those is first
        and becomes the default."""
        if not usually_free(mid):
            return 9
        if any(w in mid for w in ("preview", "exp", "omni")):
            return 5
        if "latest" in mid:
            return 4
        if "gemma" in mid:
            return 3
        return 2 if "lite" in mid else 1

    found.sort(key=lambda m: (rank(m["id"]), -version(m["id"]), m["id"]))
    return found


_RULES = """You prepare scripts for a text-to-speech voice. Rewrite the user's script so a speech engine reads it aloud correctly and naturally.

Rules:
- Keep the meaning, the order and the tone. Do not add ideas, do not remove ideas, do not answer or comment on the script.
- Fix spelling and punctuation. Every sentence ends with a full stop, a question mark or an exclamation mark.
- Break a very long sentence into two or three shorter ones.
- Write numbers, dates, times, money, units, symbols and abbreviations the way they are spoken aloud, in the language of the sentence they are in (in a Hindi sentence a number is a Hindi number word).
- Remove emojis, hashtags, markdown, stage directions and web links.
- Output only the rewritten script: no title, no quotes around it, no notes."""

_SCRIPTS = {
    "keep": "Keep each word in the script it is written in. Hindi typed in English letters stays in English letters.",
    "devanagari": "Write every Hindi word in Devanagari script, including Hindi that the user typed in English letters. "
    "Keep words that are really English (brand names, product names, technical terms) in English letters.",
    "english": "The script is in English. Keep it in English.",
}


_OTHER = "The script is in {language}. Keep it in {language}, in the writing that language normally uses. Do not translate it."


def polish(key: str, model: str, text: str, script: str = "keep", language: str | None = None) -> str:
    """`language` is the name of the script's language when it is neither Hindi nor English."""
    text = text.strip()
    if not text:
        raise UserError("Write something to polish first.")
    if len(text) > MAX_INPUT:
        raise UserError(f"This script is too long to polish in one go ({len(text):,} characters). Polish it in parts of up to {MAX_INPUT:,}.")
    body = {
        "systemInstruction": {"parts": [{"text": _RULES + "\n- " + (_OTHER.format(language=language) if language else _SCRIPTS.get(script, _SCRIPTS["keep"]))}]},
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.2},
    }
    reply = _call(key, f"models/{model}:generateContent", body)
    candidates = reply.get("candidates") or []
    if not candidates:
        why = reply.get("promptFeedback", {}).get("blockReason")
        raise UserError("Google's model declined to rewrite this script." + (f" Reason given: {why}." if why else ""))
    out = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) if not p.get("thought")).strip()
    out = re.sub(r"^```[a-z]*\s*|\s*```$", "", out).strip().strip('"').strip()
    if not out:
        raise UserError("Google's model sent back an empty answer. Try again, or pick another model in Settings.")
    return out
