"""Generate auditable real-API relationship previews from existing narration.

This is a development preview, not a formal experiment or a full course smoke.
It invokes the same planner, compiler and renderer used by P0 auto visuals.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from textbook2video.pipeline.config import select_llm_config
from textbook2video.research.relationship_visuals import plan_relationship
from textbook2video.research.visual_synthesis import compile_visuals
from textbook2video.themes import load_theme


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--segments", default="2,4,5")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--theme", default="dark-blue-academic")
    parser.add_argument("--model", default="ecnu-plus")
    parser.add_argument("--layouts", help="Optional predeclared layout for each selected page")
    args = parser.parse_args()
    key, base, _ = select_llm_config()
    if not key or base.rstrip("/") != "https://chat.ecnu.edu.cn/open/api/v1":
        raise ValueError("preview requires configured school API credentials and endpoint")
    visual = load_theme(args.theme)["visual"]
    data = args.storyboard.read_bytes()
    board = json.loads(data)
    wanted = args.segments.split(",")
    hints = args.layouts.split(",") if args.layouts else [None] * len(wanted)
    if len(hints) != len(wanted):
        raise ValueError("one layout hint is required per requested segment")
    if len(wanted) != len(set(wanted)):
        raise ValueError("duplicate requested segment")
    selected = []
    for segment_id in wanted:
        matches = [s for s in board["segments"] if str(s["id"]) == segment_id]
        if len(matches) != 1:
            raise ValueError("each requested segment must resolve exactly once")
        selected.append(matches[0])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "RUNNING_DEVELOPMENT_PREVIEW",
        "model": args.model,
        "endpoint": base,
        "theme": args.theme,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_path": str(args.storyboard.resolve()),
        "attempts": [],
        "human_review": "NOT_REVIEWED",
        "pipeline_scope": "P0 planner/compiler; default course path unchanged",
    }
    destination = args.output_dir / "manifest.json"

    def save() -> None:
        destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            for ordinal, (segment, layout_hint) in enumerate(
                zip(selected, hints, strict=True), start=1
            ):
                case = args.output_dir / f"sample-{ordinal:02}"
                case.mkdir()
                # Use only pre-existing narration and visible storyboard text.
                # The page heading supplies the intended teaching focus.
                elements = segment.get("elements", [])
                goal = next((str(e["text"]) for e in elements if e.get("type") == "heading"), "")
                source_parts = [str(segment["narration"])]
                for element in elements:
                    if element.get("text"):
                        source_parts.append(str(element["text"]))
                    for field in ("items", "steps"):
                        source_parts.extend(
                            item for item in element.get(field, []) if isinstance(item, str)
                        )
                source = "\n".join(source_parts)
                (case / "source.txt").write_text(source, encoding="utf-8")
                record = {
                    "sample": case.name,
                    "segment_id": segment["id"],
                    "status": "PLANNING",
                    "predeclared_layout": layout_hint,
                }
                manifest["attempts"].append(record)
                save()
                print(f"Planning {case.name} with {args.model}...", flush=True)
                spec, _ = plan_relationship(
                    source,
                    model=args.model,
                    response_path=case / "model-response.txt",
                    teaching_goal=goal,
                    layout_hint=layout_hint,
                )
                spec["id"] = case.name
                (case / "visual_spec.json").write_text(
                    json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                asset_manifest = compile_visuals([spec], case / "compiled", theme_id=args.theme)
                asset = case / "compiled/assets" / f"{case.name}.svg"
                svg = asset.read_text(encoding="utf-8")
                markup = (
                    '<!doctype html><html lang="zh"><meta charset="utf-8">'
                    "<style>*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden}"
                    f"body{{background:linear-gradient({visual['background_gradient_top']},"
                    f"{visual['background_gradient_bottom']});"
                    f"color:{visual['text_color']};font-family:Microsoft YaHei,sans-serif}}"
                    "main{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);"
                    "width:min(100vw,177.7778vh);aspect-ratio:16/9;container-type:inline-size}"
                    "header{position:absolute;left:5%;top:6%;right:5%;border-left:5px solid "
                    f"{visual['accent']};padding-left:24px}}"
                    "p{font-size:1.25cqw;margin:0 0 14px;opacity:.8}"
                    "h1{font-size:2.65cqw;margin:0;line-height:1.25}"
                    "svg{position:absolute;top:22%;left:0;width:100%;height:auto}"
                    "footer{position:absolute;left:5%;bottom:2.5%;font-size:1cqw;opacity:.7}</style>"
                    "<main><header><p>数字素养 · 教学关系图</p>"
                    f"<h1>{html.escape(spec['title'])}</h1></header>"
                    f"{svg}<footer>学校 {html.escape(args.model)} 规划 · 确定性排版 · 待人工审阅"
                    "</footer></main></html>"
                )
                (case / "preview.html").write_text(markup, encoding="utf-8")
                record.update(
                    {
                        "status": "RENDERING",
                        "layout": spec["diagram"]["layout"],
                        "asset_manifest": str(asset_manifest.relative_to(args.output_dir)),
                    }
                )
                for width, height in ((1600, 900), (1366, 768)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto((case / "preview.html").resolve().as_uri())
                    page.evaluate("document.fonts.ready")
                    issues = page.evaluate("""() => {
                        const bad=[];
                        for(const text of document.querySelectorAll('svg text')) {
                            const r=text.getBoundingClientRect();
                            if(r.left<0||r.top<0||r.right>innerWidth+.5||r.bottom>innerHeight+.5)
                                bad.push({type:'viewport_text_overflow',text:text.textContent});
                            const node=text.closest('[data-node-id]');
                            if(node) {const b=node.querySelector('rect').getBoundingClientRect();
                                if(r.left<b.left||r.right>b.right||r.top<b.top||r.bottom>b.bottom)
                                    bad.push({type:'node_text_overflow',id:node.dataset.nodeId,text:text.textContent});}
                        }
                        return bad;
                    }""")
                    record[f"layout_issues_{width}"] = issues
                    page.screenshot(path=str(case / f"preview-{width}.png"))
                    if issues:
                        raise ValueError(f"rendered text overflow in {case.name} at {width}")
                record["status"] = "RENDERED_PENDING_HUMAN_REVIEW"
                save()
                print(f"Rendered {case.name}: {record['layout']}", flush=True)
            cards = "".join(
                f"<section><h2>第 {r['segment_id']} 页 · {html.escape(r['layout'])}</h2>"
                f'<a href="{r["sample"]}/preview.html">'
                f'<img src="{r["sample"]}/preview-1600.png"></a></section>'
                for r in manifest["attempts"]
            )
            (args.output_dir / "index.html").write_text(
                '<!doctype html><html lang="zh"><meta charset="utf-8">'
                "<title>学校API自动关系图</title>"
                "<style>body{font-family:Microsoft YaHei;background:#eef2f7;"
                "color:#182940;margin:24px}"
                "section{margin:24px 0}h2{font-size:22px}"
                "img{width:100%;display:block;border-radius:12px}</style>"
                "<h1>学校 API 自动规划 → 程序排版</h1>"
                "<p>真实模型输出，未逐图手改；静态开发预览，待人工审阅。</p>" + cards,
                encoding="utf-8",
            )
            page.set_viewport_size({"width": 1200, "height": 1000})
            page.goto((args.output_dir / "index.html").resolve().as_uri())
            page.screenshot(path=str(args.output_dir / "contact-sheet.png"), full_page=True)
            browser.close()
        manifest["status"] = "RENDERED_PENDING_HUMAN_REVIEW"
    except Exception as error:
        manifest["status"] = "FAILED_PRESERVED"
        manifest["error_type"] = type(error).__name__
        if isinstance(error, ValueError):
            manifest["validation_error"] = str(error)[:240]
        if manifest["attempts"]:
            manifest["attempts"][-1]["status"] = "FAILED_PRESERVED"
        save()
        print(f"Preview failed: {type(error).__name__}; see preserved attempt.", flush=True)
        return 1
    save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
