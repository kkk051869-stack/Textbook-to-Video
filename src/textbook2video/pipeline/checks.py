"""校验与自检：storyboard 静态校验、环境 doctor、batch 课节解析。

都不依赖 LLM/网络（doctor 的浏览器探测除外，失败即报告，不抛异常）。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ValidationReport",
    "validate_storyboard",
    "segment_weight",
    "DoctorResult",
    "run_doctor",
    "parse_section_specs",
    "parse_lesson_specs",
    "KNOWN_ELEMENT_TYPES",
    "KNOWN_VISUAL_TYPES",
]

KNOWN_VISUAL_TYPES = {
    "title", "definition", "process", "comparison", "data-chart", "data-bar",
    "network", "tree", "timeline", "illustration", "activity",
}

# 每种 element 类型的必填字段（image 特殊处理：src 或 description 二选一）
_REQUIRED_FIELDS = {
    "heading": ["text"],
    "subheading": ["text"],
    "text": ["text"],
    "label": ["text"],
    "quote": ["text"],
    "icon_group": ["items"],
    "flow_step": ["steps"],
    "activity_step": ["steps"],
    "table": ["headers", "rows"],
    "comparison_panel": ["items"],
    "code": ["code"],
    "bar": ["items"],
    "chart_line": ["description"],
    "node": ["text"],
    "connection": ["from", "to"],
    "focus_box": ["target", "bbox"],
    "callout": ["target", "bbox"],
    "quiz_card": ["questions"],
    "image": [],   # 特判
}
KNOWN_ELEMENT_TYPES = set(_REQUIRED_FIELDS)

# 空间权重（见 docs/research/adaptive-slide-layout.md §4.1a）：粗粒度密度预算，
# 不是像素。table 特判为 1 + 0.5×行数。
_ELEMENT_WEIGHT: dict[str, float] = {
    "image": 3, "comparison_panel": 3,
    "flow_step": 2, "activity_step": 2,
    "quiz_card": 3,
    "icon_group": 1.5, "bar": 1.5,
    "quote": 1, "text": 1, "chart_line": 1, "code": 1,
    "heading": 0, "subheading": 0, "label": 0, "badge": 0,
    "node": 0, "connection": 0, "focus_box": 0, "callout": 0,
}
# 主元素（每页应恰好 1 个）
_HERO_TYPES = {"image", "comparison_panel", "table", "flow_step", "activity_step", "quiz_card"}
# 互斥对（同页只应出现其一）
# 功能重叠分组：同一组内同页最多用 1 种（都是同类目的不同 widget，并用显啰嗦）
_OVERLAP_GROUPS = [
    ("列举", {"icon_group", "flow_step", "activity_step"}),       # 都是逐条列举
    ("数据展示", {"comparison_panel", "table", "bar", "chart_line"}),  # 都是结构化数据/图表
    ("小标签", {"badge", "label"}),                                 # 都是小标签
]
_WEIGHT_MAX = 8.0   # 超过 → 过密，建议拆段/裁剪
_WEIGHT_MIN = 4.0   # 低于 → 偏空，建议稀疏档/增内容
_MAX_BODY_TYPES = 4  # 一页最多几种不同 body 类型（充实靠多放同类实例，而非多加类型）


def segment_weight(elements: list[dict]) -> float:
    """估算一页 body 元素的空间权重总和（table 按行数加权）。"""
    total = 0.0
    for el in elements:
        t = el.get("type", "")
        if t == "table":
            total += 1 + 0.5 * len(el.get("rows", []) or [])
        else:
            total += _ELEMENT_WEIGHT.get(t, 1)
    return round(total, 1)


# ---------------------------------------------------------------------------
# storyboard 校验
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_storyboard(
    storyboard: dict,
    *,
    base_dir: str | Path | None = None,
    script_path: str | Path | None = None,
) -> ValidationReport:
    """对 storyboard dict 做静态校验，返回 errors（致命）/warnings（建议）。

    base_dir：storyboard JSON 所在目录，用于校验 image src 是否真实存在
    （约定图片在 base_dir/images/ 下）。
    script_path：同名 *_script.txt 路径（若存在），用于比对讲稿段数与
    storyboard 页数是否一致——不一致仅告警（LLM 合并/新增页是合理的）。
    """
    rep = ValidationReport()
    base = Path(base_dir) if base_dir else None

    segments = storyboard.get("segments")
    if not isinstance(segments, list) or not segments:
        rep.errors.append("缺少非空的 segments 列表")
        return rep

    # segment id 重复 → 会破坏 {{IMG_}} 的 seg_id:elem_id 键，定为错误
    ids = [seg.get("id") for seg in segments if seg.get("id") is not None]
    dups = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dups:
        rep.errors.append(f"segment id 重复: {dups}")

    # 与讲稿段数一致性（#3）：能找到同级 script.txt 时比对
    if script_path and Path(script_path).exists():
        from textbook2video.pipeline.orchestrator import read_script_segments

        n_script = len(read_script_segments(script_path))
        n_pages = len(segments)
        if n_script and n_script != n_pages:
            rep.warnings.append(
                f"讲稿 {n_script} 段 vs storyboard {n_pages} 页不一致"
                f"（LLM 可能合并/新增页；请确认无「页缺旁白」或「旁白缺页」）"
            )

    for idx, seg in enumerate(segments):
        where = f"segment[{idx}]"
        sid = seg.get("id", idx)
        if "narration" not in seg or not str(seg.get("narration", "")).strip():
            rep.errors.append(f"{where}(id={sid}) 缺少 narration")

        vtype = seg.get("visual_type")
        if not vtype:
            rep.warnings.append(f"{where}(id={sid}) 缺少 visual_type")
        elif vtype not in KNOWN_VISUAL_TYPES:
            rep.warnings.append(f"{where}(id={sid}) 未知 visual_type: {vtype}")

        # render_mode：可选字段，未填或非法值都不报错——下游默认按 template 走
        rmode = seg.get("render_mode")
        if rmode is not None and rmode not in ("template", "llm"):
            rep.warnings.append(
                f"{where}(id={sid}) 未知 render_mode: {rmode!r}（将按 template 处理）"
            )

        dur = seg.get("audio_duration_sec")
        if dur is None:
            rep.warnings.append(
                f"{where}(id={sid}) 无 audio_duration_sec（animate 将用默认时长）"
            )
        elif not isinstance(dur, (int, float)) or isinstance(dur, bool) or dur <= 0:
            rep.errors.append(f"{where}(id={sid}) audio_duration_sec 非正数: {dur!r}")

        elements = seg.get("elements", [])
        if not isinstance(elements, list) or not elements:
            rep.warnings.append(f"{where}(id={sid}) 没有 elements（页面会很空）")
            continue

        for ei, el in enumerate(elements):
            _validate_element(el, f"{where}.elements[{ei}]", rep, base)
        _check_overlay_targets(elements, f"{where}(id={sid})", rep)

        _check_density_and_roles(elements, f"{where}(id={sid})", rep)

    # 教材原图利用率：base_dir/images/ 下提取的真实图 vs storyboard 实际引用了几张
    _check_textbook_image_utilization(storyboard, base, rep)

    return rep


def _check_textbook_image_utilization(
    storyboard: dict, base: Path | None, rep: ValidationReport
) -> None:
    """统计教材原图利用率：实际被 image.src 引用的张数 / 可用张数。

    < 60% 警告（浪费教材资源——AI 重画教学价值不如真实教材图）。
    """
    if base is None:
        return
    img_dir = base / "images"
    if not img_dir.exists() or not img_dir.is_dir():
        return
    # 教材图通常以 fig 开头（如 fig1-1_xxx.png）；不含其他后处理生成物
    available = {p.name for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")}
    if not available:
        return

    used: set[str] = set()
    for seg in storyboard.get("segments", []):
        for el in seg.get("elements", []):
            if el.get("type") == "image":
                src = el.get("src")
                if src and src in available:
                    used.add(src)

    ratio = len(used) / len(available)
    summary = (
        f"教材原图利用率: {len(used)}/{len(available)} = {ratio:.0%}"
    )
    if ratio < 0.6:
        rep.warnings.append(
            f"{summary} —— 偏低，建议 storyboard 更多引用教材原图（教学价值高于 AI 重画）"
        )
    else:
        # 利用率合格，仅在 errors/warnings 都通过时显得多余——挂 info 没接口，先静默
        pass


def _check_density_and_roles(elements: list[dict], where: str, rep: ValidationReport) -> None:
    """空间权重 + 单主元素语法 + 互斥 校验（均为建议级 warning，不阻断渲染）。

    见 docs/research/adaptive-slide-layout.md §4.1 / 附录 A——这是"不信任模型自控、
    用确定性校验兜底"的落地（§4.1d）。
    """
    types = [el.get("type", "") for el in elements]
    tset = set(types)

    # 1) body 类型种数：太多类型 = 杂乱拥挤（充实应靠多放同类实例，而非多加类型）
    body_types = {t for t in tset if t not in ("heading", "subheading")}
    if len(body_types) > _MAX_BODY_TYPES:
        rep.warnings.append(
            f"{where} body 类型过多（{len(body_types)} 种 > {_MAX_BODY_TYPES}）：{sorted(body_types)}；"
            f"建议收敛到 3-4 种、靠多放同类实例充实"
        )

    # 2) 密度（权重）
    w = segment_weight(elements)
    if w > _WEIGHT_MAX:
        rep.warnings.append(f"{where} 内容过密（权重 {w} > {_WEIGHT_MAX}）：建议拆成两段或裁剪轻元素")
    elif w < _WEIGHT_MIN:
        rep.warnings.append(f"{where} 内容偏空（权重 {w} < {_WEIGHT_MIN}）：建议走稀疏档或增补内容")

    # 2) 单主元素语法
    heroes = [t for t in types if t in _HERO_TYPES]
    if len(heroes) > 1:
        rep.warnings.append(f"{where} 有多个主元素 {heroes}：建议每页恰好 1 个（image/comparison_panel/table/flow_step）")

    # 3) 功能重叠：同一组内出现 ≥2 种 → 重复啰嗦，选其一
    for label, group in _OVERLAP_GROUPS:
        hit = sorted(group & tset)
        if len(hit) >= 2:
            rep.warnings.append(f"{where} {label}类重叠：{hit} 同页（功能重叠，选其一）")

    # 4) 同类型重复（如 2 个 image / 2 个 icon_group）；只看 body 元素（权重>0）
    def _is_body(t: str) -> bool:
        return t == "table" or _ELEMENT_WEIGHT.get(t, 1) >= 1

    body_dups = sorted({t for t in tset if _is_body(t) and types.count(t) > 1})
    if body_dups:
        rep.warnings.append(f"{where} 重复的元素类型 {body_dups}：每种类型每页最多 1 次")


def _check_overlay_targets(elements: list[dict], where: str, rep: ValidationReport) -> None:
    overlays = [el for el in elements if el.get("type") in ("focus_box", "callout")]
    if not overlays:
        return
    image_ids = {
        str(el.get("id") or "").strip()
        for el in elements
        if el.get("type") == "image" and str(el.get("id") or "").strip()
    }
    if not image_ids:
        rep.errors.append(f"{where} 有 focus_box/callout 但没有可绑定的 image id")
        return
    for el in overlays:
        target = str(el.get("target") or "").strip()
        if target and target not in image_ids:
            rep.errors.append(
                f"{where} {el.get('type')} target={target!r} 未指向本页 image id"
            )


def _validate_element(el: dict, where: str, rep: ValidationReport, base: Path | None) -> None:
    etype = el.get("type")
    if etype not in KNOWN_ELEMENT_TYPES:
        rep.errors.append(f"{where} 未知 element 类型: {etype!r}")
        return

    if etype == "image":
        src = el.get("src")
        if not src and not el.get("description"):
            rep.errors.append(f"{where} image 既无 src 也无 description")
        if src and base is not None:
            img_path = base / "images" / src
            if not img_path.exists():
                rep.errors.append(f"{where} image src 文件不存在: images/{src}")
        return

    if etype in ("focus_box", "callout"):
        target = str(el.get("target") or "").strip()
        bbox = el.get("bbox")
        if not target:
            rep.errors.append(f"{where} {etype} 缺少必填字段 'target'")
        if not _valid_bbox(bbox):
            rep.errors.append(f"{where} {etype} bbox 必须是 [x, y, w, h] 数字数组")
        if etype == "callout" and not (el.get("label") or el.get("text")):
            rep.errors.append(f"{where} callout 缺少 label 或 text")
        return

    if etype == "quiz_card":
        questions = el.get("questions")
        if not isinstance(questions, list) or not questions:
            rep.errors.append(f"{where} quiz_card 缺少非空 questions")
            return
        for qi, q in enumerate(questions):
            if not isinstance(q, dict):
                rep.errors.append(f"{where}.questions[{qi}] 必须是对象")
                continue
            if not str(q.get("question") or "").strip():
                rep.errors.append(f"{where}.questions[{qi}] 缺少 question")
            if not str(q.get("answer") or "").strip():
                rep.warnings.append(f"{where}.questions[{qi}] 缺少 answer")
            if not str(q.get("explanation") or "").strip():
                rep.warnings.append(f"{where}.questions[{qi}] 缺少 explanation")
        return

    for fld in _REQUIRED_FIELDS[etype]:
        val = el.get(fld)
        if val is None or (isinstance(val, (str, list)) and len(val) == 0):
            rep.errors.append(f"{where} {etype} 缺少必填字段 '{fld}'")


def _valid_bbox(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    for item in value:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            return False
    return value[2] > 0 and value[3] > 0


# ---------------------------------------------------------------------------
# 环境 doctor
# ---------------------------------------------------------------------------

@dataclass
class DoctorResult:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


def run_doctor(*, browser_channel: str = "msedge", ping: bool = False) -> list[DoctorResult]:
    """预检运行环境：凭据、ffmpeg、浏览器、TTS、（可选）LLM 连通。"""
    results: list[DoctorResult] = []

    # LLM 凭据
    try:
        from textbook2video.pipeline.config import select_llm_config

        api_key, base_url, model = select_llm_config()
        if api_key:
            results.append(DoctorResult(
                "LLM 凭据", True, f"base_url={base_url} model={model}"
            ))
        else:
            results.append(DoctorResult(
                "LLM 凭据", False, "未设置 API key（.env 的 ECNU_API_KEY / LLM_API_KEY）"
            ))
    except Exception as exc:  # noqa: BLE001
        results.append(DoctorResult("LLM 凭据", False, f"配置加载失败: {exc}"))

    # ffmpeg / ffprobe
    results.append(DoctorResult(
        "ffmpeg", shutil.which("ffmpeg") is not None,
        shutil.which("ffmpeg") or "未找到（录制/取时长/合成都需要）",
    ))
    results.append(DoctorResult(
        "ffprobe", shutil.which("ffprobe") is not None,
        shutil.which("ffprobe") or "未找到（部分校验用，可选）",
        required=False,
    ))

    # Playwright 浏览器
    results.append(_check_browser(browser_channel))

    # edge-tts
    try:
        import edge_tts  # noqa: F401

        results.append(DoctorResult("edge-tts", True, "已安装"))
    except Exception as exc:  # noqa: BLE001
        results.append(DoctorResult("edge-tts", False, f"导入失败: {exc}"))

    # 可选：LLM 连通 ping
    if ping:
        results.append(_ping_llm())

    return results


def _check_browser(channel: str) -> DoctorResult:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            launch_kwargs: dict = {"headless": True}
            if channel:
                launch_kwargs["channel"] = channel
            try:
                browser = pw.chromium.launch(**launch_kwargs)
            except Exception:
                # 指定 channel 不可用时退回内置 chromium
                browser = pw.chromium.launch(headless=True)
                browser.close()
                return DoctorResult(
                    "浏览器", True,
                    f"channel={channel} 不可用，但内置 chromium 可用",
                    required=False,
                )
            browser.close()
        return DoctorResult("浏览器", True, f"channel={channel} 可用")
    except Exception as exc:  # noqa: BLE001
        return DoctorResult(
            "浏览器", False,
            f"不可用: {exc}（试试 playwright install chromium）",
        )


def _ping_llm() -> DoctorResult:
    try:
        from textbook2video.llm.client import chat

        reply = chat(
            [{"role": "user", "content": "ping，请只回复 ok"}],
            timeout=30, max_tokens=16,
        )
        return DoctorResult("LLM 连通", bool(reply), f"返回: {str(reply)[:40]}")
    except Exception as exc:  # noqa: BLE001
        return DoctorResult("LLM 连通", False, f"调用失败: {exc}", required=False)


# ---------------------------------------------------------------------------
# batch 课节解析
# ---------------------------------------------------------------------------

def parse_section_specs(spec: str) -> list[tuple[int, int]]:
    """解析 DOCX 章节规格串：'3:0,3:1,4:0' → [(3,0),(3,1),(4,0)]。"""
    pairs: list[tuple[int, int]] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"章节规格应为 chapter:section，得到: {token!r}")
        c, s = token.split(":", 1)
        pairs.append((int(c), int(s)))
    if not pairs:
        raise ValueError("未解析出任何章节")
    return pairs


def parse_lesson_specs(spec: str) -> list[int]:
    """解析 PDF 课号规格串：'1,2,4' → [1,2,4]。"""
    lessons = [int(t.strip()) for t in spec.split(",") if t.strip()]
    if not lessons:
        raise ValueError("未解析出任何课号")
    return lessons
