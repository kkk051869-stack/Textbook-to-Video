"""元素变体库（Variant Library）

把每种 storyboard element 的多套版式分文件管理，
通过 `@register` 装饰器集中注册到 `VARIANTS` 表，按 seg_id 稳定轮换。

公共 API：
    pick_variant_html(etype, elem, seg_id, delay_class, available_image_keys,
                       preferred=None) -> str | None
        渲染单个元素：先在 preferred 子集内 hash 选 variant，再 fallback 全库。
    render_text_group(htmls, seg_id) → str
    pick_group_variant_html(group_name, htmls, seg_id) → str

新增 variant 步骤：
    1. 在对应 `variants/<etype>.py` 里写 `_xxx(elem, d, seg_id, imgs) -> str`
    2. 加 `@register("etype", name="xxx")` 装饰器
    3. 装饰器执行时自动追加到 `VARIANTS[etype]`

`name` 字段是稳定 ID，主题可通过 `preferred_variants` 引用。
`default=True` 表示主题未指定 preferred 时作为优先选择（同时进入全库轮换）。
未来扩展可加 `style_tags={...}` 给 LLM 策展层用（第一版不强制）。
"""

from __future__ import annotations

from typing import Any, Callable

RenderFn = Callable[[dict, str, Any, set[str]], str]
GroupRenderFn = Callable[[list[str], Any], str]


class Variant:
    """注册元数据 + 渲染函数。"""

    __slots__ = ("name", "fn", "default", "style_tags")

    def __init__(
        self,
        name: str,
        fn: RenderFn,
        default: bool = False,
        style_tags: frozenset[str] | None = None,
    ) -> None:
        self.name = name
        self.fn = fn
        self.default = default
        self.style_tags = style_tags or frozenset()


# 全库注册表：etype → 有序 Variant 列表（按注册顺序）
VARIANTS: dict[str, list[Variant]] = {}

# 段落组（多段合并时）的 variants
GROUP_VARIANTS: dict[str, list[Variant]] = {}


def register(
    etype: str,
    *,
    name: str,
    default: bool = False,
    style_tags: set[str] | None = None,
):
    """注册元素 variant。装饰器形式。

    用法：
        @register("icon_group", name="badge_grid", default=True)
        def _ig_badge_grid(elem, d, seg_id, imgs) -> str:
            return "<div ...>"
    """
    def deco(fn: RenderFn) -> RenderFn:
        VARIANTS.setdefault(etype, []).append(
            Variant(
                name=name,
                fn=fn,
                default=default,
                style_tags=frozenset(style_tags) if style_tags else None,
            )
        )
        return fn
    return deco


def register_group(group: str, *, name: str, default: bool = False):
    """注册段落组 / 徽章组 variant。"""
    def deco(fn: GroupRenderFn) -> GroupRenderFn:
        GROUP_VARIANTS.setdefault(group, []).append(
            Variant(name=name, fn=fn, default=default)  # type: ignore[arg-type]
        )
        return fn
    return deco


def _pick_index(n: int, seg_id: Any) -> int:
    """稳定分桶：数字 seg_id 走模运算，非数字走 hash。"""
    if n <= 1:
        return 0
    try:
        return (int(str(seg_id)) - 1) % n
    except (ValueError, TypeError):
        return abs(hash(str(seg_id))) % n


def _filter_preferred(
    variants: list[Variant], preferred: list[str] | None,
) -> list[Variant]:
    """主题给了偏好名单时，限定在子集内选；空 / 全无匹配则用全库。"""
    if not preferred:
        return variants
    by_name = {v.name: v for v in variants}
    pool = [by_name[n] for n in preferred if n in by_name]
    return pool or variants


def pick_variant_html(
    etype: str,
    elem: dict,
    seg_id: Any,
    delay_class: str,
    available_image_keys: set[str],
    preferred: list[str] | None = None,
    lock_first: bool = False,
) -> str | None:
    """按 etype 选 variant 渲染。preferred 限定时优先在子集里 hash 选。

    `lock_first=True`：不按 seg_id 轮换，恒取 pool 第 0 个 variant——用于让
    "同一主题整片的标题版式保持一致"的 heading（numbered_chapter 里的序号仍由
    seg_id 传入 fn 决定，只是不再切换版式类型）。

    返回 None 表示该 etype 不在变体库（调用方应进入 fallback 或返回 None）。
    返回 "" 表示元素数据不完整（如 items 为空），跳过渲染。
    """
    fns = VARIANTS.get(etype)
    if not fns:
        return None
    # 内置硬约束（每种 etype 必填字段检查）
    if etype == "icon_group" and not (elem.get("items") or []):
        return ""
    if etype in ("flow_step", "activity_step") and not (elem.get("steps") or []):
        return ""
    if etype == "comparison_panel" and len(elem.get("items") or []) < 2:
        return ""
    if etype == "table" and not (elem.get("rows") or []):
        return ""

    pool = _filter_preferred(fns, preferred)
    idx = 0 if lock_first else _pick_index(len(pool), seg_id)
    return pool[idx].fn(elem, delay_class, seg_id, available_image_keys)


def pick_group_variant_html(
    group_name: str, htmls: list[str], seg_id: Any,
) -> str:
    """合并组（text_group / badge_row）按 seg_id 选变体。"""
    variant = pick_group_variant(group_name, seg_id)
    if variant is None:
        return "".join(htmls)
    return variant.fn(htmls, seg_id)  # type: ignore[call-arg]


def pick_group_variant(group_name: str, seg_id: Any) -> Variant | None:
    """Return the deterministically selected group variant."""
    pool = GROUP_VARIANTS.get(group_name, [])
    if not pool:
        return None
    idx = _pick_index(len(pool), seg_id)
    return pool[idx]


# === 自动加载所有 variant 模块 ===
# 导入这些模块会触发 @register 装饰器把 variant 注册进 VARIANTS。
# 新增 variant 文件时记得在此 import 一行。
from textbook2video.variants import (  # noqa: E402,F401
    _shared,
    badge,
    comparison_panel,
    flow_step,
    groups,
    heading,
    icon_group,
    image,
    layouts,
    quote,
    subheading,
    table,
    text,
)
# heading/activity_step 通过其他模块处理
try:
    from textbook2video.variants import activity_step  # noqa: F401
except ImportError:
    pass
