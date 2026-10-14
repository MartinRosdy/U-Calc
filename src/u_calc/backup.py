"""Consistent SQLite backup command for production operations."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from .storage import SCHEMA_VERSION


def _fsync_file_and_directory(path: Path) -> None:
    """Persist file contents and its directory entry before reporting success."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(
        path.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def create_backup(source: Path, output: Path) -> tuple[int, str]:
    """Create a new online SQLite backup and verify its integrity.

    The destination is never overwritten. The SQLite backup API includes committed WAL
    pages, unlike copying the main database file directly while the bot is running.
    """
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if source == output:
        raise ValueError("Путь backup должен отличаться от рабочей базы")
    if not source.is_file():
        raise ValueError(f"Рабочая база не найдена: {source}")
    if not output.parent.is_dir():
        raise ValueError(f"Каталог backup не найден: {output.parent}")
    try:
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"Backup уже существует и не будет перезаписан: {output}") from exc
    else:
        os.close(descriptor)

    source_uri = f"file:{quote(str(source), safe='/')}?mode=ro"
    try:
        with (
            sqlite3.connect(source_uri, uri=True, timeout=30) as source_connection,
            sqlite3.connect(output, timeout=30) as backup_connection,
        ):
            source_connection.execute("PRAGMA busy_timeout=30000")
            source_connection.backup(backup_connection)
            integrity = str(backup_connection.execute("PRAGMA integrity_check").fetchone()[0])
            schema_version = int(backup_connection.execute("PRAGMA user_version").fetchone()[0])
            if integrity != "ok":
                raise ValueError(f"Проверка backup завершилась ошибкой: {integrity}")
        _fsync_file_and_directory(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return schema_version, integrity


def verify_database(path: Path) -> tuple[int, str]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Файл SQLite не найден: {path}")
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if integrity != "ok":
        raise ValueError(f"Проверка SQLite завершилась ошибкой: {integrity}")
    return schema_version, integrity


def restore_backup(backup: Path, destination: Path) -> tuple[int, Path | None]:
    """Atomically restore a verified backup while the polling lock is available."""
    from .locking import single_instance_lock

    backup = backup.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if backup == destination:
        raise ValueError("Backup и рабочая база должны быть разными файлами")
    backup_version, _ = verify_database(backup)
    if backup_version > SCHEMA_VERSION:
        raise ValueError(
            f"Backup использует schema v{backup_version}, а этот U-Calc поддерживает "
            f"не выше v{SCHEMA_VERSION}"
        )
    if not destination.parent.is_dir():
        raise ValueError(f"Каталог рабочей базы не найден: {destination.parent}")

    emergency_copy: Path | None = None
    temporary = destination.with_name(f".{destination.name}.restore-{uuid4().hex}.tmp")
    with single_instance_lock(destination):
        if destination.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            emergency_copy = destination.with_name(f"{destination.stem}-pre-restore-{timestamp}.db")
            create_backup(destination, emergency_copy)
        try:
            copied_version, _ = create_backup(backup, temporary)
            if copied_version != backup_version:
                raise ValueError(
                    "Backup изменился во время восстановления: "
                    f"проверена schema v{backup_version}, скопирована v{copied_version}"
                )
            if copied_version > SCHEMA_VERSION:
                raise ValueError(
                    f"Скопированный backup использует schema v{copied_version}, а этот "
                    f"U-Calc поддерживает не выше v{SCHEMA_VERSION}"
                )
            for suffix in ("-wal", "-shm"):
                destination.with_name(destination.name + suffix).unlink(missing_ok=True)
            os.replace(temporary, destination)
            directory_descriptor = os.open(
                destination.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return copied_version, emergency_copy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="u-calc-backup",
        description="Создать согласованную и проверенную резервную копию SQLite U-Calc.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("DATABASE_PATH", "/app/data/u_calc.db")),
        help="рабочая база; по умолчанию DATABASE_PATH",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="новый файл backup; существующий файл никогда не перезаписывается",
    )
    return parser


def main() -> None:
    parser = _parser()
    arguments = parser.parse_args()
    output = arguments.output
    if output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = arguments.database.parent / f"u_calc-backup-{timestamp}.db"
    try:
        schema_version, _ = create_backup(arguments.database, output)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(2, f"Не удалось создать backup: {exc}\n")
    print(f"Backup создан и проверен: {output.resolve()} (schema v{schema_version})")


def restore_main() -> None:
    parser = argparse.ArgumentParser(
        prog="u-calc-restore",
        description="Безопасно восстановить SQLite U-Calc из проверенного backup.",
    )
    parser.add_argument("--backup", type=Path, required=True, help="проверенный файл backup")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("DATABASE_PATH", "/app/data/u_calc.db")),
        help="рабочая база; по умолчанию DATABASE_PATH",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="подтвердить замену рабочей базы; текущая база сохраняется отдельно",
    )
    arguments = parser.parse_args()
    if not arguments.yes:
        parser.exit(2, "Восстановление не выполнено: добавьте --yes после остановки бота.\n")
    try:
        schema_version, emergency = restore_backup(arguments.backup, arguments.database)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        parser.exit(2, f"Не удалось восстановить backup: {exc}\n")
    emergency_note = f" Аварийная копия прежней БД: {emergency}." if emergency else ""
    print(
        f"База восстановлена и проверена: {arguments.database.resolve()} "
        f"(schema v{schema_version}).{emergency_note}"
    )


if __name__ == "__main__":
    main()
