"""Cross-process lock shared by polling and maintenance commands."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO


@contextmanager
def single_instance_lock(database_path: Path) -> Iterator[IO[str]]:
    """Prevent polling and destructive maintenance from sharing one database."""
    lock_path = database_path.with_suffix(database_path.suffix + ".polling.lock")
    stream: IO[str] | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = lock_path.open("a+", encoding="utf-8")
        os.fchmod(stream.fileno(), 0o600)
    except OSError as exc:
        if stream is not None:
            stream.close()
        raise RuntimeError(f"Не удалось открыть polling-lock {lock_path}: {exc}") from exc

    acquired = False
    try:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.seek(0)
            owner = stream.read().strip()
            suffix = f" (PID {owner})" if owner.isdigit() else ""
            raise RuntimeError(
                f"Другой экземпляр U-Calc уже использует эту базу{suffix}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Не удалось захватить polling-lock {lock_path}: {exc}") from exc
        acquired = True
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        except OSError as exc:
            raise RuntimeError(f"Не удалось записать polling-lock {lock_path}: {exc}") from exc
        yield stream
    finally:
        if acquired:
            # Closing the descriptor below releases an advisory flock as well.
            with suppress(OSError):
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
