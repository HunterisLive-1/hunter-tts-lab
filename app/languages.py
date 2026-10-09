"""Which languages each model can speak.

The lists are the model makers' own: 19 of Resemble AI's 23 for Chatterbox
(see below), OpenBMB's 30 for VoxCPM2, and k2-fsa's table of 646 for
OmniVoice (omni-languages.json, taken from the OmniVoice package). We
measured Hindi, Hinglish and English ourselves, and made one clip in each of
49 other languages to see that it is spoken at all; the page says so wherever
another language is picked.

A language has one code in this app, whichever model speaks it. Where a model
calls the language something else, GIVEN says what the engine is handed.
"""

from __future__ import annotations

import json
from pathlib import Path

# Chatterbox's makers list 23. Four of them (Chinese, Hebrew, Japanese, Russian)
# need their text prepared in a way the audio.cpp engine does not do: it stops
# with "unsupported Chatterbox language". We tried all 23 through this app and
# list the 19 that made a clip.
CHATTERBOX = ("ar", "da", "de", "el", "en", "es", "fi", "fr", "hi", "it", "ko", "ms", "nl", "no", "pl", "pt", "sv", "sw", "tr")
VOXCPM2 = ("ar", "my", "zh", "da", "nl", "en", "fi", "fr", "de", "el", "he", "hi", "id", "it", "ja", "km", "ko", "lo", "ms", "no", "pl", "pt", "ru",
           "es", "sw", "sv", "tl", "th", "tr", "vi")  # fmt: skip

_OMNI: dict[str, str] = json.loads(Path(__file__).with_name("omni-languages.json").read_text(encoding="utf-8"))

# this app's code -> the code the model itself uses
GIVEN: dict[str, dict[str, str]] = {
    "omnivoice": {"ar": "arb", "tl": "fil"},  # it lists "Standard Arabic" and "Filipino"
}
_HIDDEN = {model: set(codes.values()) for model, codes in GIVEN.items()}

NAMES: dict[str, str] = {**_OMNI, "ar": "Arabic", "tl": "Tagalog", "pa": "Punjabi"}

# Shown first in the list: most people who use this app speak one of these.
INDIA = ("bn", "ta", "te", "mr", "gu", "pa", "ur", "kn", "ml", "ory", "as", "npi", "bho", "mai", "sa", "sd", "gom", "ks", "mni", "sat", "brx", "tcy")

# Written without spaces between words, or in dense blocks: a second of speech
# is 4 to 6 characters instead of about 16, so a piece of text has to be
# shorter to be the same length when spoken.
DENSE = frozenset(("zh", "ja", "ko", "th", "lo", "km", "my", "yue", "nan", "bo"))

_BY_MODEL: dict[str, frozenset] = {
    "chatterbox": frozenset(CHATTERBOX),
    "voxcpm2": frozenset(VOXCPM2),
    "omnivoice": frozenset((set(_OMNI) - _HIDDEN["omnivoice"]) | set(GIVEN["omnivoice"])),
}


def name(code: str) -> str:
    return NAMES.get(code, code)


def known(code) -> bool:
    return isinstance(code, str) and any(code in codes for codes in _BY_MODEL.values())


def speaks(model_id: str, code: str) -> bool:
    return code in _BY_MODEL.get(model_id, ())


def supported(model_id: str) -> list[list[str]]:
    """[code, name] for every language the model speaks, by name."""
    return sorted(([code, name(code)] for code in _BY_MODEL.get(model_id, ())), key=lambda pair: pair[1])


def given(model_id: str, code: str) -> str:
    """What the engine is handed for this language."""
    return GIVEN.get(model_id, {}).get(code, code)


def for_page() -> dict:
    return {"models": {model: supported(model) for model in _BY_MODEL}, "india": list(INDIA), "dense": sorted(DENSE)}
