"""旧数据库的安全复制方案。

原则：
1. 只读取旧库，绝不删除、改写或移动原始文件；
2. 导入前先把旧库复制为带时间戳的备份；
3. 先复制到临时文件并做完整性校验，最后原子替换；
4. 任一步骤失败都保留原库，且不产生半成品目标库。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

from desktop.paths import AppPaths, dev_database_candidates

LOGGER = logging.getLogger("hephaestus.desktop.legacy")
SQLITE_MAGIC = b"SQLite format 3\x00"


class LegacyImportError(RuntimeError):
    """旧数据库无法安全导入。"""


def is_sqlite_file(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
    except OSError:
        return False


def count_notes(path: Path) -> int:
    """读取旧库的笔记数量；结构不符时返回 0。"""
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
            if "notes" not in tables:
                return 0
            return int(connection.execute("select count(*) from notes").fetchone()[0])
    except sqlite3.Error:
        return 0


def _validate_database(path: Path) -> None:
    if not is_sqlite_file(path):
        raise LegacyImportError("文件不是有效的 SQLite 数据库")
    with sqlite3.connect(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise LegacyImportError(f"数据库完整性校验失败: {integrity!r}")
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        if "notes" not in tables:
            raise LegacyImportError("数据库缺少 notes 表，可能不是 Hephaestus 数据库")


def import_database(source: Path, paths: AppPaths) -> Path:
    """把 source 复制到桌面数据目录，返回备份文件路径。"""
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise LegacyImportError(f"旧数据库不存在: {source}")
    target = paths.db_path
    if target.exists():
        raise LegacyImportError(f"目标数据库已存在，拒绝覆盖: {target}")

    paths.ensure()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = paths.backups_dir / f"legacy-hephaestus-{stamp}.db"
    shutil.copy2(source, backup)

    tmp = target.with_name(target.name + ".import.tmp")
    tmp.unlink(missing_ok=True)
    try:
        shutil.copy2(backup, tmp)
        _validate_database(tmp)
        os.replace(tmp, target)
    except Exception as exc:  # noqa: BLE001 - 需要把任何失败都转成可读错误
        tmp.unlink(missing_ok=True)
        raise LegacyImportError(f"导入失败，原始数据库保持不变: {exc}") from exc
    return backup


def find_legacy_candidate(paths: AppPaths) -> Path | None:
    if paths.db_path.exists():
        return None
    for candidate in dev_database_candidates():
        if candidate.is_file() and is_sqlite_file(candidate) and count_notes(candidate) > 0:
            return candidate
    return None


def auto_import_legacy(paths: AppPaths) -> Path | None:
    """首次启动且数据目录为空时，从旧数据库复制数据（原库保持原样）。"""
    candidate = find_legacy_candidate(paths)
    if candidate is None:
        return None
    backup = import_database(candidate, paths)
    LOGGER.info(
        "已复制旧数据库: source=%s target=%s backup=%s",
        candidate,
        paths.db_path,
        backup,
    )
    return paths.db_path
