"""The voice library: short recordings of a voice, saved under a name.

The page turns whatever the user uploads or records into a plain WAV before
it gets here, so this file only has to check and store it.
"""

from __future__ import annotations

import io
import re
import secrets
import time
import wave
from pathlib import Path

import paths
import store
from jobs import UserError

SAMPLE_ID = "sample"
SAMPLE = {"id": SAMPLE_ID, "name": "Sample voice", "seconds": 0.0, "created": "", "builtin": True,
          "note": "Made by a computer, not a real person. Good for a first try."}  # fmt: skip
MIN_SECONDS, MAX_SECONDS = 3.0, 30.0
MAX_BYTES = 12 * 1024 * 1024


def _sample_path() -> Path:
    return paths.WEB / "sample-voice.wav"


def _seconds(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
                raise UserError("That file is not a plain 16-bit WAV. Add it through this page, which converts it for you.")
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, EOFError) as e:
        raise UserError("That recording could not be read as audio.") from e


def all_voices() -> list[dict]:
    items = list(store.read(paths.VOICE_INDEX, []))
    sample = _sample_path()
    if sample.exists():
        try:
            secs = round(_seconds(sample.read_bytes()), 1)
        except UserError:
            secs = 0.0
        items.append({**SAMPLE, "seconds": secs})
    return items


def path_of(voice_id: str) -> Path | None:
    if voice_id == SAMPLE_ID:
        p = _sample_path()
        return p if p.exists() else None
    if not re.fullmatch(r"[0-9a-f]{12}", voice_id or ""):
        return None
    p = paths.VOICES / f"{voice_id}.wav"
    return p if p.exists() else None


def name_of(voice_id: str) -> str:
    return next((v["name"] for v in all_voices() if v["id"] == voice_id), "Unknown voice")


def _clean_name(name: str) -> str:
    name = " ".join(re.sub(r"[\x00-\x1f<>]", "", name or "").split())[:40]
    return name or "My voice"


def add(name: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise UserError("That recording is too large. 5 to 10 seconds is all a voice needs.")
    seconds = _seconds(data)
    if seconds < MIN_SECONDS:
        raise UserError(f"That recording is {seconds:.1f} seconds long. It needs at least {MIN_SECONDS:.0f} seconds of speech.")
    if seconds > MAX_SECONDS:
        raise UserError(f"That recording is {seconds:.0f} seconds long. Keep it under {MAX_SECONDS:.0f} seconds; 5 to 10 is best.")
    voice = {"id": secrets.token_hex(6), "name": _clean_name(name), "seconds": round(seconds, 1), "created": time.strftime("%Y-%m-%d %H:%M")}
    paths.VOICES.mkdir(parents=True, exist_ok=True)
    tmp = paths.VOICES / f"{voice['id']}.tmp"
    tmp.write_bytes(data)
    tmp.replace(paths.VOICES / f"{voice['id']}.wav")
    store.update(paths.VOICE_INDEX, [], lambda items: [voice] + items)
    return voice


def rename(voice_id: str, name: str) -> None:
    def change(items: list) -> list:
        for v in items:
            if v["id"] == voice_id:
                v["name"] = _clean_name(name)
        return items

    store.update(paths.VOICE_INDEX, [], change)


def delete(voice_id: str) -> None:
    p = path_of(voice_id)
    if voice_id != SAMPLE_ID and p:
        p.unlink(missing_ok=True)
    store.update(paths.VOICE_INDEX, [], lambda items: [v for v in items if v["id"] != voice_id])
