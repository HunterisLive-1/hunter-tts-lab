"""Long work (installing a model, making a voice clip) runs here, one job at
a time, so two models are never in memory together and the page stays
responsive. The page asks for the list of jobs a few times a second and draws
progress from it.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid

import paths
from downloads import Cancelled, DownloadError


class UserError(Exception):
    """A failure with a message written for the person using the app."""


class Job:
    def __init__(self, kind: str, title: str, about: dict | None = None):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title, self.about = kind, title, about or {}
        self.status = "waiting"  # waiting, running, done, failed, cancelled
        self.progress: float | None = None
        self.detail = ""
        self.result: dict | None = None
        self.error: str | None = None
        self.created = time.time()
        self.finished: float | None = None
        self._cancel = threading.Event()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def report(self, progress: float | None = None, detail: str | None = None) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if detail is not None:
            self.detail = detail

    def public(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "about": self.about, "status": self.status,
            "progress": self.progress, "detail": self.detail, "result": self.result, "error": self.error,
        }  # fmt: skip


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_queue: "queue.Queue[tuple[Job, object]]" = queue.Queue()
_worker: threading.Thread | None = None


def _run() -> None:
    while True:
        job, work = _queue.get()
        if job.cancelled():
            job.status, job.finished = "cancelled", time.time()
            continue
        job.status = "running"
        try:
            job.result = work(job) or {}
            job.status = "done"
            job.progress = 1.0
        except Cancelled:
            job.status = "cancelled"
        except (UserError, DownloadError) as e:
            job.status, job.error = "failed", str(e)
        except Exception as e:  # a bug: say so plainly and keep the details for a report
            job.status, job.error = "failed", f"Something unexpected went wrong ({type(e).__name__}: {e}). The details are in data\\logs\\app.log."
            try:
                paths.LOGS.mkdir(parents=True, exist_ok=True)
                with open(paths.LOGS / "app.log", "a", encoding="utf-8") as f:
                    f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {job.kind}: {job.title}\n{traceback.format_exc()}")
            except OSError:
                pass
        job.finished = time.time()


def submit(kind: str, title: str, work, about: dict | None = None) -> Job:
    """Queue `work(job)`. It may call job.report() and should check job.cancelled()."""
    global _worker
    job = Job(kind, title, about)
    with _lock:
        _jobs[job.id] = job
        if _worker is None:
            _worker = threading.Thread(target=_run, daemon=True, name="jobs")
            _worker.start()
    _queue.put((job, work))
    return job


def cancel(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if job is None or job.status not in ("waiting", "running"):
        return False
    job._cancel.set()
    return True


def busy(kind: str | None = None, **about) -> bool:
    """Is a job of this kind (and about this thing) waiting or running?"""
    with _lock:
        return any(
            j.status in ("waiting", "running") and (kind is None or j.kind == kind) and all(j.about.get(k) == v for k, v in about.items())
            for j in _jobs.values()
        )


def snapshot() -> list[dict]:
    """Jobs still going, plus the ones that ended in the last ten minutes."""
    now = time.time()
    with _lock:
        for jid in [j.id for j in _jobs.values() if j.finished and now - j.finished > 600]:
            del _jobs[jid]
        return [j.public() for j in _jobs.values()]
