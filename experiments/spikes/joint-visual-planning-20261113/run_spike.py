"""One-case spike: jointly plan narration, graph IDs and focus targets.

This runner lives under one isolated run directory. It does not change the
ordinary produce entrypoint or any production module.
"""

from __future__ import annotations

import hashlib
import json
import re
import copy
from pathlib import Path
from xml.etree import ElementTree as ET

from textbook2video.animation_gen import _inline_reviewed_visual_objects
from textbook2video.animation_ids import visual_node_animation_id
from textbook2video.llm.client import chat
from textbook2video.pipeline.compose import mux_audio_video
from textbook2video.pipeline.narrator import generate_sentence_audio, get_audio_duration
from textbook2video.pipeline.parser import extract_pdf_pages_info
from textbook2video.pipeline.recorder import record_html_to_video
from textbook2video.pipeline.subtitles import generate_srt
from textbook2video.pipeline.visual_page_render import course_page_html, validate_local_page
from textbook2video.research.visual_grammar import render_visual, validate_visual
from textbook2video.research.exact_source_excerpts import exact_evidence


ROOT = Path.cwd().resolve()
RUN = Path(__file__).resolve().parent
SOURCE_PDF = ROOT / "datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/cases/lesson_002/source/source.pdf"
MODEL = "ecnu-plus"
THEME = "bright"
SEGMENT_ID = "spike-utxo"
ELEMENT_ID = "planned-graph"
SOURCE_LOCATOR = "source.pdf, PDF page 1, section （一）链式数据结构"
SYSTEM = "你是严谨的教材教学规划器。只使用给出的教材原文；准确区分来源事实与算术推导；不补充常识性但原文未支持的机制。输出必须是单个 JSON 对象，不要 Markdown。"


def parse_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValueError("model reply contains no JSON object")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("model plan must be a JSON object")
    return value


def validate_plan(plan: dict, source: str) -> None:
    required = {"proposition", "narration", "visual"}
    if required - set(plan):
        raise ValueError(f"missing top-level fields: {sorted(required - set(plan))}")
    proposition = plan["proposition"]
    if not isinstance(proposition, dict) or not proposition.get("text"):
        raise ValueError("proposition.text is required")
    if not isinstance(proposition.get("source_excerpt"), str) or proposition["source_excerpt"] not in source:
        raise ValueError("proposition.source_excerpt must be an exact source substring")
    if proposition.get("source_locator") != SOURCE_LOCATOR:
        raise ValueError("proposition.source_locator must identify the supplied PDF page and section")
    visual = plan["visual"]
    render_spec, detached_nodes = renderer_compatible_spec(visual, source)
    validate_visual(render_spec, source=source)
    nodes = visual["nodes"]
    edges = visual.get("edges", [])
    node_ids = {node["id"] for node in nodes}
    edge_ids = {edge.get("id") for edge in edges}
    if None in edge_ids or len(edge_ids) != len(edges):
        raise ValueError("each relationship needs a unique stable id")
    edge_ids = set(edge_ids)
    narration = plan["narration"]
    if not isinstance(narration, list) or not 3 <= len(narration) <= 6:
        raise ValueError("narration must contain 3-6 sentence-level cues")
    sentence_ids = set()
    focus_sets = []
    for cue in narration:
        if not isinstance(cue, dict) or not cue.get("id") or not cue.get("text"):
            raise ValueError("each narration cue needs id and text")
        if cue["id"] in sentence_ids:
            raise ValueError("duplicate narration cue id")
        sentence_ids.add(cue["id"])
        focus = cue.get("focus_ids")
        if not isinstance(focus, list) or not focus:
            raise ValueError(f"narration cue {cue['id']} needs focus_ids")
        for target in focus:
            if target.startswith("node:") and target[5:] not in node_ids:
                raise ValueError(f"unknown planned node in {cue['id']}: {target}")
            if target.startswith("edge:") and target[5:] not in edge_ids:
                raise ValueError(f"unknown planned relation in {cue['id']}: {target}")
            if not (target.startswith("node:") or target.startswith("edge:")):
                raise ValueError(f"focus target must be node:<id> or edge:<id>: {target}")
        focus_sets.append(tuple(focus))
    if len(set(focus_sets)) < 2:
        raise ValueError("focus mapping must change across at least two narration stages")
    save_json(RUN / "renderer-adaptation.json", {
        "rule": "single isolated, source-supported concept node is rendered as the existing flow constraint footer; no graph edge is invented",
        "detached_nodes": detached_nodes,
        "compiled_graph_node_ids": [node["id"] for node in render_spec["nodes"]],
        "compiled_graph_edge_ids": [edge["id"] for edge in render_spec["edges"]],
    })


def renderer_compatible_spec(visual: dict, source: str) -> tuple[dict, list[dict]]:
    """Move one independent source-supported note to the renderer's existing footer.

    This preserves its generated ID and evidence without fabricating a relation.
    More than one detached object remains a hard failure.
    """
    nodes = visual.get("nodes")
    edges = visual.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("joint visual plan must provide nodes and edges")
    node_ids = {node.get("id") for node in nodes if isinstance(node, dict)}
    degree = {ident: 0 for ident in node_ids}
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            raise ValueError("relationship endpoints must reference planned objects")
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    detached = [node for node in nodes if degree.get(node.get("id"), 0) == 0]
    if len(detached) > 1:
        raise ValueError("more than one unconnected object; cannot preserve as one footer note")
    compiled = copy.deepcopy(visual)
    if detached:
        if visual.get("kind") != "flow" or visual.get("constraint"):
            raise ValueError("existing visual kind cannot represent one detached object without a new relation")
        note = detached[0]
        exact_evidence(note.get("evidence"), source)
        label = str(note.get("label") or "").strip()
        detail = str(note.get("detail") or "").strip()
        if not label or not detail or len(label) > 48 or len(detail) > 96:
            raise ValueError("detached concept needs a readable label and detail")
        compiled["nodes"] = [node for node in nodes if node.get("id") != note["id"]]
        compiled["constraint"] = f"{label}：{detail}"
        compiled["constraint_evidence"] = note["evidence"]
    return compiled, detached


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_prompt(source: str) -> str:
    return f"""从下面真实教材原文中自主选择一个适合约 20–40 秒讲解、且包含明确对象和关系的知识点。一次性共同规划讲解命题、旁白、视觉图及逐句关注映射。

必须只输出以下形状的 JSON：
{{
  "proposition": {{"text":"一句核心教学命题", "source_excerpt":"原文中的精确连续子串", "source_locator":"{SOURCE_LOCATOR}"}},
  "narration": [
    {{"id":"sentence_1", "text":"完整的一句中文旁白", "focus_ids":["node:<节点ID>", "edge:<关系ID>"], "focus_reason":"为什么此对象/关系服务于本句"}}
  ],
  "visual": {{
    "schema_version":"teaching-visual-v2", "id":"stable_graph_id", "kind":"flow", "title":"短标题", "teaching_goal":"本图解释什么",
    "layout_direction":"auto", "text_scale":1,
    "nodes":[{{"id":"safe_ascii_id", "label":"对象短名", "detail":"必要的数值或说明", "evidence":"精确教材原文子串"}}],
    "edges":[{{"id":"safe_ascii_relation_id", "source":"node_id", "target":"node_id", "label":"短关系名", "directed":true, "evidence":"精确教材原文子串"}}]
  }}
}}

约束：
- 旁白 3–6 句，总体适合 20–40 秒；只讲选中的一个知识点。
- 图必须表达教材明确支持的对象、操作、输入输出关系。可以做直接算术推导，但要在旁白中说明这是计算结果。
- 每个节点和关系都必须有来源原文支持；evidence 字段必须逐字复制自下方原文，不要改标点或补词。
- 节点 ID 与关系 ID 使用唯一、稳定的 ASCII 字符串；节点 label/detail 简洁可读。
- 每句旁白必须直接引用本次规划中的一个或多个关注对象：focus_ids 只能使用 node:<节点ID> 或 edge:<关系ID>；多个阶段应体现关注目标变化。
- 不要用整图 ID 充当关注目标，不要安排高亮时间；程序会把 focus_ids 与实测音频句级 cue 对接。
- 不输出额外字段、解释、SVG、HTML 或 Markdown。

教材来源：{SOURCE_LOCATOR}
原文：
{source}
"""


def request_plan(source: str) -> dict:
    prompt = build_prompt(source)
    (RUN / "plan-prompt.txt").write_text(prompt, encoding="utf-8")
    attempts = []
    raw = chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        model=MODEL,
        temperature=0.15,
        max_tokens=6000,
        timeout=240,
    )
    attempts.append(raw)
    (RUN / "model-response-1.txt").write_text(raw, encoding="utf-8")
    try:
        plan = parse_json(raw)
        validate_plan(plan, source)
        save_json(RUN / "joint-plan.json", plan)
        return plan
    except Exception as first_error:
        correction = (
            "请只根据上一条回复和已给原文，修复以下可定位的结构/引用错误；不要改写未受影响的教学内容，"
            "不要猜测引用。仍只输出同一形状的完整 JSON。\n"
            f"错误：{type(first_error).__name__}: {first_error}\n"
            f"原回复：\n{raw}\n"
        )
        retry = chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt},
             {"role": "assistant", "content": raw}, {"role": "user", "content": correction}],
            model=MODEL,
            temperature=0.0,
            max_tokens=6000,
            timeout=240,
        )
        attempts.append(retry)
        (RUN / "model-response-2.txt").write_text(retry, encoding="utf-8")
        plan = parse_json(retry)
        validate_plan(plan, source)
        save_json(RUN / "joint-plan.json", plan)
        return plan


def render_graph(plan: dict) -> tuple[Path, dict]:
    spec = plan["visual"]
    compiled_spec, detached_nodes = renderer_compatible_spec(spec, (RUN / "source-page-1.txt").read_text(encoding="utf-8"))
    save_json(RUN / "joint-plan.json", plan)
    save_json(RUN / "compiled-visual-spec.json", compiled_spec)
    svg = render_visual(compiled_spec, theme_id=THEME)
    root = ET.fromstring(svg)
    for note in detached_nodes:
        footer = [element for element in root.iter()
                  if element.get("data-visual-object") == "constraint"]
        if len(footer) != 1:
            raise ValueError("existing flow footer did not materialize exactly once")
        footer[0].set("data-node-id", note["id"])
    edge_map = {f"{edge['source']}:{edge['target']}": edge["id"] for edge in spec["edges"]}
    observed = set()
    for element in root.iter():
        old = element.get("data-edge")
        if old in edge_map:
            relation_id = edge_map[old]
            element.set("data-relationship-id", relation_id)
            element.set("data-edge", relation_id)
            observed.add(relation_id)
    if observed != set(edge_map.values()):
        raise ValueError(f"renderer edge identity mismatch: expected={sorted(edge_map.values())}, observed={sorted(observed)}")
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    svg = ET.tostring(root, encoding="unicode")
    svg_path = RUN / "planned-visual.svg"
    svg_path.write_text(svg, encoding="utf-8")
    digest = hashlib.sha256(svg_path.read_bytes()).hexdigest()
    targets = {}
    for node in spec["nodes"]:
        target = visual_node_animation_id(ELEMENT_ID, node["id"])
        targets[target] = {"node_id": node["id"], "label": node["label"],
                           "description": " ".join([node["label"], node.get("detail", "")]).strip()}
    for edge in spec["edges"]:
        target = visual_node_animation_id(ELEMENT_ID, "edge:" + edge["id"])
        targets[target] = {"edge_id": edge["id"],
                           "description": f"{edge['source']} → {edge['target']}: {edge.get('label', '')}"}
    element = {"id": ELEMENT_ID, "type": "image", "description": spec["title"],
               "src": svg_path.name, "visual_asset_sha256": digest,
               "visual_object_targets": targets}
    # Exercise the same exact-hash SVG target inlining used by production pages.
    inlined = _inline_reviewed_visual_objects(svg_path, element, scope=SEGMENT_ID)
    (RUN / "inline-target-proof.svg").write_text(inlined, encoding="utf-8")
    return svg_path, element


def main() -> None:
    source_result = extract_pdf_pages_info(str(SOURCE_PDF), 1, 1)
    source = source_result["text"]
    if len(source) < 300:
        raise ValueError("PDF page text extraction unexpectedly short")
    (RUN / "source-page-1.txt").write_text(source, encoding="utf-8")
    source_meta = {
        "source_pdf": str(SOURCE_PDF),
        "source_sha256": hashlib.sha256(SOURCE_PDF.read_bytes()).hexdigest(),
        "pages": [1], "extractor": "pipeline.parser.extract_pdf_pages_info",
        "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "characters": len(source), "model": MODEL,
    }
    save_json(RUN / "source-manifest.json", source_meta)
    # The offline audit already used the single allowed structural correction.
    # Reuse its exact second reply here; do not make another model call.
    saved_retry = RUN / "model-response-2.txt"
    if saved_retry.is_file():
        plan = parse_json(saved_retry.read_text(encoding="utf-8"))
        validate_plan(plan, source)
        save_json(RUN / "joint-plan.json", plan)
    else:
        plan = request_plan(source)
    svg_path, visual_element = render_graph(plan)

    segment = {
        "id": SEGMENT_ID,
        "visual_type": "concept",
        "narration": "".join(cue["text"] for cue in plan["narration"]),
        "elements": [
            {"id": "spike-heading", "type": "heading", "text": plan["visual"]["title"]},
            visual_element,
        ],
    }
    image_map = {f"{SEGMENT_ID}:{ELEMENT_ID}": str(svg_path)}

    audio_dir = RUN / "audio"
    if (audio_dir / "sentence_cues.json").is_file() and (audio_dir / "s1.wav").is_file():
        generated = {"audio_files": [audio_dir / "s1.wav"],
                     "sentence_cues_path": audio_dir / "sentence_cues.json"}
    else:
        generated = generate_sentence_audio(
            [[cue["text"] for cue in plan["narration"]]],
            output_dir=audio_dir,
            backend="sapi",
            voice="Microsoft Huihui Desktop",
            rate="+0%",
            segment_ids=[SEGMENT_ID],
        )
    cues_data = json.loads(Path(generated["sentence_cues_path"]).read_text(encoding="utf-8"))
    cue_group = cues_data["segments"][0]
    cue_rows = cue_group["cues"]
    duration = round(float(cue_group["duration_sec"]), 3)
    if len(cue_rows) != len(plan["narration"]):
        raise ValueError("measured cue count does not match the jointly planned narration")
    segment["audio_duration_sec"] = duration
    target_ids = {}
    for target_id, data in visual_element["visual_object_targets"].items():
        if "node_id" in data:
            target_ids["node:" + data["node_id"]] = target_id
        else:
            target_ids["edge:" + data["edge_id"]] = target_id
    timeline = [{"event_id": "plan-show-graph", "target": ELEMENT_ID, "action": "show",
                 "effect": "fadeIn", "at_sec": 0.0, "duration_ms": 250}]
    for planned, cue in zip(plan["narration"], cue_rows, strict=True):
        unresolved = [target for target in planned["focus_ids"] if target not in target_ids]
        if unresolved:
            raise ValueError(f"generated focus targets missing after rendering: {unresolved}")
        targets = [target_ids[target] for target in planned["focus_ids"]]
        hold = max(0.6, min(float(cue["duration_sec"]) - 0.1, 4.5))
        timeline.append({
            "event_id": f"joint-plan-{planned['id']}",
            "target": ",".join(targets),
            "action": "focus",
            "effect": "fadeIn",
            "at_sec": float(cue["start_sec"]),
            "duration_ms": 0,
            "hold_sec": round(hold, 3),
            "planned_sentence_id": planned["id"],
            "measured_sentence_id": cue["sentence_id"],
        })
    segment["timeline"] = timeline
    segment["spike_focus_map"] = [
        {"planned_sentence_id": item["id"], "sentence_text": item["text"],
         "generated_focus_ids": item["focus_ids"],
         "runtime_targets": [target_ids[target] for target in item["focus_ids"]],
         "measured_cue": cue}
        for item, cue in zip(plan["narration"], cue_rows, strict=True)
    ]
    save_json(RUN / "page-segment.json", segment)
    save_json(RUN / "focus-map.json", segment["spike_focus_map"])
    save_json(RUN / "measured-cues.json", cues_data)

    static_html = course_page_html(segment, image_map, theme=THEME, static=True)
    dynamic_html = course_page_html(segment, image_map, theme=THEME, static=False)
    (RUN / "page-static.html").write_text(static_html, encoding="utf-8")
    (RUN / "page-runtime.html").write_text(dynamic_html, encoding="utf-8")
    layout_dir = RUN / "layout-check"
    layout_dir.mkdir(parents=True, exist_ok=True)
    (layout_dir / "static.html").write_text(static_html, encoding="utf-8")
    layout_report = validate_local_page(
        segment, image_map, output_dir=layout_dir, browser="msedge",
        review_policy="development",
    )
    save_json(RUN / "layout-report.json", layout_report)

    storyboard = {"lesson_title": plan["proposition"]["text"], "segments": [segment],
                  "metadata": {"source": SOURCE_LOCATOR, "spike": "joint-visual-plan-focus"}}
    subtitle_path = generate_srt(
        storyboard, RUN / "spike.srt", sentence_cues=cues_data,
    )
    silent_path = RUN / "spike-silent.mp4"
    record_html_to_video(
        str((RUN / "page-runtime.html").resolve()), str(silent_path), duration=duration,
        fps=30, browser_channel="msedge", viewport_width=1920, viewport_height=1080,
        trace_path=str(RUN / "runtime-trace.json"),
    )
    final_path = RUN / "joint-planning-spike.mp4"
    mux_audio_video(silent_path, generated["audio_files"][0], final_path,
                    subtitle_path=subtitle_path)

    report = {
        "status": "video_generated",
        "source": source_meta,
        "model": MODEL,
        "narration_sentence_count": len(plan["narration"]),
        "measured_audio_duration_sec": duration,
        "video_duration_sec": get_audio_duration(str(generated["audio_files"][0])),
        "graph_nodes": [node["id"] for node in plan["visual"]["nodes"]],
        "graph_relationships": [edge["id"] for edge in plan["visual"]["edges"]],
        "generated_focus_maps": len(plan["narration"]),
        "visual_asset_sha256": visual_element["visual_asset_sha256"],
        "video_path": str(final_path.resolve()),
        "token_usage": "not exposed by the existing chat() wrapper",
    }
    save_json(RUN / "spike-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
