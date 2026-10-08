"""Installing, testing, running and removing the voice engine and its models.

"Runtime" is the audio.cpp program in one of its builds (NVIDIA, Vulkan, CPU).
"Model" is one voice model file. Installing a model also installs a runtime
that works on this PC: each candidate is tried with a real sentence, and the
first one that speaks is kept. That test is what makes the choice, not a
guess from the name of the graphics card.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import wave
import zipfile
from pathlib import Path

import paths
import store
from catalog import FILES, MODELS, RUNTIMES
from downloads import Cancelled, fetch, fetch_members, fetch_zip_without
from jobs import UserError

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0
SAMPLE_VOICE = paths.WEB / "sample-voice.wav"
# Seconds for 10 seconds of voice above which a graphics card is not really doing the work.
SLOW_ON_A_GRAPHICS_CARD = 25.0
TEST_LINE = ("Hello. This is a test of the voice engine on this computer. "
             "If you can hear this sentence clearly, everything is set up and ready to use.")  # fmt: skip


# ---------------------------------------------------------------- what is installed


def installed() -> dict:
    data = store.read(paths.INSTALLED, {})
    data.setdefault("models", {})
    data.setdefault("tried", {})
    return data


def runtime_dir(rt: str) -> Path:
    return paths.RUNTIMES / rt


def runtime_ready(rt: str) -> bool:
    d = runtime_dir(rt)
    return (d / "audiocpp_cli.exe").exists() and (d / "READY").exists()


def model_file(model_id: str) -> Path:
    m = MODELS[model_id]
    return paths.MODELS / m["folder"] / m["file"]


def model_ready(model_id: str) -> bool:
    entry = installed()["models"].get(model_id)
    f = model_file(model_id)
    return bool(entry) and f.exists() and f.stat().st_size == MODELS[model_id]["size"] and runtime_ready(entry["runtime"])


def threads() -> int:
    """Physical cores, near enough: using every logical thread makes the engine slower, not faster."""
    return max(1, (os.cpu_count() or 2) // 2)


# ---------------------------------------------------------------- runtimes


def _gb(n: float) -> str:
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{n / 1024**2:.0f} MB"


class _Meter:
    """Turns byte counts from the downloader into a progress line with a speed."""

    def __init__(self, job, what: str, start: float, share: float):
        self.job, self.what, self.start, self.share = job, what, start, share
        self.t0, self.b0, self.rate, self.last = time.time(), 0, 0.0, 0.0

    def __call__(self, done: int, total: int) -> None:
        now = time.time()
        if now - self.last < 0.3 and done < total:
            return
        if now - self.t0 >= 1.5:
            self.rate = (done - self.b0) / (now - self.t0)
            self.t0, self.b0 = now, done
        self.last = now
        speed = f", {self.rate / 1024**2:.1f} MB/s" if self.rate else ""
        self.job.report(self.start + self.share * (done / total if total else 1), f"{self.what}: {_gb(done)} of {_gb(total)}{speed}")


def _flatten_program(folder: Path) -> None:
    """Some archives hold the program in a subfolder; bring it to the top."""
    if (folder / "audiocpp_cli.exe").exists():
        return
    hits = sorted(folder.rglob("audiocpp_cli.exe"))
    if not hits:
        raise UserError("The engine download did not contain the program. Try again; if it repeats, the engine's download page may have changed.")
    for item in list(hits[0].parent.iterdir()):
        shutil.move(str(item), str(folder / item.name))


def install_runtime(rt: str, job, start: float, share: float) -> None:
    if runtime_ready(rt):
        return
    spec = RUNTIMES[rt]
    leave_out = tuple(spec.get("leave_out", ()))
    target = runtime_dir(rt)
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(target, ignore_errors=True)
    tmp.mkdir(parents=True)

    def skipped(name: str) -> bool:
        return name.lower().startswith(leave_out) if leave_out else False

    program = FILES[spec["bin"]]
    archive = paths.DOWNLOADS / (rt + "-" + program["url"].rsplit("/", 1)[1])
    half = share * (0.5 if spec["libs"] else 1.0)
    label = f"Getting the engine for {spec['on']}"
    if leave_out:
        fetch_zip_without(program["url"], program["size"], skipped, archive, _Meter(job, label, start, half), job.cancelled)
    else:
        fetch(program["url"], archive, program["size"], program["sha256"], _Meter(job, label, start, half), job.cancelled)
    job.report(detail="Unpacking the engine")
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if job.cancelled():
                    raise Cancelled()
                if not skipped(Path(info.filename).name):
                    z.extract(info, tmp)  # zipfile checks each file against the archive's own checksum
    except zipfile.BadZipFile as e:
        archive.unlink(missing_ok=True)
        raise UserError("The engine download was damaged. Press Install again to fetch it afresh.") from e
    _flatten_program(tmp)

    if spec["libs"]:
        libs = FILES[spec["libs"]]
        label = "Getting the libraries the engine needs"
        if spec.get("only_libs"):
            fetch_members(libs["url"], libs["size"], tuple(spec["only_libs"]), tmp, _Meter(job, label, start + half, share - half), job.cancelled)
        else:
            lib_archive = paths.DOWNLOADS / libs["url"].rsplit("/", 1)[1]
            fetch(libs["url"], lib_archive, libs["size"], libs["sha256"], _Meter(job, label, start + half, share - half), job.cancelled)
            job.report(detail="Unpacking the libraries")
            with zipfile.ZipFile(lib_archive) as z:
                for info in z.infolist():
                    name = Path(info.filename).name
                    if name.lower().endswith(".dll"):  # placed by name: the archive's own folders do not matter
                        with z.open(info) as src, open(tmp / name, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
            lib_archive.unlink(missing_ok=True)
    archive.unlink(missing_ok=True)
    (tmp / "READY").write_text("ok\n", encoding="utf-8")
    os.replace(tmp, target)


# ---------------------------------------------------------------- running the engine

_FAILURES = (
    (r"out of memory|failed to allocate|alloc.*fail|CUDA_ERROR_OUT_OF_MEMORY|ErrorOutOfDeviceMemory", "The graphics card ran out of memory. Close other heavy apps (games, video editors, other AI tools) and try again."),
    (r"no CUDA|CUDA.*not (found|available)|cuda.*init|nvcuda|unsupported.*gpu|no kernel image", "The NVIDIA part of the engine could not start on this card or driver."),
    (r"vulkan.*(fail|not|error)|no.*vulkan", "Vulkan could not start on this graphics card."),
    (r"requires speaker reference", "This model needs a voice to copy. Pick a voice first."),
)


def _explain(code: int, stderr: str) -> str:
    if code == 0xC000001D:
        return "This processor is missing instructions the engine needs."
    if code == 0xC0000135:
        return "A library the engine needs is missing. Remove the model and install it again."
    for pattern, message in _FAILURES:
        if re.search(pattern, stderr, flags=re.IGNORECASE):
            return message
    said = [ln.strip() for ln in stderr.splitlines() if "fail" in ln.lower() or "error" in ln.lower()]
    return (said[-1][:200] if said else f"The engine stopped with code {code}.").replace("audiocpp_cli failed: ", "")


def wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, OSError, EOFError):
        return 0.0


def speak(rt: str, model_id: str, text: str, out_wav: Path, voice: Path | None, language: str, cancelled=None, limit: float = 1800) -> dict:
    """Make one clip. Returns {"seconds": wall time, "audio": length of the clip}."""
    m, spec = MODELS[model_id], RUNTIMES[rt]
    if m["needs_voice"] and voice is None:
        raise UserError(f"{m['name']} needs a voice to copy. Pick a voice first.")
    # A piece that began with a dash would be read by the engine as one of its own options.
    text = text.lstrip("-" + chr(0x2013) + chr(0x2014) + " ")
    cmd = [
        str(runtime_dir(rt) / "audiocpp_cli.exe"), "--task", m["task"], "--family", m["family"],
        "--model", str(model_file(model_id).parent), "--backend", spec["backend"], "--threads", str(threads()),
        "--text", text, "--out", str(out_wav), "--language", language,
    ]  # fmt: skip
    if voice is not None:
        cmd += ["--voice-ref", str(voice)]
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    out_wav.unlink(missing_ok=True)
    log = paths.LOGS / "engine-last.txt"
    t0 = time.time()
    with open(log, "w", encoding="utf-8", errors="replace") as logf:
        # Below normal priority on the processor: it takes every core, and the PC has to stay usable.
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=str(runtime_dir(rt)),
                                creationflags=NO_WINDOW | (BELOW_NORMAL if spec["backend"] == "cpu" else 0))  # fmt: skip
        while proc.poll() is None:
            if cancelled and cancelled():
                proc.kill()
                proc.wait(timeout=10)
                raise Cancelled()
            if time.time() - t0 > limit:
                proc.kill()
                raise UserError("The engine took more than 30 minutes for one piece of text and was stopped.")
            time.sleep(0.15)
    took = time.time() - t0
    audio = wav_seconds(out_wav) if out_wav.exists() else 0.0
    if proc.returncode != 0 or audio < 0.2:
        try:
            said = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            said = ""
        raise UserError(_explain(proc.returncode & 0xFFFFFFFF, said))
    return {"seconds": round(took, 2), "audio": round(audio, 2)}


def self_test(rt: str, model_id: str, cancelled=None) -> dict:
    """One real sentence. {"ok": True, "per10": seconds per 10 s of voice} or {"ok": False, "error": why}."""
    out = paths.DOWNLOADS / f"selftest-{rt}-{model_id}.wav"
    try:
        r = speak(rt, model_id, TEST_LINE, out, SAMPLE_VOICE, "en", cancelled, limit=900)
        if r["seconds"] < 25:
            # The first run after a download also pays for reading the model
            # from disk for the first time. On a quick PC a second run costs a
            # few seconds and gives the number the user will really see.
            again = speak(rt, model_id, TEST_LINE, out, SAMPLE_VOICE, "en", cancelled, limit=900)
            if again["seconds"] / again["audio"] < r["seconds"] / r["audio"]:
                r = again
        return {"ok": True, "per10": round(r["seconds"] / r["audio"] * 10, 1)}
    except UserError as e:
        return {"ok": False, "error": str(e)}
    finally:
        out.unlink(missing_ok=True)


# ---------------------------------------------------------------- install and remove


def _runtime_bytes(rt: str) -> int:
    spec = RUNTIMES[rt]
    if rt == "cpu":
        return 215 * 1024**2  # only the needed parts of the two archives are fetched
    return FILES[spec["bin"]]["size"] + (FILES[spec["libs"]]["size"] if spec["libs"] else 0)


def install_model(job, model_id: str, order: list[str]) -> dict:
    """Download the model, then find a runtime from `order` that really works here."""
    m = MODELS[model_id]
    data = installed()
    # The order is the plan's: best way of running first. One that already
    # failed its test on this PC is not downloaded and tried again (pressing
    # "Check this PC again" forgets those failures, for after a driver update).
    order = [rt for rt in order if data["tried"].get(rt, {}).get("ok") is not False] or list(order)
    first = order[0]
    need = (0 if model_file(model_id).exists() else m["size"]) + (0 if runtime_ready(first) else int(_runtime_bytes(first) * 2.2))
    free = shutil.disk_usage(paths.DATA).free
    if free < need + 1024**3:
        raise UserError(f"Not enough free disk space: this needs about {_gb(need + 1024**3)} and {_gb(free)} is free.")

    weight = m["size"] / (m["size"] + (0 if runtime_ready(first) else _runtime_bytes(first)))
    fetch(m["url"], model_file(model_id), m["size"], m["sha256"], _Meter(job, f"Downloading {m['name']}", 0.0, weight * 0.96), job.cancelled)

    # Every way that speaks is timed, and the fastest one is kept. A graphics
    # runtime can pass the test and still be no faster than a processor: the
    # older NVIDIA build did exactly that on a 50-series card (66 s for 10 s
    # of voice, where the right build takes 7). That silent fallback is the
    # usual reason people say an AI tool "does not use my graphics card", so
    # a slow result is not accepted until the other ways have had their turn.
    notes: list[str] = []
    spoke: list[tuple[float, str]] = []
    for rt in order:
        install_runtime(rt, job, weight * 0.96, (1 - weight) * 0.96)
        job.report(0.97, f"Testing {m['name']} on {RUNTIMES[rt]['on']}")
        test = self_test(rt, model_id, job.cancelled)
        data = installed()
        data["tried"][rt] = {"ok": test["ok"], "error": test.get("error"), "per10": test.get("per10"), "when": time.strftime("%Y-%m-%d %H:%M")}
        store.write(paths.INSTALLED, data)
        if not test["ok"]:
            notes.append(f"{RUNTIMES[rt]['label']} was tried and did not work here: {test['error']}")
            continue
        spoke.append((test["per10"], rt))
        if RUNTIMES[rt]["backend"] == "cpu" or test["per10"] <= SLOW_ON_A_GRAPHICS_CARD:
            break
        notes.append(f"{RUNTIMES[rt]['label']} works here but slowly ({test['per10']:.0f} seconds for 10 seconds of voice), so the other ways were tried too.")
    if not spoke:
        raise UserError(f"{m['name']} was downloaded, but the engine could not make a test clip on this PC. " + " ".join(notes))
    per10, rt = min(spoke)
    data = installed()
    data["models"][model_id] = {"runtime": rt, "per10": per10, "tested": time.strftime("%Y-%m-%d %H:%M"), "notes": notes}
    store.write(paths.INSTALLED, data)
    _drop_unused_runtimes()
    return {"model": model_id, "runtime": rt, "per10": per10, "notes": notes}


def _drop_unused_runtimes() -> None:
    used = {e["runtime"] for e in installed()["models"].values()}
    if not paths.RUNTIMES.exists():
        return
    for d in paths.RUNTIMES.iterdir():
        if d.is_dir() and d.name.removesuffix(".tmp") not in used:
            shutil.rmtree(d, ignore_errors=True)


def forget_failures() -> None:
    """Let every way of running be tried again, for instance after a driver update."""
    data = installed()
    data["tried"] = {rt: t for rt, t in data["tried"].items() if t.get("ok")}
    store.write(paths.INSTALLED, data)


def remove_model(model_id: str) -> None:
    data = installed()
    data["models"].pop(model_id, None)
    store.write(paths.INSTALLED, data)
    shutil.rmtree(model_file(model_id).parent, ignore_errors=True)
    _drop_unused_runtimes()
    for stray in paths.DOWNLOADS.glob("*"):
        if stray.is_file():
            stray.unlink(missing_ok=True)


def disk_use() -> dict:
    def size(folder: Path) -> int:
        return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.exists() else 0

    return {"models": size(paths.MODELS), "runtimes": size(paths.RUNTIMES), "outputs": size(paths.OUTPUTS)}
