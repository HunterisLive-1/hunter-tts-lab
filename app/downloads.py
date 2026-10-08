"""Downloads that can be resumed, and are checked before they are used.

Two things this file is careful about:

- A download that stops halfway (closed lid, lost Wi-Fi, a power cut) is
  picked up where it stopped the next time, not started again from zero.
- Nothing is trusted because it has the right size. A power cut can leave a
  file with its full length and zeros inside, and a resumed download would
  build on top of that. Every file is compared with its published SHA-256
  before it is used, and one that does not match is deleted and fetched again.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import os
import struct
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

AGENT = "HunterTTSLab/1.0 (+https://github.com/HunterisLive-1/hunter-tts-lab)"
BLOCK = 1 << 20
_NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError)


class Cancelled(Exception):
    """The user pressed Cancel."""


class DownloadError(Exception):
    """Something the user should be told about, in plain words."""


def _open(url: str, start: int = 0, end: int | None = None, timeout: float = 60):
    headers = {"User-Agent": AGENT}
    if start or end is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def sha256_of(path: Path, cancelled=None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancelled and cancelled():
                raise Cancelled()
            block = f.read(BLOCK * 4)
            if not block:
                return h.hexdigest()
            h.update(block)


def fetch(url: str, dest: Path, size: int, sha256: str, progress=None, cancelled=None) -> None:
    """Download `url` to `dest`. `progress(done_bytes, total_bytes)` is called as it goes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == size and sha256_of(dest, cancelled) == sha256:
        if progress:
            progress(size, size)
        return
    part = dest.with_name(dest.name + ".part")
    failures, started_over = 0, False
    while True:
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have < size:
            try:
                with _open(url, start=have) as r:
                    if have and r.status != 206:  # the server ignored the resume request
                        have = 0
                    with open(part, "ab" if have else "wb") as f:
                        while True:
                            if cancelled and cancelled():
                                raise Cancelled()
                            block = r.read(BLOCK)
                            if not block:
                                break
                            f.write(block)
                            have += len(block)
                            failures = 0
                            if progress:
                                progress(have, size)
            except Cancelled:
                raise
            except _NETWORK_ERRORS as e:
                failures += 1
                if failures > 8:
                    raise DownloadError(f"The download kept failing: {_reason(e)}. Check the internet connection and try again; it will continue from where it stopped.") from e
                time.sleep(min(30, 2**failures))
                continue
            if have < size:  # the connection closed early; go round again and resume
                failures += 1
                if failures > 8:
                    raise DownloadError("The download kept stopping early. Check the internet connection and try again; it will continue from where it stopped.")
                continue
        if sha256_of(part, cancelled) == sha256:
            os.replace(part, dest)
            return
        part.unlink(missing_ok=True)
        if started_over:
            raise DownloadError("The downloaded file was damaged twice in a row. Try again later, or on another network.")
        started_over = True


def _reason(e: Exception) -> str:
    text = str(getattr(e, "reason", "") or e)
    return text[:160] or type(e).__name__


class _RemoteFile(io.RawIOBase):
    """A file on a web server, read a range at a time. Enough for zipfile to
    read an archive's list of contents without downloading the archive."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size or not len(b):
            return 0
        end = min(self.size, self.pos + len(b)) - 1
        with _open(self.url, self.pos, end) as r:
            data = r.read()
        b[: len(data)] = data
        self.pos += len(data)
        return len(data)


def fetch_zip_without(url: str, size: int, skip, dest: Path, progress=None, cancelled=None) -> None:
    """Download a zip but leave holes where the unwanted big files are.

    `skip(name)` says which members are not needed. The result opens as a
    normal zip; the skipped members are simply unreadable, every other member
    still carries its own checksum, which zipfile verifies on extraction.
    Used for the CPU runtime: its archive is 274 MB, of which 246 MB is one
    NVIDIA library the CPU never loads.
    """
    with _open(url, 0, 0) as r:
        final = r.geturl()
    zf = zipfile.ZipFile(io.BufferedReader(_RemoteFile(final, size), 256 * 1024))
    members = sorted(zf.infolist(), key=lambda i: i.header_offset)
    holes = []
    for n, info in enumerate(members):
        end = members[n + 1].header_offset if n + 1 < len(members) else zf.start_dir
        if skip(Path(info.filename).name) and end - info.header_offset > 8 * BLOCK:
            holes.append((info.header_offset, end))
    spans, at = [], 0
    for a, b in holes:
        if a > at:
            spans.append((at, a))
        at = b
    if at < size:
        spans.append((at, size))
    total, done = sum(b - a for a, b in spans), 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with open(part, "wb") as f:
        f.truncate(size)
        for a, b in spans:
            f.seek(a)
            left = b - a
            with _open(final, a, b - 1, timeout=120) as r:
                while left:
                    if cancelled and cancelled():
                        raise Cancelled()
                    block = r.read(min(BLOCK, left))
                    if not block:
                        raise DownloadError("The download stopped early.")
                    f.write(block)
                    left -= len(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
    os.replace(part, dest)


def fetch_members(url: str, size: int, names: tuple[str, ...], dest_dir: Path, progress=None, cancelled=None) -> list[Path]:
    """Take only the named files out of a remote zip, without downloading the rest.

    Used for the one library the CPU runtime needs from a 575 MB archive.
    Each file is checked against the checksum the archive itself records.
    """
    with _open(url, 0, 0) as r:  # follow the redirect once; the ranges then go straight to the file
        final = r.geturl()
    zf = zipfile.ZipFile(io.BufferedReader(_RemoteFile(final, size), 256 * 1024))
    wanted = [i for i in zf.infolist() if Path(i.filename).name.lower() in names]
    if len(wanted) != len(names):
        raise DownloadError("The engine's library archive does not contain the expected files.")
    total, done, out = sum(i.compress_size for i in wanted), 0, []
    dest_dir.mkdir(parents=True, exist_ok=True)
    for info in wanted:
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise DownloadError("The engine's library archive uses a compression this app cannot read.")
        with _open(final, info.header_offset, info.header_offset + 29) as r:
            name_len, extra_len = struct.unpack("<HH", r.read()[26:30])
        start = info.header_offset + 30 + name_len + extra_len
        target = dest_dir / Path(info.filename).name
        part = target.with_name(target.name + ".part")
        inflate = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
        crc, left = 0, info.compress_size
        with _open(final, start, start + info.compress_size - 1, timeout=120) as r, open(part, "wb") as f:
            while left:
                if cancelled and cancelled():
                    raise Cancelled()
                block = r.read(min(BLOCK, left))
                if not block:
                    raise DownloadError("The download stopped early.")
                left -= len(block)
                done += len(block)
                data = inflate.decompress(block) if inflate else block
                crc = zlib.crc32(data, crc)
                f.write(data)
                if progress:
                    progress(done, total)
            if inflate:
                data = inflate.flush()
                crc = zlib.crc32(data, crc)
                f.write(data)
        if crc & 0xFFFFFFFF != info.CRC:
            part.unlink(missing_ok=True)
            raise DownloadError("A downloaded library was damaged on the way.")
        os.replace(part, target)
        out.append(target)
    return out
