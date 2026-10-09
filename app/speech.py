"""From a script to one clip: cut the text into pieces, speak each, join them."""

from __future__ import annotations

import re
import secrets
import shutil
import time
import unicodedata
import wave
from pathlib import Path

import engines
import paths
import store
import voices
from catalog import MODELS, PIECE_CHARS, RUNTIMES
from jobs import UserError

# Sentence enders, including the Hindi danda and double danda (written as code
# points so this file stays plain ASCII).
_ENDERS = ".!?" + chr(0x0964) + chr(0x0965)
_SOFT = ",;:" + chr(0x2014)
GAP_SECONDS = 0.25
MAX_SCRIPT = 20000
HISTORY_KEEP = 500


def split_script(text: str, limit: int = PIECE_CHARS) -> list[str]:
    """Pieces of at most `limit` characters, cut at sentence ends where possible.

    A new line always ends a sentence. A single sentence longer than the
    limit is cut at a comma, and only as a last resort between two words.
    """
    sentences: list[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        line = " ".join(line.split())
        current = ""
        for ch in line:
            current += ch
            if ch in _ENDERS:
                sentences.append(current.strip())
                current = ""
        if current.strip():
            sentences.append(current.strip())

    def cut_long(s: str) -> list[str]:
        out = []
        while len(s) > limit:
            window = s[:limit]
            at = max(window.rfind(c) for c in _SOFT)
            if at < limit // 3:
                at = window.rfind(" ")
            if at < limit // 3:
                at = limit - 1
            out.append(s[: at + 1].strip())
            s = s[at + 1 :].strip()
        if s:
            out.append(s)
        return out

    pieces, buf = [], ""
    for s in (part for sentence in sentences for part in cut_long(sentence)):
        if not re.search(r"\w", s):
            continue  # nothing to say in a row of dots
        if buf and len(buf) + 1 + len(s) > limit:
            pieces.append(buf)
            buf = s
        else:
            buf = (buf + " " + s).strip()
    if buf:
        pieces.append(buf)
    return pieces


def join_wavs(parts: list[Path], out: Path, gap: float = GAP_SECONDS) -> float:
    """Join clips of the same format with a short pause between. Returns the length in seconds."""
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
    silence = bytes(int(params.framerate * gap) * params.nchannels * params.sampwidth)
    frames = 0
    with wave.open(str(out), "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        for n, part in enumerate(parts):
            with wave.open(str(part), "rb") as r:
                if (r.getnchannels(), r.getsampwidth(), r.getframerate()) != (params.nchannels, params.sampwidth, params.framerate):
                    raise UserError("The engine changed its audio format between pieces; the clip could not be joined.")
                data = r.readframes(r.getnframes())
            if n:
                w.writeframes(silence)
                frames += len(silence) // (params.nchannels * params.sampwidth)
            w.writeframes(data)
            frames += len(data) // (params.nchannels * params.sampwidth)
    return frames / float(params.framerate)


def history() -> list[dict]:
    return store.read(paths.HISTORY, [])


def clip_path(clip_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-z-]{8,40}", clip_id):
        return None
    p = paths.OUTPUTS / f"{clip_id}.wav"
    return p if p.exists() else None


def delete_clip(clip_id: str) -> None:
    p = clip_path(clip_id)
    if p:
        p.unlink(missing_ok=True)
    store.update(paths.HISTORY, [], lambda items: [c for c in items if c["id"] != clip_id])


def download_name(clip: dict) -> str:
    """A file name from the first words of the script. Letters, digits and
    combining marks are kept: dropping the marks would strip the vowel signs
    out of Hindi words."""
    kept = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in clip.get("text", ""))
    slug = "-".join(kept.split()[:6])[:48] or "voice"
    return f"{slug}-{clip['id'][-6:]}.wav"


def generate(job, text: str, voice_id: str, model_id: str, language: str) -> dict:
    text = text.strip()
    if not text:
        raise UserError("Write something to say first.")
    if len(text) > MAX_SCRIPT:
        raise UserError(f"This script is {len(text):,} characters long. Make it shorter than {MAX_SCRIPT:,}, or do it in two parts.")
    if model_id not in MODELS or not engines.model_ready(model_id):
        raise UserError("That model is not installed. Install it on the Models page.")
    voice = voices.path_of(voice_id) if voice_id else None
    if voice_id and voice is None:
        raise UserError("That voice was not found. Pick another voice.")
    entry = engines.installed()["models"][model_id]
    rt = entry["runtime"]
    pieces = split_script(text)
    if not pieces:
        raise UserError("There are no words in this script.")

    clip_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    work = paths.DOWNLOADS / f"job-{clip_id}"
    work.mkdir(parents=True, exist_ok=True)
    started, parts, worked = time.time(), [], 0.0
    try:
        for n, piece in enumerate(pieces):
            words = f"Speaking part {n + 1} of {len(pieces)}" if len(pieces) > 1 else "Speaking"
            job.report(n / len(pieces), words)
            part = work / f"{n:04d}.wav"
            made = engines.speak(rt, model_id, piece, part, voice, language, job.cancelled, status=lambda say, words=words: job.report(detail=say or words))
            # "work" leaves out a model's one-time start, where the engine reports it.
            worked += made.get("work") or made["seconds"]
            parts.append(part)
        job.report(0.99, "Joining the parts" if len(parts) > 1 else "Saving")
        out = paths.OUTPUTS / f"{clip_id}.wav"
        if len(parts) == 1:
            shutil.copyfile(parts[0], out)
            audio = engines.wav_seconds(out)
        else:
            audio = join_wavs(parts, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    took = time.time() - started
    clip = {
        "id": clip_id,
        "text": text,
        "voice_id": voice_id or "",
        "voice": voices.name_of(voice_id) if voice_id else "No voice (model's own)",
        "model": model_id,
        "model_name": MODELS[model_id]["name"],
        "runtime": rt,
        "device": RUNTIMES[rt]["backend"],
        "language": language,
        "seconds": round(took, 1),
        "audio": round(audio, 1),
        "pieces": len(pieces),
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }

    def add(items: list) -> list:
        items.insert(0, clip)
        for old in items[HISTORY_KEEP:]:
            (paths.OUTPUTS / f"{old['id']}.wav").unlink(missing_ok=True)
        return items[:HISTORY_KEEP]

    store.update(paths.HISTORY, [], add)
    # What this PC really does, for the Models page: a running average of recent clips.
    if audio >= 2:
        def note(data: dict) -> dict:
            m = data.setdefault("models", {}).get(model_id)
            if m:
                now = worked / audio * 10
                m["per10"] = round(now if not m.get("per10") else m["per10"] * 0.6 + now * 0.4, 1)
            return data

        store.update(paths.INSTALLED, {}, note)
    return {"clip": clip}
