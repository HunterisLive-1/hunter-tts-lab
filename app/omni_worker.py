"""OmniVoice's side of the conversation. This file runs inside OmniVoice's own
Python, not the app's.

The app (omni_engine.py) starts it, keeps it running while clips are being
made, and talks to it in lines of JSON: one request in on standard input, one
answer out on standard output, marked with "@@" so that nothing a library
prints can be mistaken for an answer.

    {"op": "hear", "voice": "C:/.../voice.wav"}
        -> {"ok": true, "text": "what the recording says"}
    {"op": "speak", "text": "...", "voice": "C:/.../voice.wav", "voice_text": "...",
     "language": "hi", "steps": 32, "out": "C:/.../0001.wav"}
        -> {"ok": true, "audio": 7.9, "work": 2.1}

OmniVoice copies a voice from a recording plus the words spoken in it.
"hear" gets those words with Whisper; the app remembers them, so it happens
once per voice. Only one of the two models is in memory at a time: the other
is let go first, so the memory needed is the larger of the two and not their
sum.

When the app closes, standard input closes with it and this program ends.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import traceback
import wave

ASR_RATE = 16000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="folder with the OmniVoice files")
    ap.add_argument("--whisper", required=True, help="folder with the Whisper files")
    ap.add_argument("--device", choices=("cuda", "cpu"), required=True)
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args()
    cuda = args.device == "cuda"

    # Answers leave on the real standard output. Everything else that prints
    # (libraries, warnings, progress bars) is sent to the log instead.
    answers = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def say(answer: dict) -> None:
        answers.write("@@" + json.dumps(answer) + "\n")
        answers.flush()

    def note(words: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {words}", file=sys.stderr, flush=True)

    try:
        import numpy as np
        import torch
    except Exception as e:  # a broken install: say so instead of dying silently
        traceback.print_exc()
        say({"ready": False, "error": "import", "detail": f"{type(e).__name__}: {e}"[:400]})
        return 1

    gpu = ""
    if cuda:
        if not torch.cuda.is_available():
            say({"ready": False, "error": "no_cuda", "detail": f"PyTorch {torch.__version__}"})
            return 1
        try:
            gpu = torch.cuda.get_device_name(0)
            # A card this PyTorch has no code for is found, and then fails on
            # its first real sum. Do one now rather than in the middle of a clip.
            float((torch.ones(64, device="cuda:0") * 2).sum().item())
        except Exception as e:
            traceback.print_exc()
            say({"ready": False, "error": "cuda_failed", "detail": f"{type(e).__name__}: {e}"[:400]})
            return 1
    if args.threads > 0:
        torch.set_num_threads(args.threads)
    note(f"PyTorch {torch.__version__} on {gpu or 'the processor'}")
    say({"ready": True, "torch": torch.__version__, "device": args.device, "gpu": gpu})

    loaded: dict = {"model": None, "whisper": None}
    prompts: dict = {}  # the voice in use, prepared once

    def let_go(what: str) -> None:
        if loaded[what] is None:
            return
        loaded[what] = None
        if what == "model":
            prompts.clear()
        gc.collect()
        if cuda:
            torch.cuda.empty_cache()

    def model():
        if loaded["model"] is None:
            let_go("whisper")
            from omnivoice import OmniVoice

            t0 = time.time()
            loaded["model"] = OmniVoice.from_pretrained(
                args.model,
                device_map="cuda:0" if cuda else "cpu",
                dtype=torch.float16 if cuda else torch.float32,
            )
            note(f"OmniVoice loaded in {time.time() - t0:.1f} s")
        return loaded["model"]

    def hear(voice: str) -> str:
        let_go("model")
        from omnivoice.utils.audio import load_audio, remove_silence
        from transformers import pipeline

        if loaded["whisper"] is None:
            t0 = time.time()
            loaded["whisper"] = pipeline(
                "automatic-speech-recognition",
                model=args.whisper,
                dtype=torch.float16 if cuda else torch.float32,
                device="cuda:0" if cuda else "cpu",
            )
            note(f"Whisper loaded in {time.time() - t0:.1f} s")
        # The same tidying OmniVoice gives the recording before it uses it.
        sound = load_audio(voice, ASR_RATE)
        level = float(np.sqrt(np.mean(sound**2)))
        if 0 < level < 0.1:
            sound = sound * 0.1 / level
        trimmed = remove_silence(sound, ASR_RATE, mid_sil=200, lead_sil=100, trail_sil=200)
        if trimmed.shape[-1] > ASR_RATE // 2:
            sound = trimmed
        text = loaded["whisper"]({"array": np.squeeze(sound), "sampling_rate": ASR_RATE})["text"].strip()
        note(f"heard: {text!r}")
        let_go("whisper")  # needed once per voice; no reason to keep it in memory
        return text

    def speak(req: dict) -> dict:
        m = model()
        voice = req["voice"]
        key = (voice, os.path.getmtime(voice), req["voice_text"])
        if key not in prompts:
            prompts.clear()
            # The voice is prepared on the processor even when a graphics card
            # does the speaking. On the card this one step took more graphics
            # memory than all the speaking after it (4 GB for a 7 second
            # recording, 6 GB for 14 seconds, against 2 GB to speak), and
            # PyTorch then kept it. On the processor it takes 2 or 3 seconds,
            # once per voice.
            if cuda:
                m.audio_tokenizer.to("cpu")
            try:
                prompts[key] = m.create_voice_clone_prompt(ref_audio=voice, ref_text=req["voice_text"])
            finally:
                if cuda:
                    m.audio_tokenizer.to("cuda:0")
                    torch.cuda.empty_cache()
        t0 = time.time()
        sound = m.generate(
            text=req["text"],
            language=req.get("language") or None,
            voice_clone_prompt=prompts[key],
            num_step=int(req.get("steps") or 32),
        )[0]
        pcm = (np.clip(np.asarray(sound, dtype=np.float32).reshape(-1), -1.0, 1.0) * 32767.0).astype("<i2")
        out = req["out"]
        with wave.open(out + ".part", "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(m.sampling_rate))
            w.writeframes(pcm.tobytes())
        os.replace(out + ".part", out)
        return {"audio": round(len(pcm) / float(m.sampling_rate), 2), "work": round(time.time() - t0, 2)}

    def out_of_memory(e: Exception) -> bool:
        words = str(e).lower()
        return isinstance(e, MemoryError) or "out of memory" in words or "not enough memory" in words or "defaultcpuallocator" in words

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            op = req.get("op")
        except (ValueError, AttributeError):
            say({"ok": False, "error": "bad_request", "detail": "not a JSON object"})
            continue
        if op == "bye":
            break
        try:
            if op == "hear":
                say({"ok": True, "text": hear(req["voice"])})
            elif op == "speak":
                say({"ok": True, **speak(req)})
            else:
                say({"ok": False, "error": "bad_request", "detail": f"unknown op {op!r}"})
        except Exception as e:
            traceback.print_exc()
            full = out_of_memory(e)
            if full:  # give the memory back, so the next try starts clean
                let_go("model")
                let_go("whisper")
            say({"ok": False, "error": "memory" if full else "failed", "detail": f"{type(e).__name__}: {e}"[:400]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
