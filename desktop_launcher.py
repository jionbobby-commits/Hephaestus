"""PyInstaller 入口。

以顶层脚本启动，保证 desktop 作为普通包被导入（而不是把包内模块当脚本执行）。
"""

from __future__ import annotations

import multiprocessing
import sys

from desktop.main import main

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        multiprocessing.freeze_support()
    sys.exit(main())
