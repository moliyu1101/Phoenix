from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def relative_parts(name: str) -> tuple[str, ...]:
    if not name or '\\' in name or '\x00' in name or ':' in name:
        raise ValueError('Invalid artifact path')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or len(path.parts) > 16:
        raise ValueError('Artifact paths must stay inside their workspace')
    if any(len(p) > 240 for p in path.parts):
        raise ValueError('Artifact path component is too long')
    return path.parts


class SecureFiles:
    """POSIX openat/O_NOFOLLOW traversal prevents symlink escapes and check/use races."""
    def __init__(self, root: Path, max_bytes: int = 32 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def _parent(self, name: str, create: bool) -> tuple[int, str]:
        parts = relative_parts(name)
        if not parts:
            raise ValueError('A file path is required')
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                new_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            return fd, parts[-1]
        except BaseException:
            os.close(fd)
            raise

    def read(self, name: str, offset: int = 0, limit: int | None = None) -> bytes:
        if offset < 0:
            raise ValueError('Negative offset')
        limit = self.max_bytes if limit is None else min(limit, self.max_bytes)
        if limit < 1:
            raise ValueError('Invalid read length')
        parent, leaf = self._parent(name, False)
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                import stat
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('Only regular files may be read')
                os.lseek(fd, offset, os.SEEK_SET)
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    return stream.read(limit)
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def write(self, name: str, content: bytes, overwrite: bool = False):
        if len(content) > self.max_bytes:
            raise ValueError('File exceeds size limit')
        parent, leaf = self._parent(name, True)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
            flags |= os.O_TRUNC if overwrite else os.O_EXCL
            fd = os.open(leaf, flags, 0o600, dir_fd=parent)
            try:
                import stat
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('Only regular files may be written')
                with os.fdopen(os.dup(fd), 'wb') as stream:
                    stream.write(content)
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def list(self, prefix: str = '') -> list[dict]:
        if prefix:
            relative_parts(prefix)
        entries = []
        for base, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(base) / d).is_symlink())
            for name in sorted(files):
                p = Path(base) / name
                if p.is_symlink():
                    continue
                rel = p.relative_to(self.root).as_posix()
                if not rel.startswith(prefix):
                    continue
                entries.append({'path': rel, 'size': p.stat().st_size})
                if len(entries) >= 2000:
                    return entries
        return entries
