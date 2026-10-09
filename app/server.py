"""The small web server behind the page. It listens on this PC only.

Two guards, because a page on the internet must not be able to drive an app
on the user's PC:

- Requests are answered only when they are addressed to 127.0.0.1 or
  localhost (this stops another site from reaching the app under a borrowed
  name).
- Every /api call must carry a token that only the app's own page is given.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import brand
import engines
import gemini
import hardware
import jobs
import languages
import paths
import recommend
import speech
import store
import voices
from catalog import MODELS, RUNTIMES, TEST_PC
from jobs import UserError

TOKEN = secrets.token_urlsafe(24)
MAX_JSON = 1024 * 1024
DEFAULTS = {"gemini_key": "", "gemini_model": "", "device": "auto", "language": "hi", "script": "keep"}
_STATIC = {"/app.css", "/app.js", "/favicon.svg", "/sample-voice.wav"}

_hw: dict | None = None
_hw_lock = threading.Lock()


def config() -> dict:
    return {**DEFAULTS, **store.read(paths.CONFIG, {})}


def scan_hardware() -> None:
    global _hw
    found = hardware.detect()
    with _hw_lock:
        _hw = found


def current_plan() -> dict | None:
    with _hw_lock:
        hw = _hw
    return recommend.plan(hw, config()["device"]) if hw else None


def state() -> dict:
    cfg = config()
    with _hw_lock:
        hw = _hw
    plan = recommend.plan(hw, cfg["device"]) if hw else None
    done = engines.installed()
    fits = {m["id"]: m for m in (plan["models"] if plan else [])}
    models = []
    for mid, m in MODELS.items():
        entry = done["models"].get(mid) or {}
        ready = engines.model_ready(mid)
        models.append({
            "id": mid, "name": m["name"], "by": m["by"], "license": m["license"], "home": m["home"],
            "summary": m["summary"], "detail": m["detail"], "size_gb": round(m["size"] / 1024**3, 1),
            "engine_gb": round(engines.engine_bytes(_order(plan, mid)) / 1024**3, 1) if plan and not ready else 0,
            "optional": bool(m.get("optional")), "needs_voice": m["needs_voice"], "installed": ready,
            "runtime": entry.get("runtime") if ready else None,
            "runs_on": RUNTIMES[entry["runtime"]]["on"] if ready else None,
            "device": RUNTIMES[entry["runtime"]]["backend"] if ready else None,
            "per10": entry.get("per10") if ready else None,
            "notes": entry.get("notes", []) if ready else [],
            "problem": entry.get("problem", "") if ready else "",
            "fit": fits.get(mid),
        })  # fmt: skip
    key = cfg["gemini_key"]
    return {
        "app": {"name": brand.NAME, "version": brand.VERSION, "credit": brand.CREDIT, "channel": brand.CHANNEL_NAME,
                "channel_url": brand.CHANNEL_URL, "repo_url": brand.REPO_URL, "test_pc": TEST_PC},
        "hw": hw,
        "plan": plan and {k: plan[k] for k in ("device", "device_label", "why", "headline", "notes", "pick")},
        "models": models,
        # engines kept for the other choice of "Best for this PC / Processor only"
        "spare": {"gb": round(sum(engines.runtime_disk_gb(rt) for rt in engines.spare_runtimes()), 1), "count": len(engines.spare_runtimes())},
        "voices": voices.all_voices(),
        "clips": speech.history()[:200],
        "settings": {"has_key": bool(key), "key_hint": ("…" + key[-4:]) if len(key) >= 8 else "", "gemini_model": cfg["gemini_model"],
                     "device": cfg["device"], "language": cfg["language"], "script": cfg["script"]},
        "jobs": jobs.snapshot(),
        "limits": {"script": speech.MAX_SCRIPT, "voice_min": voices.MIN_SECONDS, "voice_max": voices.MAX_SECONDS},
    }  # fmt: skip


def _order(plan: dict, model_id: str) -> list[str]:
    """The ways of running this model on this PC, best first."""
    return list(plan["torch_runtimes"] if engines.is_omni(model_id) else plan["runtimes"])


def start_install(model_id: str) -> dict:
    if model_id not in MODELS:
        raise UserError("Unknown model.")
    if jobs.busy("install", model=model_id):
        raise UserError("That model is already being installed.")
    plan = current_plan()
    if plan is None:
        raise UserError("Still looking at this PC. Try again in a few seconds.")
    order = _order(plan, model_id)
    job = jobs.submit("install", f"Installing {MODELS[model_id]['name']}", lambda j: engines.install_model(j, model_id, order), {"model": model_id})
    return {"job": job.id}


# ---------------------------------------------------------------- the handler


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HunterTTSLab"

    def log_message(self, fmt, *args):  # quiet: the console is for the banner and real problems
        pass

    # -- plumbing

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value, code: int = 200) -> None:
        self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _fail(self, message: str, code: int = 400) -> None:
        self._json({"error": message}, code)

    def _body(self, limit: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > limit:
            self.close_connection = True  # the body is left unread, so this connection cannot be used again
            raise UserError("That is too large to send.")
        return self.rfile.read(length) if length else b""

    def _file(self, path: Path, ctype: str, download_as: str | None = None) -> None:
        """A file from disk, with range support so the audio player can seek."""
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download_as:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download_as))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left:
                block = f.read(min(256 * 1024, left))
                if not block:
                    break
                try:
                    self.wfile.write(block)
                except (BrokenPipeError, ConnectionError):
                    return
                left -= len(block)

    # -- GET

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"This app only answers on this PC.", "text/plain; charset=utf-8")
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path == "/":
                page = (paths.WEB / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN).replace("{{VERSION}}", brand.VERSION)
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path in _STATIC:
                f = paths.WEB / path[1:]
                if not f.exists():
                    return self._send(404, b"Not found", "text/plain")
                return self._file(f, mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            if path == "/api/ping":
                return self._json({"app": brand.NAME})
            m = re.fullmatch(r"/media/voice/([0-9a-z]+)\.wav", path)
            if m:
                f = voices.path_of(m.group(1))
                return self._file(f, "audio/wav") if f else self._send(404, b"Not found", "text/plain")
            m = re.fullmatch(r"/media/clip/([0-9a-z-]+)\.wav", path)
            if m:
                f = speech.clip_path(m.group(1))
                if not f:
                    return self._send(404, b"Not found", "text/plain")
                name = None
                if "download" in query:
                    clip = next((c for c in speech.history() if c["id"] == m.group(1)), {"id": m.group(1)})
                    name = speech.download_name(clip)
                return self._file(f, "audio/wav", name)
            if path.startswith("/api/"):
                if self.headers.get("X-App-Token") != TOKEN:
                    return self._fail("Open the app from its own window.", 403)
                if path == "/api/state":
                    return self._json(state())
                if path == "/api/jobs":
                    return self._json({"jobs": jobs.snapshot()})
                if path == "/api/languages":
                    return self._json(languages.for_page())
            return self._send(404, b"Not found", "text/plain")
        except (BrokenPipeError, ConnectionError):
            pass

    # -- POST

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-App-Token") != TOKEN:
            self.close_connection = True  # refused before the body was read
        if not self._host_ok():
            return self._send(403, b"This app only answers on this PC.", "text/plain; charset=utf-8")
        if self.headers.get("X-App-Token") != TOKEN:
            return self._fail("Open the app from its own window.", 403)
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path == "/api/voices":  # the body is the WAV itself
                voice = voices.add((query.get("name") or [""])[0], self._body(voices.MAX_BYTES))
                return self._json({"voice": voice})
            raw = self._body(MAX_JSON)
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                return self._fail("That request could not be read.")
            if not isinstance(data, dict):
                return self._fail("That request could not be read.")
            return self._json(self._act(path, data))
        except UserError as e:
            return self._fail(str(e))
        except (BrokenPipeError, ConnectionError):
            pass

    def _act(self, path: str, data: dict) -> dict:
        if path == "/api/models/install":
            return start_install(str(data.get("id")))
        if path == "/api/models/remove":
            mid = str(data.get("id"))
            if mid not in MODELS:
                raise UserError("Unknown model.")
            if jobs.busy():
                raise UserError("Something is still running. Wait for it to finish, or cancel it.")
            engines.remove_model(mid)
            return {"ok": True}
        if path == "/api/runtimes/clean":
            if jobs.busy():
                raise UserError("Something is still running. Wait for it to finish, or cancel it.")
            engines.drop_spare_runtimes()
            return {"ok": True}
        if path == "/api/jobs/cancel":
            return {"ok": jobs.cancel(str(data.get("id")))}
        if path == "/api/hardware/refresh":
            engines.forget_failures()
            scan_hardware()
            return {"ok": True}
        if path == "/api/voices/rename":
            voices.rename(str(data.get("id")), str(data.get("name") or ""))
            return {"ok": True}
        if path == "/api/voices/delete":
            voices.delete(str(data.get("id")))
            return {"ok": True}
        if path == "/api/generate":
            text, model_id = str(data.get("text") or ""), str(data.get("model") or "")
            voice_id, language = str(data.get("voice") or ""), str(data.get("language") or "hi")
            if not text.strip():
                raise UserError("Write something to say first.")
            if model_id not in MODELS or not engines.model_ready(model_id):
                raise UserError("Install a model first, on the Models page.")
            if MODELS[model_id]["needs_voice"] and not voice_id:
                raise UserError(f"{MODELS[model_id]['name']} needs a voice to copy. Pick a voice first.")
            if voice_id and voices.path_of(voice_id) is None:
                raise UserError("That voice was not found. Pick another voice.")
            if not languages.speaks(model_id, language):
                raise UserError(f"{MODELS[model_id]['name']} does not speak {languages.name(language)}. Pick another model, or another language.")
            store.update(paths.CONFIG, {}, lambda c: {**c, "language": language})
            job = jobs.submit("speak", "Making the voice clip", lambda j: speech.generate(j, text, voice_id, model_id, language))
            return {"job": job.id}
        if path == "/api/clips/delete":
            speech.delete_clip(str(data.get("id")))
            return {"ok": True}
        if path == "/api/settings":
            return self._settings(data)
        if path == "/api/gemini/models":
            key = str(data.get("key") or "").strip() or config()["gemini_key"]
            if not key:
                raise UserError("Paste a Gemini API key first.")
            return {"models": gemini.list_models(key)}
        if path == "/api/polish":
            cfg = config()
            if not cfg["gemini_key"]:
                raise UserError("Add a Gemini API key in Settings to polish scripts.")
            if not cfg["gemini_model"]:
                raise UserError("Pick a Gemini model in Settings first.")
            script = data.get("script") if data.get("script") in ("keep", "devanagari", "english") else "keep"
            store.update(paths.CONFIG, {}, lambda c: {**c, "script": script})
            text = str(data.get("text") or "")
            language = str(data.get("language") or "")
            # Hindi and English have their own choices above; any other language is kept as it is written.
            other = languages.name(language) if languages.known(language) and language not in ("hi", "en") else None
            try:
                return {"text": gemini.polish(cfg["gemini_key"], cfg["gemini_model"], text, script, other)}
            except gemini.ModelUnavailable as first:
                # Which models are free, and how much, is Google's to decide and it
                # changes. Rather than send the user to Settings, try the next
                # usually-free ones and remember the one that answered.
                others = [m for m in gemini.list_models(cfg["gemini_key"]) if m["free"] and m["id"] != cfg["gemini_model"]][:3]
                for m in others:
                    try:
                        out = gemini.polish(cfg["gemini_key"], m["id"], text, script, other)
                    except gemini.ModelUnavailable:
                        continue
                    store.update(paths.CONFIG, {}, lambda c, pick=m["id"]: {**c, "gemini_model": pick})
                    return {"text": out, "switched_to": m["name"]}
                raise first
        if path == "/api/open":
            folder = {"outputs": paths.OUTPUTS, "data": paths.DATA}.get(str(data.get("what")))
            if folder is None:
                raise UserError("Unknown folder.")
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))  # noqa: S606 - opens a folder of the app's own, in Explorer
            return {"ok": True}
        raise UserError("Unknown request.")

    def _settings(self, data: dict) -> dict:
        changed_device = False

        def change(cfg: dict) -> dict:
            nonlocal changed_device
            if "gemini_key" in data:
                cfg["gemini_key"] = str(data["gemini_key"] or "").strip()[:200]
                if not cfg["gemini_key"]:
                    cfg["gemini_model"] = ""
            if "gemini_model" in data:
                cfg["gemini_model"] = re.sub(r"[^A-Za-z0-9._-]", "", str(data["gemini_model"] or ""))[:80]
            if data.get("device") in ("auto", "cpu") and data["device"] != cfg.get("device", "auto"):
                cfg["device"] = data["device"]
                changed_device = True
            if languages.known(data.get("language")):
                cfg["language"] = data["language"]
            return cfg

        store.update(paths.CONFIG, {}, change)
        if "gemini_key" in data:
            store.forget_previous(paths.CONFIG)  # a key that was removed or replaced must not stay in the backup copy
        started = []
        if changed_device:
            # Models already installed are set up again for the new choice and tested there.
            for mid in engines.installed()["models"]:
                if mid in MODELS:
                    started.append(start_install(mid)["job"])
        return {"ok": True, "jobs": started}


class _Server(ThreadingHTTPServer):
    # On Windows "address reuse" would let a second copy of the app listen on
    # the same port as the first, and requests would land on either at random.
    allow_reuse_address = False
    daemon_threads = True


def make_server(port: int) -> ThreadingHTTPServer:
    return _Server(("127.0.0.1", port), Handler)
