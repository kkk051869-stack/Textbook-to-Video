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
    "stat_card": ["value", "label"],
    "table": ["headers", "rows"],
    "comparison_panel": ["items"],
    "code": ["code"],
    "bar": ["items"],
    "chart_line": ["description"],
    "node": ["text"],
    "connection": ["from", "to"],
    "image": [],   # 特判
}
KNOWN_ELEMENT_TYPES = set(_REQUIRED_FIELDS)


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

    return rep


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

    for fld in _REQUIRED_FIELDS[etype]:
        val = el.get(fld)
        if val is None or (isinstance(val, (str, list)) and len(val) == 0):
            rep.errors.append(f"{where} {etype} 缺少必填字段 '{fld}'")


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
