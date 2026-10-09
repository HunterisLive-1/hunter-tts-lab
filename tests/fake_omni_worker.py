"""A stand-in for app/omni_worker.py that speaks the same lines without PyTorch.

It reads how to behave from mode.txt in the folder named by FAKE_OMNI_DIR, at
start and before every request, and notes every request in ops.txt there.
"""

import json
import os
import sys
import time
import wave
from pathlib import Path

box = Path(os.environ["FAKE_OMNI_DIR"])


def mode() -> str:
    try:
        return (box / "mode.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "ok"


def say(answer: dict) -> None:
    sys.stdout.write("@@" + json.dumps(answer) + "\n")
    sys.stdout.flush()


def noted(op: str) -> None:
    with open(box / "ops.txt", "a", encoding="utf-8") as f:
        f.write(op + "\n")


if mode() == "no_cuda":
    say({"ready": False, "error": "no_cuda", "detail": "PyTorch 0.0"})
    raise SystemExit(1)
if mode() == "dead_on_arrival":
    print("ImportError: DLL load failed while importing _C", file=sys.stderr)
    raise SystemExit(3)

print("a line a library printed, which is not an answer")
say({"ready": True, "torch": "0.0", "device": sys.argv[sys.argv.index("--device") + 1], "gpu": ""})

for line in sys.stdin:
    req = json.loads(line)
    op, how = req.get("op"), mode()
    noted(op)
    if op == "hear":
        say({"ok": True, "text": "" if how == "silent_voice" else "  what the   recording says "})
    elif op == "speak":
        if how == "die":
            print("RuntimeError: something broke inside", file=sys.stderr, flush=True)
            os._exit(7)
        if how == "slow":
            time.sleep(30)
        if how == "memory":
            say({"ok": False, "error": "memory", "detail": "CUDA out of memory"})
            continue
        with wave.open(req["out"], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(bytes(24000 * 2 * 2))  # two seconds
        (box / "last_request.json").write_text(json.dumps(req), encoding="utf-8")
        say({"ok": True, "audio": 2.0, "work": 0.5})
