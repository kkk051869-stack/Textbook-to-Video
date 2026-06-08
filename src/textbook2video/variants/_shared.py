"""所有 variant 模块共用的转义、字号、延迟工具。

这些 helper 不需要注册——只被各 variant 函数 import 使用。
"""

from __future__ import annotations

import html as _html
from typing import Any


def _esc(text: Any) -> str:
    """HTML 转义，并把换行转成 <br>。"""
    return _html.escape(str(text or "")).replace("\n", "<br>")


def _fs(px: int, floor_ratio: float = 0.78) -> str:
    """流式字号 clamp：上限=px（保持 1920 现状不变），首选=等效 vw（1920 下 1vw=19.2px），
    下限≈px×floor_ratio。小视口/窄容器下优雅缩小，避免溢出；大屏维持原观感。
    """
    vw = round(px / 19.2, 2)
    floor = max(12, int(px * floor_ratio))
    return f"clamp({floor}px,{vw}vw,{px}px)"
