"""OmniVoice, the optional model that runs in Python.

Chatterbox and VoxCPM2 run through audio.cpp, a plain program. OmniVoice has
no such build that reads Hindi typed in English letters properly, so it runs
the way its authors ship it: on PyTorch. This file gives it a Python of its
own inside the app's data folder:

    data/runtimes/torch-cu128/python/python.exe     a standalone Python 3.11
    data/runtimes/torch-cu128/python/Lib/...        PyTorch, OmniVoice and what they need

Nothing is installed into Windows, no PATH is changed, and a Python the user
already has is neither used nor touched. There is no virtual environment with
a fixed path inside, so the folder still works after the app is moved.

Every file is pinned: Python and PyTorch by the checksums in catalog.py, the
other packages by the checksums in omni-requirements.txt.

The model takes ten seconds or more to load, so it is not started once per
piece of text the way audio.cpp is. One helper process (omni_worker.py) is
started, kept while clips are being made, and closed after a few idle
minutes so that it does not sit on the graphics memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.parse
from pathlib import Path

import engines
import paths
import store
from catalog import FILES, MODELS, OMNI_STEPS, RUNTIMES, TORCH_PACKAGES_BYTES
from downloads import Cancelled, fetch
from jobs import UserError

MODEL_ID = "omnivoice"
REQUIREMENTS = Path(__file__).with_name("omni-requirements.txt")
WORKER = Path(__file__).with_name("omni_worker.py")
IDLE_SECONDS = 300  # the helper is closed after this long without a clip
HEARD_KEEP = 200

_NAME = MODELS[MODEL_ID]["name"]


# ---------------------------------------------------------------- where things are


def runtime_dir(rt: str) -> Path:
    return paths.RUNTIMES / rt


def python_exe(rt: str) -> Path:
    return runtime_dir(rt) / "python" / "python.exe"


def runtime_ready(rt: str) -> bool:
    return python_exe(rt).exists() and (runtime_dir(rt) / "READY").exists()


def runtime_bytes(rt: str) -> int:
    spec = RUNTIMES[rt]
    return FILES["python311"]["size"] + FILES[spec["torch"]]["size"] + FILES[spec["torchaudio"]]["size"] + TORCH_PACKAGES_BYTES


def model_dir() -> Path:
    return paths.MODELS / MODELS[MODEL_ID]["folder"]


# ---------------------------------------------------------------- setting up Python


def _clean_env() -> dict:
    """The environment for OmniVoice's Python: nothing of another Python's leaks in."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "PIP_", "VIRTUAL_ENV", "CONDA"))}
    env.update(
        HF_HUB_OFFLINE="1",  # every file is already on disk; never go looking online
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HOME=str(model_dir() / ".cache"),
        TOKENIZERS_PARALLELISM="false",
    )
    return env


TOO_DEEP = ("The app's folder has a long path, and Windows cannot unpack PyTorch that deep inside it. "
            "Move the Hunter TTS Lab folder somewhere shorter, for example C:\\HunterTTSLab, start it again and press Install.")  # fmt: skip

_PIP_FAILURES = (
    (r"Long Path support|path too long|File name too long", TOO_DEEP),
    (r"No space left|Errno 28|not enough space|There is not enough space", "The disk filled up while setting up Python. Free some space and press Install again."),
    (r"THESE PACKAGES DO NOT MATCH THE HASHES|hash.*mismatch", "A downloaded Python package did not match its checksum and was refused. Press Install again."),
    (r"ConnectionError|ReadTimeout|Temporary failure|getaddrinfo|Could not fetch|Max retries|ProxyError|SSLError|Connection (aborted|reset|refused)|No matching distribution",
     "The Python packages could not be downloaded. Check the internet connection and press Install again; what is already here is kept."),
    (r"Access is denied|PermissionError|WinError 5\b|WinError 32\b", "Windows would not let the app write its own files. An antivirus may be holding them; wait a minute and press Install again."),
)  # fmt: skip


def _run(cmd: list, job, log: Path, on_line=None, failed: str = "Setting up Python did not work.") -> None:
    """Run a setup command to its end, with its output kept in a log and Cancel obeyed."""
    lines: "queue.Queue[str | None]" = queue.Queue()
    proc = subprocess.Popen(
        [str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=_clean_env(),
        cwd=str(paths.DATA), creationflags=engines.NO_WINDOW | engines.BELOW_NORMAL, text=True, encoding="utf-8", errors="replace",
    )  # fmt: skip

    def pump() -> None:
        for line in proc.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    threading.Thread(target=pump, daemon=True, name="setup-output").start()
    tail: list[str] = []
    with open(log, "a", encoding="utf-8", errors="replace") as logf:
        logf.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(str(c) for c in cmd[:8])} ...\n")
        while True:
            if job.cancelled():
                proc.kill()
                proc.wait(timeout=15)
                raise Cancelled()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            logf.write(line + "\n")
            tail = (tail + [line])[-60:]
            if on_line:
                on_line(line)
    if proc.wait() != 0:
        said = "\n".join(tail)
        for pattern, message in _PIP_FAILURES:
            if re.search(pattern, said, flags=re.IGNORECASE):
                raise UserError(message)
        last = next((ln.strip() for ln in reversed(tail) if "error" in ln.lower()), "")
        raise UserError(f"{failed} {last[:200]} The details are in data\\logs\\{log.name}.".replace("  ", " "))


def _pip(rt: str, args: list, job, log: Path, on_line=None) -> None:
    # -I and --isolated: no environment variable, user folder or pip setting of
    # another Python on this PC can change what gets installed here.
    # --no-compile: Python makes its compiled copies by itself the first time a
    # file is used. Making all 15,000 now would take a minute, 300 MB, and
    # the longest file path of the whole setup.
    cmd = [python_exe(rt), "-I", "-u", "-m", "pip", "install", "--isolated", "--no-input", "--no-cache-dir", "--no-compile",
           "--disable-pip-version-check", "--no-warn-script-location", "--no-deps", *args]  # fmt: skip
    _run(cmd, job, log, on_line)


# The longest file path PyTorch unpacks to, counted from its folder. Windows
# stops at 260 characters for a whole path unless long paths were switched on.
LONGEST_PATH_INSIDE = 146


def _long_paths_on() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (ImportError, OSError):
        return False


def path_too_deep(rt: str) -> bool:
    return len(str(runtime_dir(rt))) + 1 + LONGEST_PATH_INSIDE > 259 and not _long_paths_on()


def _done(rt: str, step: str) -> bool:
    return (runtime_dir(rt) / f"{step}_OK").exists()


def _mark(rt: str, step: str) -> None:
    (runtime_dir(rt) / f"{step}_OK").write_text("ok", encoding="utf-8")


def disk_needed(rt: str) -> int:
    """Free space the setup needs at its fullest moment: the PyTorch download and its unpacked copy, side by side."""
    if runtime_ready(rt):
        return 0
    torch = FILES[RUNTIMES[rt]["torch"]]
    return torch["size"] + torch["unpacked"] + 1024**3  # and about 1 GB for Python and the other packages


def install_runtime(rt: str, job, start: float, share: float) -> None:
    """Python, PyTorch and OmniVoice's packages into data/runtimes/<rt>. Progress runs from `start` over `share`.

    Three steps, each marked when it is finished. An install that was
    cancelled, or lost its connection, goes on from the step it was in the
    next time, instead of fetching 3 GB of PyTorch again.
    """
    if runtime_ready(rt):
        return
    if path_too_deep(rt):
        raise UserError(TOO_DEEP)  # said now, not after 3 GB of download
    stop()
    spec, target = RUNTIMES[rt], runtime_dir(rt)
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    log = paths.LOGS / "omnivoice-setup.txt"
    total, done = runtime_bytes(rt), 0

    def span(size: int) -> tuple[float, float]:
        return start + share * done / total, share * size / total

    # 1. Python itself
    py = FILES["python311"]
    if not (_done(rt, "PYTHON") and python_exe(rt).exists()):
        shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise UserError(f"An older copy of {_NAME}'s Python is still in use and could not be replaced. Close the app, start it again and press Install.")
        target.mkdir(parents=True)
        log.unlink(missing_ok=True)
        archive = paths.DOWNLOADS / "python-3.11.15-windows.tar.gz"
        fetch(py["url"], archive, py["size"], py["sha256"], engines._Meter(job, f"Getting Python for {_NAME}", *span(py["size"])), job.cancelled)
        job.report(detail="Unpacking Python")
        try:
            with tarfile.open(archive, "r:gz") as tar:
                try:
                    tar.extractall(target, filter="data")
                except TypeError:  # a Python from before extraction filters
                    tar.extractall(target)  # noqa: S202 - the archive was just checked against its pinned checksum
        except (tarfile.TarError, OSError) as e:
            archive.unlink(missing_ok=True)
            raise UserError("The Python download could not be unpacked. Press Install again to fetch it afresh.") from e
        if not python_exe(rt).exists():
            raise UserError("The Python download did not contain the program. Try again; if it repeats, its download page may have changed.")
        archive.unlink(missing_ok=True)
        _mark(rt, "PYTHON")
    done += py["size"]

    # 2. PyTorch, the build for this PC
    parts = [(FILES[spec["torch"]], f"Getting PyTorch for {spec['on']}"), (FILES[spec["torchaudio"]], "Getting PyTorch's audio part")]
    wheels = [paths.DOWNLOADS / urllib.parse.unquote(f["url"].rsplit("/", 1)[1]) for f, _ in parts]
    if not _done(rt, "TORCH"):
        for (f, words), wheel in zip(parts, wheels):
            fetch(f["url"], wheel, f["size"], f["sha256"], engines._Meter(job, words, *span(f["size"])), job.cancelled)
            done += f["size"]
        job.report(start + share * done / total, "Unpacking PyTorch. This takes a few minutes.")
        _pip(rt, wheels, job, log)
        # PyTorch for Windows carries the files a C++ programmer links against,
        # 2.6 GB of them. Nothing here ever loads them.
        for lib in (target / "python" / "Lib" / "site-packages" / "torch" / "lib").glob("*.lib"):
            lib.unlink(missing_ok=True)
        _mark(rt, "TORCH")
    else:
        done += sum(f["size"] for f, _ in parts)
    for wheel in wheels:
        wheel.unlink(missing_ok=True)

    # 3. Everything else OmniVoice needs, each file checked against the list
    wanted = max(1, sum(1 for ln in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if ln[:1].isalnum()))
    seen = 0

    def on_line(line: str) -> None:
        nonlocal seen
        if line.startswith("Collecting "):
            seen += 1
            job.report(start + share * (done + TORCH_PACKAGES_BYTES * min(1.0, seen / wanted) * 0.9) / total,
                       f"Getting the Python packages {_NAME} needs: {seen} of {wanted}")  # fmt: skip
        elif line.startswith("Installing collected packages"):
            job.report(detail="Unpacking the Python packages")

    job.report(start + share * done / total, f"Getting the Python packages {_NAME} needs")
    _pip(rt, ["--require-hashes", "--only-binary", ":all:", "-r", REQUIREMENTS], job, log, on_line)
    (target / "READY").write_text("ok", encoding="utf-8")


# ---------------------------------------------------------------- the helper process

_WORDS = {
    "no_cuda": "PyTorch could not find the NVIDIA card. Its driver may be too old; updating the NVIDIA driver usually fixes this.",
    "cuda_failed": "PyTorch could not use this NVIDIA card.",
    "import": f"{_NAME}'s Python did not start properly. Remove {_NAME} and install it again.",
}


def _explain(answer: dict, on_gpu: bool) -> str:
    code, detail = answer.get("error", ""), str(answer.get("detail", ""))
    if code == "memory":
        return engines.OUT_OF_VRAM if on_gpu else engines.OUT_OF_RAM
    if code in _WORDS:
        return _WORDS[code]
    if re.search(r"no kernel image|not compatible with the current PyTorch", detail, flags=re.IGNORECASE):
        return "This build of PyTorch does not support this NVIDIA card."
    if re.search(r"CUDA error|cudnn|CUBLAS", detail, flags=re.IGNORECASE):
        return "PyTorch hit an error on the NVIDIA card: " + detail[:160]
    return f"{_NAME} stopped: {detail[:200] or 'no reason given'}"


class _Worker:
    def __init__(self, rt: str, cancelled=None):
        self.rt, self.on_gpu = rt, RUNTIMES[rt]["backend"] == "cuda"
        self.answers: "queue.Queue[dict | None]" = queue.Queue()
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        self.log_path = paths.LOGS / "omnivoice-last.txt"
        self.log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        cmd = [str(python_exe(rt)), "-I", "-X", "utf8", "-u", str(WORKER), "--model", str(model_dir()), "--whisper", str(model_dir() / "whisper"),
               "--device", RUNTIMES[rt]["backend"], "--threads", str(engines.threads())]  # fmt: skip
        # Below normal priority on the processor: it takes every core, and the PC has to stay usable.
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, cwd=str(paths.DATA), env=_clean_env(),
                creationflags=engines.NO_WINDOW | (0 if self.on_gpu else engines.BELOW_NORMAL), text=True, encoding="utf-8", errors="replace",
            )  # fmt: skip
        except OSError as e:
            self.log.close()
            raise UserError(f"{_NAME}'s Python could not be started ({e}). Remove {_NAME} and install it again.") from e
        threading.Thread(target=self._pump, daemon=True, name="omnivoice-answers").start()
        try:
            hello = self._wait(cancelled, 900)
        except BaseException:
            self.stop()
            raise
        if not hello.get("ready"):
            self.stop()
            raise UserError(_explain(hello, self.on_gpu))

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:
                if line.startswith("@@"):
                    try:
                        self.answers.put(json.loads(line[2:]))
                    except ValueError:
                        pass
        except (OSError, ValueError):
            pass
        self.answers.put(None)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _died(self) -> UserError:
        code = (self.proc.poll() or 0) & 0xFFFFFFFF
        try:
            self.log.flush()
            said = self.log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        except (OSError, ValueError):
            said = ""
        if code == 0xC0000135:
            return UserError(f"A library {_NAME}'s Python needs is missing. Remove {_NAME} and install it again.")
        if code == 0xC000001D:
            return UserError("This processor is missing instructions PyTorch needs.")
        if re.search(r"out of memory|not enough memory|MemoryError|bad_alloc", said, flags=re.IGNORECASE) or code in (0xC0000017, 0xC000012D):
            return UserError(_explain({"error": "memory"}, self.on_gpu))
        last = next((ln.strip() for ln in reversed(said.splitlines()) if ln.strip()), "")
        return UserError(f"{_NAME} stopped unexpectedly. {last[:200]} The details are in data\\logs\\{self.log_path.name}.".replace("  ", " "))

    def _wait(self, cancelled, limit: float) -> dict:
        t0 = time.time()
        while True:
            if cancelled and cancelled():
                self.stop()
                raise Cancelled()
            if time.time() - t0 > limit:
                self.stop()
                raise UserError(f"{_NAME} took more than {limit / 60:.0f} minutes for one step and was stopped.")
            try:
                answer = self.answers.get(timeout=0.15)
            except queue.Empty:
                continue
            if answer is None:
                raise self._died()
            return answer

    def ask(self, request: dict, cancelled=None, limit: float = 1800) -> dict:
        try:
            self.proc.stdin.write(json.dumps(request) + "\n")  # plain ASCII: json escapes everything else
            self.proc.stdin.flush()
        except (OSError, ValueError):
            if self.alive():
                self.stop()
            raise self._died() from None
        return self._wait(cancelled, limit)

    def stop(self) -> None:
        if self.alive():
            try:
                self.proc.stdin.close()  # it ends by itself when its input closes
                self.proc.wait(timeout=3)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                self.proc.kill()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        for pipe in (self.proc.stdin, self.proc.stdout, self.log):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


_lock = threading.RLock()
_worker: _Worker | None = None
_last_used = 0.0
_reaper: threading.Thread | None = None


def _reap() -> None:
    while True:
        time.sleep(20)
        if _lock.acquire(blocking=False):  # never while a clip is being made
            try:
                if _worker is not None and time.time() - _last_used > IDLE_SECONDS:
                    stop()
            finally:
                _lock.release()


def _get(rt: str, cancelled=None, status=None) -> _Worker:
    global _worker, _reaper, _last_used
    if _worker is not None and (_worker.rt != rt or not _worker.alive()):
        stop()
    if _worker is None:
        engines.check_memory(MODEL_ID, RUNTIMES[rt]["backend"])
        if status:
            status(f"Starting {_NAME}. The first clip takes a little longer.")
        _last_used = time.time()
        _worker = _Worker(rt, cancelled)
        if _reaper is None:
            _reaper = threading.Thread(target=_reap, daemon=True, name="omnivoice-idle")
            _reaper.start()
    return _worker


def stop() -> None:
    """Close the helper and give its memory back. Safe to call when it is not running."""
    global _worker
    with _lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def running() -> bool:
    return _worker is not None and _worker.alive()


def current() -> str | None:
    """The runtime the helper is running from, or None."""
    worker = _worker
    return worker.rt if worker is not None and worker.alive() else None


# ---------------------------------------------------------------- making a clip


def _voice_key(voice: Path) -> str:
    return hashlib.sha256(voice.read_bytes()).hexdigest()[:32]


def _heard(rt: str, voice: Path, cancelled=None, status=None, again: bool = False) -> str:
    """The words spoken in a voice recording. Whisper is asked once per recording; the answer is kept."""
    key = _voice_key(voice)
    known = store.read(paths.HEARD, {})
    if not again and known.get(key):
        return known[key]
    if status:
        status("Listening to the voice recording (once per voice)")
    worker = _get(rt, cancelled, None)
    answer = worker.ask({"op": "hear", "voice": str(voice)}, cancelled, 900)
    if not answer.get("ok"):
        raise UserError(_explain(answer, worker.on_gpu))
    text = " ".join(str(answer.get("text", "")).split())
    if not text:
        raise UserError(f"{_NAME} could not make out any words in this voice recording. Use a recording of clear speech.")

    def keep(items: dict) -> dict:
        items.pop(key, None)
        items[key] = text
        return dict(list(items.items())[-HEARD_KEEP:])

    store.update(paths.HEARD, {}, keep)
    return text


def speak(rt: str, text: str, out_wav: Path, voice: Path | None, language: str, cancelled=None, limit: float = 1800, status=None, again: bool = False) -> dict:
    """Make one clip. Returns {"seconds": wall time, "audio": length of the clip, "work": time spent speaking}."""
    global _last_used, _worker
    if voice is None:
        raise UserError(f"{_NAME} needs a voice to copy. Pick a voice first.")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    out_wav.unlink(missing_ok=True)
    t0 = time.time()
    with _lock:
        try:
            said = _heard(rt, voice, cancelled, status, again)
            worker = _get(rt, cancelled, status)
            if status:
                status("")
            request = {"op": "speak", "text": text, "voice": str(voice), "voice_text": said, "language": language,
                       "steps": OMNI_STEPS[RUNTIMES[rt]["backend"]], "out": str(out_wav)}  # fmt: skip
            answer = worker.ask(request, cancelled, limit)
        except Cancelled:
            _worker = None  # it was stopped in the middle of its work
            raise
        finally:
            _last_used = time.time()
        if not answer.get("ok"):
            raise UserError(_explain(answer, worker.on_gpu))
    audio = engines.wav_seconds(out_wav) if out_wav.exists() else 0.0
    if audio < 0.2:
        raise UserError(f"{_NAME} made an empty clip. Try again.")
    return {"seconds": round(time.time() - t0, 2), "audio": round(audio, 2), "work": float(answer.get("work") or 0.0)}


def self_test(rt: str, cancelled=None) -> dict:
    """One real sentence, Whisper included. {"ok": True, "per10": ...} or {"ok": False, "error": why}."""
    out = paths.DOWNLOADS / f"selftest-{rt}-{MODEL_ID}.wav"
    try:
        stop()  # a fresh start: this tests what is on disk now
        r = speak(rt, engines.TEST_LINE, out, engines.SAMPLE_VOICE, "en", cancelled, limit=900, again=True)
        work = r["work"] or r["seconds"]
        if work < 25:
            # The first clip also pays for warming up the graphics card. On a
            # quick PC a second one costs a moment and gives the real number.
            again = speak(rt, engines.TEST_LINE, out, engines.SAMPLE_VOICE, "en", cancelled, limit=900)
            if again["work"] and again["work"] / again["audio"] < work / r["audio"]:
                r, work = again, again["work"]
        return {"ok": True, "per10": round(work / r["audio"] * 10, 1)}
    except UserError as e:
        stop()
        return {"ok": False, "error": str(e)}
    finally:
        out.unlink(missing_ok=True)
