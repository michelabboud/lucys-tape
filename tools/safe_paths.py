#!/usr/bin/env python3
"""Lucy's Tape — reading sources and writing the archive without leaving their folders (LT-SEC-009).

Every tool that reads a session or note, or writes into the archive, goes through here:

- a source is read only when it resolves to a regular file inside its source folder, and
  the check is made on the opened file itself, so it cannot be swapped between check and read;
- an archive file is written by walking down from the archive root one folder at a time
  without following links, creating a new private temporary file there, and renaming it
  over the target. A symlink planted at the target is replaced, never written through, and
  a crash leaves the old file or the new one, never half of one;
- a date used in a file name must be a date.

Where the platform lacks the directory-descriptor calls (Windows), writes fall back to
checking the resolved folder before writing; that leaves a race against someone who can
rename folders inside the archive while it runs, which Phase 2 revisits.
"""
import errno
import os
import re
import secrets
import stat
from pathlib import Path

DATE_RX = re.compile(r"\d{4}-\d\d-\d\d")
NO_DATE = "0000-00-00"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
# O_NONBLOCK so that opening a FIFO planted under a source name returns at once and is
# then refused as not a regular file, instead of blocking the refresh forever.
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_HAVE_DIR_FD = (_NOFOLLOW and _DIRECTORY and os.open in os.supports_dir_fd
                # os.replace takes dir_fd arguments but is never listed in supports_dir_fd;
                # it shares renameat with os.rename, which is (0.2.21 checked replace, so the
                # descriptor walk never ran and every write took the fallback)
                and os.mkdir in os.supports_dir_fd and os.rename in os.supports_dir_fd
                and os.unlink in os.supports_dir_fd)


class Refused(OSError):
    """A path that escapes its folder, is a link where none is allowed, or is not a regular file."""

    def __init__(self, why):
        super().__init__(errno.EPERM, why)


def date_prefix(ts):
    """The YYYY-MM-DD at the start of a timestamp, or 0000-00-00 when it is not one."""
    head = (ts or "")[:10]
    return head if DATE_RX.fullmatch(head) else NO_DATE


def open_source(path, root, follow_links=True):
    """(binary file, stat) for a regular file inside root. The caller closes the file.

    follow_links=True accepts a symlink whose target is also inside root (Claude Code
    links subagent sessions to their siblings); False refuses any symlink, which is right
    for the archive, where the tools never create one. The regular-file check is made on
    the opened descriptor, so the file cannot be swapped between check and read."""
    path, root = Path(path), Path(root).resolve()
    if not follow_links and path.is_symlink():
        raise Refused("a symlink")
    try:
        real = path.resolve()
    except RuntimeError as e:  # a symlink loop, on Python before 3.13 (OSError from 3.13)
        raise Refused("a symlink loop") from e
    if not real.is_relative_to(root):
        raise Refused("outside its folder")
    fd = os.open(real, os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("not a regular file")
        if _NONBLOCK:
            os.set_blocking(fd, True)
        return os.fdopen(fd, "rb"), st
    except BaseException:
        os.close(fd)
        raise


def read_source_text(path, root, follow_links=True):
    """(text, stat) of a regular file inside root, decoded as UTF-8 with replacement."""
    fh, st = open_source(path, root, follow_links)
    with fh:
        return fh.read().decode("utf-8", "replace"), st


def temp_name(name):
    """A hidden name beside the target, random so that a file left by a killed run can
    never collide with a later one (a reused process id made O_EXCL fail every night)."""
    return f".{name[:200]}.{secrets.token_hex(8)}.tmp"


def _parts(path, root):
    try:
        rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(root))
    except ValueError:
        raise Refused("outside its folder") from None
    parts = rel.parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise Refused("outside its folder")
    return parts[:-1], parts[-1]


def write_text(path, text, root, errors="strict"):
    """Write text to path (inside root) atomically, privately, and without following links.

    Missing folders between root and path are created (mode 700). root itself is trusted:
    it is the archive the user pointed us at."""
    dirs, name = _parts(path, root)
    data = text.encode("utf-8", errors)
    if not _HAVE_DIR_FD:
        return _write_text_fallback(Path(path), data, Path(root), dirs)
    try:
        fd = os.open(root, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise Refused("the archive folder itself is a link") from e
        raise
    try:
        for d in dirs:
            try:
                nfd = os.open(d, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(d, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass  # another writer (the importer runs outside the lock) made it first
                nfd = os.open(d, os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=fd)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise Refused(f"folder {d!r} is a link or not a folder") from e
                raise
            os.close(fd)
            fd = nfd
        tmp = temp_name(name)
        tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600, dir_fd=fd)
        try:
            with os.fdopen(tfd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(fd)


def _write_text_fallback(path, data, root, dirs):
    parent = root.resolve().joinpath(*dirs)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.resolve() != parent:
        raise Refused("a folder on the way is a link")
    tmp = parent / temp_name(path.name)
    tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(tfd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, parent / path.name)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
