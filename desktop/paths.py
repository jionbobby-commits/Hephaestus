"""桌面版文件布局：用户数据与程序文件彻底分离。

桌面模式的数据根目录默认为 %LOCALAPPDATA%\\Hephaestus，包含：

- hephaestus.db   用户数据库
- logs/           运行日志（不含笔记正文）
- config/         本地配置
- backups/        迁移前生成的数据库备份

Web 开发模式仍然使用 app.database 的默认配置（data/hephaestus.db），
两者互不影响。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Hephaestus"

#: 显式覆盖数据目录（测试与便携部署使用）。
DATA_DIR_ENV = "HEPHAESTUS_DATA_DIR"


def _default_root() -> Path:
    override = os.environ.get(DATA_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        return Path(local_appdata) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


@dataclass(frozen=True)
class AppPaths:
    """桌面版使用的全部路径。"""

    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / "hephaestus.db"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "hephaestus-desktop.log"

    @property
    def database_url(self) -> str:
        return sqlite_url(self.db_path)

    def ensure(self) -> "AppPaths":
        for directory in (self.root, self.logs_dir, self.config_dir, self.backups_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self


def sqlite_url(path: Path) -> str:
    """把 Windows 绝对路径转换为 SQLAlchemy 可用的 sqlite URL。"""
    return "sqlite:///" + Path(path).expanduser().resolve().as_posix()


def resolve_paths(root: str | Path | None = None) -> AppPaths:
    if root is not None:
        return AppPaths(Path(root).expanduser().resolve())
    return AppPaths(_default_root().expanduser().resolve())


def project_dir() -> Path:
    """源码仓库根目录（未打包时）。"""
    return Path(__file__).resolve().parent.parent


def program_dir() -> Path:
    """当前程序所在目录：打包后为 exe 目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_dir()


def dev_database_candidates() -> list[Path]:
    """Web 模式可能使用过的旧数据库位置（只作为迁移来源，绝不修改）。"""
    raw = [
        program_dir() / "data" / "hephaestus.db",
        project_dir() / "data" / "hephaestus.db",
        Path.cwd() / "data" / "hephaestus.db",
    ]
    unique: list[Path] = []
    for candidate in raw:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in unique:
            unique.append(resolved)
    return unique
