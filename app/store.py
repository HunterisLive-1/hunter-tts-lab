"""Small JSON files that survive a power cut.

A plain write truncates the file first; if the PC loses power in between, the
file is left empty and the next start would quietly begin from nothing. So
every write goes to a temporary file, is flushed to disk, and only then takes
the place of the real one. The previous copy is kept as .bak, and a file that
cannot be read is set aside as .corrupt instead of being overwritten.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock(path: Path) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(str(path), threading.RLock())


def read(path: Path, default):
    with _lock(path):
        for candidate in (path, path.with_suffix(path.suffix + ".bak")):
            if not candidate.exists():
                continue
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                if candidate == path:
                    try:
                        shutil.copy2(path, path.with_suffix(path.suffix + ".corrupt"))
                    except OSError:
                        pass
        return default


def write(path: Path, value) -> None:
    with _lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            try:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            except OSError:
                pass
        os.replace(tmp, path)


def forget_previous(path: Path) -> None:
    """Make the kept-aside copies match the current file.

    For when something was removed on purpose and must not linger: a deleted
    API key would otherwise still be sitting in the .bak file.
    """
    with _lock(path):
        path.with_suffix(path.suffix + ".corrupt").unlink(missing_ok=True)
        bak = path.with_suffix(path.suffix + ".bak")
        if path.exists():
            shutil.copy2(path, bak)
        else:
            bak.unlink(missing_ok=True)


def update(path: Path, default, change):
    """Read, let `change` modify the value (or return a new one), write, return it."""
    with _lock(path):
        value = read(path, default)
        result = change(value)
        if result is not None:
            value = result
        write(path, value)
        return value
