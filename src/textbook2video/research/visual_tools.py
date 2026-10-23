"""Executable create/revise/compose tools and bounded screenshot review loop.

School gateways need not implement native function calling: the model emits a
JSON tool envelope, and the same validated dispatcher executes it. All model
requests, raw responses, rejected revisions and screenshots remain inspectable.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_images, chat_with_system
from textbook2video.research.relationship_visuals import PLANNER_RULES, validate_relationship
from textbook2video.research.visual_composition import execution_assets, render_composition
from textbook2video.research.visual_content_map import materialize_content_map
from textbook2video.research.visual_edits import apply_changes
from textbook2video.research.visual_grammar import CATALOG, GRAMMAR_VERSION, validate_visual
from textbook2video.research.visual_source_refs import materialize_source_refs, source_units
from textbook2video.research.visual_synthesis import IMAGE_KINDS, compile_visuals
from textbook2video.themes import load_theme

TOOLS = [
    {
        "name": "create",
        "arguments": {
            "visuals": "1-6 source-grounded VisualSpecs",
            "content_map": {
                "element-id": {
                    "decision": "support|represented|unsupported_in_source|irrelevant_to_goal",
                    "source_ref": "source ID(s), required when represented",
                    "visual_refs": ["visual-id or visual-id:node-id"],
                    "reason": "explain disposition; do not silently remove unique facts",
                },
            },
        },
    },
    {
        "name": "revise",
        "arguments": {
            "parent": "previous revision directory",
            "reason": "specific review feedback",
            "visuals": "replacement VisualSpecs preserving stable IDs where possible",
            "changes": "instead: [{op:add|replace|remove,path:/visuals/0/...,value:...}]",
        },
    },
    {
        "name": "compose",
        "arguments": {
            "visuals": "same source-grounded VisualSpecs as create",
            "content_map": "same element disposition contract as create",
            "visual_ids": "ordered IDs from this revision",
            "axis": "single|horizontal|vertical",
            "horizontal_free": "boolean",
            "vertical_free": "boolean",
        },
    },
]
PLAN_RULES = """Select the representation from teaching_goal and source, not image description.
Only source_text is evidence; instructions/descriptions are NOT source evidence.
Use none for decorative or irrelevant pictures. A person's portrait needs an explicit
source-supported teaching purpose. Do not invent nodes, numbers, edges or causal claims.
Return {tool:"create",arguments:{visuals:[...]}}. Use one main visual, or split complex
content into up to six ordered panels. Each panel must have a short title, teaching_goal,
id (safe identifier), and kind. Precise structure goes to SVG, never image generation.
For graph kinds use schema_version=teaching-visual-v2, nodes=[{id,label,detail?,source_ref}],
edges=[{source,target,label?,directed?,source_ref}]. Select source IDs, never retype quotes.
Use 2-8 nodes per panel, at most four stages and three nodes per layer. Keep labels short.
comparison has exactly two nodes and no edges; details show shared comparison dimensions.
chart/proportion: series=[{label,value,evidence}], unit, chart_type=bar|line.
table: rows=[[header,...],[cell,...]], evidence. formula/code: content,evidence.
Every v2 spec needs title and teaching_goal. Keep code indentation and exact formulas.
Every relationship spec also needs a top-level title and teaching_goal.
diagram.constraint_source_ref selects source IDs for constraint_evidence; the displayed
constraint itself must still be a short exact excerpt, never a generated conclusion.
For multiple panels, every visual needs narration_span: an exact consecutive substring
of narration_text. In panel order these spans must concatenate to narration_text exactly,
including whitespace/punctuation, with no omissions or added words. Plan before TTS.
Choose a peer network as kind=network. Use the optional three-column relationship
component only when the source actually supports its input/middle/output structure.
Do not force unrelated source statements or conditions into three sequential stages.
Do not replace a structural explanation with a generic word map. When multiplicity
is the teaching point (each member holds an instance), depict multiple members and
their instances, not one box labelled "multiple members". Give peers equal capabilities
unless the source explicitly assigns different roles.
scene/object/historical/person/photo/texture need prompt,source_ref,teaching_goal; use only
when concrete imagery is necessary. none needs source_ref and teaching_goal too.
Do not write SVG/HTML/CSS or coordinates. Never silently convert an invalid kind to flow.
For relationship use kind=relationship (NEVER kind=split_merge/one_way/peer_network).
Its diagram.version must be teaching-relationship-v1; omit top-level schema_version,
nodes and edges. Every diagram edge ALSO needs an exact source evidence quote.
An edge's action/label must be supported by that quote; shared words are not entailment.
If page_context is supplied, include arguments.content_map, an object keyed by EVERY
page_context element ID. Each value is {decision,source_ref,visual_refs,reason}.
decision=support retains a short text element; keep at most two such supports.
decision=represented replaces an element with the visual: source_ref is REQUIRED,
visual_refs points to the visual/node IDs, and reason explains ALL its original facts.
decision=unsupported_in_source or irrelevant_to_goal omits it with an explicit reason.
Do not write page_plan, fact_quotes or source_evidence on create: the executor compiles
the chosen decisions, inventories every original fact, and materializes exact source quotes.
Do not remove unique source information to make a page fit.
Never mark a unique supported fact as redundant merely to save space.
Prefer source_ref:"source-001" (or a list of source IDs) instead of retyping evidence.
Only select IDs from source_units. The tool materializes exact quotes automatically.
This applies to nodes, edges, image/none specs and coverage entries. Do not also write
evidence/source_evidence when using source_ref. Coverage fact_quotes may be omitted:
the tool inventories ALL original visible strings from page_context automatically;
you still must supply each element's decision, visual_refs and reason.
irrelevant_to_goal is for adjacent subtopics or decorative assets, even when true
elsewhere in the textbook. Explain the scope mismatch; never drop the teaching goal's
unique supported facts under this label. The screenshot reviewer must assess it.
For a paired composition, use tool=compose with visuals, content_map, visual_ids,
axis=horizontal|vertical and the matching horizontal_free/vertical_free=true.
Alternatively create/revise may include composition={visual_ids,axis,horizontal_free,
vertical_free}. Every visual must be included exactly once. Pairing requires NO retained
body supports. Labels must remain at least 16px in the actual course page; if they
would shrink below that, use separate panels instead. Do not declare space free when
body elements occupy it. Composition is rendered and screenshot-reviewed, not a plan only.
On REVISE, prefer tool=revise, arguments={changes:[...]} for small corrections.
changes is an ordered JSON-pointer patch to previous_candidate, using add/replace/remove.
Prefer stable-ID array selectors, e.g. /page_plan/coverage/@e2/source_ref or
/visuals/@main/nodes/@node-id/label. @ selects exactly one item's id or element_id.
JSON patch add to an array INSERTS a new item; it never updates the existing item.
Use replace for existing nodes/fields, add only for a genuinely new field/item.
Every graph node must have a source-supported edge; never leave ledger copies isolated.
Coverage targets are visual-id or visual-id:node-id, not visual-id:constraint.
An element ID e8 is NOT array index 8; never infer numeric indices from IDs.
Only /visuals, /page_plan, /composition and /content_map may be changed.
Use /content_map/e2/source_ref if the previous candidate still has compact content_map.
Do not also send full visuals
or page_plan. Example: {op:"replace",path:"/visuals/0/nodes/1/label",value:"new label"}.
If changing source_ref, remove its old evidence/source_evidence too, otherwise the exact
quote conflict check will reject it. The executor supplies parent/reason automatically.
All unchanged fields remain intact; edited results still need full source and screenshot QA.
"""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _json(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        if not exc.msg.startswith("Invalid control character"):
            raise
        # Preserve literal newlines/tabs in string values. Do not guess missing
        # braces, invent a tool call or edit any semantic value.
        value = json.loads(cleaned, strict=False)
    if not isinstance(value, dict):
        raise ValueError("tool response must be an object")
    return value


def parse_tool_envelope(raw: str) -> tuple[dict, list[str]]:
    envelope = _json(raw)
    if envelope.get("tool") not in {"create", "revise", "compose"}:
        raise ValueError("model must call create/revise/compose")
    changes = []
    if "arguments" not in envelope:
        fields = {key: value for key, value in envelope.items() if key != "tool"}
        allowed = {"visuals", "content_map", "page_plan", "composition", "visual_ids",
                   "axis", "horizontal_free", "vertical_free", "changes", "parent", "reason"}
        if not fields or not set(fields).issubset(allowed):
            raise ValueError(
                "tool call needs an arguments object containing visual tool parameters"
            )
        envelope = {"tool": envelope["tool"], "arguments": fields}
        changes.append("Wrapped explicit top-level tool parameters in arguments; values unchanged")
    if not isinstance(envelope["arguments"], dict):
        raise ValueError("tool arguments must be an object")
    return envelope, changes


def revision_edit_base(parent: Path) -> dict:
    if (parent / "revision.json").exists():
        verify_revision(parent)
    else:
        verify_failure(parent)
    candidate = parent / "request.json"
    if not candidate.exists():
        candidate = parent / "raw_tool_request.json"
    base = (
        json.loads(candidate.read_text(encoding="utf-8"))["arguments"]
        if candidate.exists() else None
    )
    if base is not None and "changes" not in base:
        return base
    snapshot = parent / "edit_base.json"
    if snapshot.exists():
        failure = json.loads((parent / "failure.json").read_text(encoding="utf-8"))
        base = json.loads(snapshot.read_text(encoding="utf-8"))
        if digest(base) != failure.get("edit_base_sha256"):
            raise ValueError("failed patch edit base hash drift")
        return base
    raise ValueError("parent has no resolved visual arguments; send a full replacement")


def expand_revision_changes(arguments: dict) -> dict:
    if "changes" not in arguments:
        return deepcopy(arguments)
    if not arguments.get("parent"):
        raise ValueError("local changes need a parent revision")
    return apply_changes(revision_edit_base(Path(arguments["parent"])), arguments)


def compose(
    visual_ids: list[str],
    *,
    axis: str = "single",
    horizontal_free: bool = False,
    vertical_free: bool = False,
) -> dict:
    """Space must be free along the requested double-image direction."""
    if not visual_ids or len(set(visual_ids)) != len(visual_ids):
        raise ValueError("composition needs unique visual IDs")
    if axis not in {"single", "horizontal", "vertical"}:
        raise ValueError("unsupported composition axis")
    if axis == "single":
        return {"axis": axis, "pages": [[i] for i in visual_ids], "primary_per_page": 1}
    if len(visual_ids) != 2:
        raise ValueError("a two-image composition requires exactly two images")
    if not (horizontal_free if axis == "horizontal" else vertical_free):
        raise ValueError("two images require free space along their composition axis")
    return {"axis": axis, "pages": [visual_ids], "primary_per_page": 1}


def dispatch(
    tool: str,
    arguments: dict,
    *,
    source: str,
    output_dir: Path,
    theme: str = "dark-blue-academic",
    browser: str = "msedge",
    render: bool = True,
    allow_images: bool = True,
    page_context: list[dict] | None = None,
    narration_text: str | None = None,
) -> Path | dict:
    if tool not in {"create", "revise", "compose"}:
        raise ValueError("unknown visual tool")
    parent = None
    if tool == "revise":
        parent_dir = Path(arguments["parent"])
        parent_source = json.loads((parent_dir / "source.json").read_text(encoding="utf-8"))
        parent_path = parent_dir / "revision.json"
        if parent_path.exists():
            verify_revision(parent_dir)
        parent = (json.loads(parent_path.read_text(encoding="utf-8"))
                  if parent_path.exists() else verify_failure(parent_dir))
        if parent["source_sha256"] != digest(source) or parent_source["source_text"] != source:
            raise ValueError("revision cannot change the source")
        if not str(arguments.get("reason", "")).strip():
            raise ValueError("revision needs a reason")
    output_dir.mkdir(parents=True, exist_ok=False)
    _save(output_dir / "source.json", {"source_text": source, "sha256": digest(source)})
    _save(output_dir / "raw_tool_request.json", {"tool": tool, "arguments": arguments})
    edit_base_sha256 = None
    try:
        if "changes" in arguments:
            if tool != "revise":
                raise ValueError("local changes are only supported by revise")
            edit_base = revision_edit_base(Path(arguments["parent"]))
            edit_base_sha256 = digest(edit_base)
            _save(output_dir / "edit_base.json", edit_base)
            arguments = apply_changes(edit_base, arguments)
        arguments, map_changes = materialize_content_map(arguments, page_context)
        arguments, normalizations = materialize_source_refs(arguments, source, page_context)
        normalizations = map_changes + normalizations
        specs = deepcopy(arguments.get("visuals"))
        if not isinstance(specs, list) or not 1 <= len(specs) <= 6:
            raise ValueError("create/revise requires 1-6 visual panels")
        if len(specs) > 1 and any(spec.get("kind") == "none" for spec in specs):
            raise ValueError("none must be a single abstention, not an omitted sequence panel")
        if len(specs) == 1 and "page_plan" in specs[0]:
            nested_plan = specs[0].pop("page_plan")
            if arguments.get("page_plan") is not None and arguments["page_plan"] != nested_plan:
                raise ValueError("conflicting page plans in arguments and visual")
            arguments = {**arguments, "page_plan": nested_plan}
            normalizations.append(
                "Moved single-panel page_plan to tool arguments; semantics unchanged"
            )
        for spec in specs:
            if (
                page_context is not None and spec.get("kind") != "none"
                and not str(spec.get("title") or "").strip()
            ):
                raise ValueError(
                    f"visual {spec.get('id')!r} needs a nonempty top-level title; "
                    "add /visuals/@visual-id/title before rendering the course page"
                )
        context_snapshot = deepcopy(page_context)
        for element in context_snapshot or []:
            if element.get("source_image_path"):
                image_path = Path(element["source_image_path"])
                element["source_image_sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
        _save(
            output_dir / "request.json",
            {
                "tool": tool,
                "arguments": arguments,
                "theme": theme,
                "page_context": context_snapshot,
                "narration_text": narration_text,
            },
        )
        if len(specs) > 1 and narration_text is not None:
            spans = [spec.get("narration_span") for spec in specs]
            if (
                any(not isinstance(span, str) or not span for span in spans)
                or "".join(spans) != narration_text
            ):
                raise ValueError(
                    "panel narration_span values must partition narration_text exactly"
                )
        if page_context is not None and any(s.get("kind") != "none" for s in specs):
            from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan

            if not arguments.get("page_plan"):
                raise ValueError("arguments.page_plan is required as a sibling of visuals")
            apply_visual_page_plan(
                {"elements": deepcopy(page_context)},
                "__primary__",
                arguments.get("page_plan"),
                visual_specs=specs,
                source_text=source,
            )
        ids = set()
        for spec in specs:
            ident = spec.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident):
                raise ValueError("visual IDs must be safe stable identifiers")
            if ident in ids:
                raise ValueError("duplicate visual ID")
            ids.add(ident)
            if spec.get("kind") == "relationship":
                if spec.get("schema_version") or "nodes" in spec or "edges" in spec:
                    raise ValueError("relationship nodes/edges belong only inside diagram")
                validate_relationship(spec, source)
                for edge in spec["diagram"]["edges"]:
                    if not edge.get("evidence") or edge["evidence"] not in source:
                        raise ValueError("relationship edges need exact source evidence")
            elif spec.get("kind") in IMAGE_KINDS | {"none"}:
                if not spec.get("teaching_goal") or not spec.get("evidence"):
                    raise ValueError("images/abstentions need a teaching goal and evidence")
                if spec["evidence"] not in source:
                    raise ValueError("image evidence must be an exact source excerpt")
                if spec["kind"] in IMAGE_KINDS and not allow_images:
                    raise ValueError("image generation disabled for this run")
            else:
                validate_visual(spec, source)
        _save(output_dir / "specs.json", specs)
        manifest_path = compile_visuals(
            specs,
            output_dir / "compiled",
            theme_id=theme,
            revision_of=(Path(arguments["parent"]) / "compiled/visual_assets.json")
            if parent and (Path(arguments["parent"]) / "compiled/visual_assets.json").exists()
            else None,
        )
        composition_args = arguments.get("composition")
        if tool == "compose":
            composition_args = {
                key: arguments[key]
                for key in ("visual_ids", "axis", "horizontal_free", "vertical_free")
                if key in arguments
            }
        composition_args = composition_args or {"visual_ids": [s["id"] for s in specs]}
        composition = compose(**composition_args)
        flattened = [ident for group in composition["pages"] for ident in group]
        if set(flattened) != ids:
            raise ValueError("composition must include every visual exactly once")
        if len(specs) > 1 and narration_text is not None:
            by_id = {spec["id"]: spec for spec in specs}
            if "".join(by_id[ident]["narration_span"] for ident in flattened) != narration_text:
                raise ValueError("composition order must preserve narration_text verbatim")
        rendered_assets = render_composition(
            output_dir, composition, page_plan=arguments.get("page_plan")
        )
        revision = {
            "tool": tool,
            "source_sha256": digest(source),
            "spec_sha256": digest(specs),
            "theme": theme,
            "reason": arguments.get("reason", "initial creation"),
            "parent": str(Path(arguments["parent"]).resolve()) if parent else None,
            "parent_sha256": digest(parent) if parent else None,
            "composition": composition,
            "execution_assets_sha256": digest(rendered_assets),
            "page_plan": arguments.get("page_plan"),
            "normalizations": normalizations,
            "manifest": str(manifest_path.resolve()),
            "status": "COMPILED_PENDING_REVIEW",
            "human_review": "NOT_REVIEWED",
            "edit_base_sha256": edit_base_sha256,
        }
        if render:
            revision["geometry"] = preview_revision(output_dir, browser=browser)
        revision["integrity_version"] = "visual-revision-v2"
        revision["raw_tool_request_sha256"] = digest(
            json.loads((output_dir / "raw_tool_request.json").read_text(encoding="utf-8"))
        )
        revision["request_sha256"] = digest(
            json.loads((output_dir / "request.json").read_text(encoding="utf-8"))
        )
        revision["execution_sha256"] = digest(revision)
        _save(output_dir / "revision.json", revision)
        return output_dir / "revision.json"
    except Exception as exc:
        _save(
            output_dir / "failure.json",
            {
                "status": "FAILED_PRESERVED",
                "error_type": type(exc).__name__,
                "error": str(exc)
                if isinstance(exc, (ValueError, FileNotFoundError))
                else "tool failure",
                "edit_base_sha256": edit_base_sha256,
                "parent": str(Path(arguments["parent"]).resolve()) if parent else None,
                "parent_sha256": digest(parent) if parent else None,
            },
        )
        raise


def preview_revision(directory: Path, *, browser: str = "msedge") -> list[dict]:
    from playwright.sync_api import sync_playwright

    manifest = json.loads((directory / "compiled/visual_assets.json").read_text(encoding="utf-8"))
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    # The compilation inherits the course theme; screenshots use the same colors.
    first_asset = next((a for a in manifest["assets"] if a.get("theme_id")), {})
    theme = request.get("theme", first_asset.get("theme_id", "dark-blue-academic"))
    colors = load_theme(theme)["visual"]
    reports = []
    with sync_playwright() as pw:
        instance = pw.chromium.launch(channel=browser, headless=True)
        try:
            page = instance.new_page()
            for asset in execution_assets(directory):
                if not asset.get("filename"):
                    continue
                path = directory / "compiled/assets" / asset["filename"]
                svg = (
                    path.read_text(encoding="utf-8")
                    if path.suffix == ".svg"
                    else (
                        f'<img src="{path.resolve().as_uri()}" '
                        'style="width:100%;height:100%;object-fit:contain">'
                    )
                )
                markup = (
                    '<!doctype html><html lang="zh"><meta charset="utf-8"><style>'
                    "*{box-sizing:border-box}body{margin:0;overflow:hidden;"
                    f"background:{colors.get('background_gradient_top', colors.get('background'))};"
                    f"color:{colors['text_color']};"
                    "font-family:Microsoft YaHei,sans-serif}"
                    "main{width:min(100vw,177.7778vh);aspect-ratio:16/9;position:absolute;"
                    "left:50%;top:50%;transform:translate(-50%,-50%);container-type:inline-size}"
                    "h1{position:absolute;top:3%;left:4%;right:4%;font-size:2.7cqw;margin:0}"
                    ".visual{position:absolute;left:1%;right:1%;top:17%;bottom:3%}"
                    "svg{width:100%;height:100%}</style><main>"
                    f"<h1>{html.escape(asset['spec'].get('title', ''))}</h1>"
                    f'<div class="visual">{svg}</div></main></html>'
                )
                name = asset["id"]
                if request.get("page_context") is not None:
                    from textbook2video.pipeline.visual_page_plan import apply_visual_page_plan
                    from textbook2video.pipeline.visual_page_render import course_page_html

                    context = deepcopy(request["page_context"])
                    primary_id = "__visual_tool_primary__"
                    if any(e.get("id") == primary_id for e in context):
                        raise ValueError("reserved visual preview element ID")
                    segment = {
                        "id": "preview",
                        "visual_type": "illustration",
                        "narration": "preview",
                        "elements": [
                            {
                                "id": "__visual_tool_heading__",
                                "type": "heading",
                                "text": asset["spec"]["title"],
                            },
                            *context,
                            {
                                "id": primary_id,
                                "type": "image",
                                "description": asset["spec"]["title"],
                                "visual_brief_role": "EXPLANATORY_DIAGRAM",
                                "visual_tools_run": "development-preview",
                            },
                        ],
                    }
                    apply_visual_page_plan(segment, primary_id, request["arguments"]["page_plan"])
                    markup = course_page_html(
                        segment,
                        {f"preview:{primary_id}": str(path.resolve())},
                        theme=theme,
                    )
                preview = directory / f"{name}.html"
                with preview.open("x", encoding="utf-8") as stream:
                    stream.write(markup)
                for width, height in ((1600, 900), (1366, 768)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(preview.resolve().as_uri())
                    page.evaluate("document.fonts.ready")
                    if request.get("page_context") is not None:
                        page.wait_for_timeout(300)
                    issues = page.evaluate("""() => {
                        const issues=[];
                        for(const t of document.querySelectorAll('svg text')) {
                            const r=t.getBoundingClientRect();
                            if(r.left<0||r.top<0||r.right>innerWidth+.5
                                ||r.bottom>innerHeight+.5)
                                issues.push({type:'text_overflow',text:t.textContent});
                            const node=t.closest('[data-node-id]');
                            if(node){const b=node.querySelector('rect').getBoundingClientRect();
                                if(r.left<b.left-1||r.right>b.right+1
                                    ||r.top<b.top-1||r.bottom>b.bottom+1)
                                    issues.push({type:'node_text_overflow',
                                        id:node.dataset.nodeId});}
                            if(r.height<13) issues.push({type:'unreadable_text',
                                text:t.textContent});
                        }
                        return issues;
                    }""")
                    if request.get("page_context") is not None:
                        bounds = page.locator(".t2v-image-surface img").bounding_box()
                        if bounds is None or bounds["width"] < 780 or bounds["height"] < 480:
                            issues.append({"type": "course_image_too_small", "bounds": bounds})
                        if bounds and (
                            bounds["x"] < 0
                            or bounds["y"] < 0
                            or bounds["x"] + bounds["width"] > width + 0.5
                            or bounds["y"] + bounds["height"] > height + 0.5
                        ):
                            issues.append({"type": "course_image_overflow", "bounds": bounds})
                        issues.extend(
                            page.locator(".t2v-image-surface img").evaluate("""img => {
                            const a=img.getBoundingClientRect(), issues=[];
                            for(let el=img.parentElement;el;el=el.parentElement){
                                const s=getComputedStyle(el), b=el.getBoundingClientRect();
                                const clipsX=/(hidden|clip|auto|scroll)/.test(s.overflowX);
                                const clipsY=/(hidden|clip|auto|scroll)/.test(s.overflowY);
                                if((clipsX&&(a.left<b.left-1||a.right>b.right+1))||
                                   (clipsY&&(a.top<b.top-1||a.bottom>b.bottom+1)))
                                    issues.push({type:'ancestor_image_clipping',
                                                 ancestor:el.className});
                            }
                            return issues;
                        }""")
                        )
                    screenshot = directory / f"{name}-{width}.png"
                    page.screenshot(path=str(screenshot))
                    reports.append(
                        {
                            "visual_id": name,
                            "viewport": [width, height],
                            "screenshot": str(screenshot.resolve()),
                            "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                            "issues": issues,
                        }
                    )
        finally:
            instance.close()
    _save(directory / "geometry.json", reports)
    return reports


def review_revision(directory: Path, *, model: str, timeout: float = 120) -> dict:
    verify_revision(directory)
    source = json.loads((directory / "source.json").read_text(encoding="utf-8"))["source_text"]
    specs = json.loads((directory / "specs.json").read_text(encoding="utf-8"))
    geometry = json.loads((directory / "geometry.json").read_text(encoding="utf-8"))
    revision = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    if geometry != revision["geometry"]:
        raise ValueError("geometry report hash drift")
    images = [r["screenshot"] for r in geometry]
    tool_request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    source_images = [
        {"element_id": element["id"], "path": element["source_image_path"]}
        for element in tool_request.get("page_context") or []
        if element.get("type") == "image" and element.get("source_image_path")
    ]
    images.extend(image["path"] for image in source_images)
    request = {
        "source_text": source,
        "specs": specs,
        "geometry": geometry,
        "page_context": tool_request.get("page_context"),
        "page_plan": revision.get("page_plan"),
        "composition": revision.get("composition"),
        "source_images": source_images,
        "narration_text": tool_request.get("narration_text"),
        "instructions": "Inspect actual screenshots and source. Check every edge/claim, teaching "
        "relevance, readable labels, crossings, whitespace, hierarchy and theme. "
        "Return JSON: {verdict:ACCEPT|REVISE|REJECT, scores:{accuracy:0..4,relevance:0..4,"
        "readability:0..4,composition:0..4}, issues:[{visual_id,issue,change}], reason:string}. "
        "Quote existence does not establish claim truth. Decorative images fail relevance. "
        "Do not claim human approval. Geometry failures require revision. "
        "Do not excuse unsupported action verbs or wrong edge direction as a simplification. "
        "ACCEPT is forbidden if any semantic weakness is known. In particular, a quote "
        "about a condition does not imply that condition is a process step or an input "
        "broadcast to every node. Judge each edge's claim, not merely node labels.",
    }
    if (revision.get("page_plan") or {}).get("replaces_element_ids"):
        request["coverage_contract"] = (
            "Also return coverage:[{element_id,verdict:covered|unsupported|irrelevant|missing,"
            "reason}]. "
            "Review every replaced element exactly once against ALL its original facts and source; "
            "missing unique information is a REVISE, even if the new diagram itself is accurate. "
            "Unsupported facts may be dropped only if the source does not entail them. "
            "Irrelevant facts/assets may be omitted only when outside this teaching goal; "
            "do not mistake missing core information for irrelevance."
        )
    _save(directory / "review-request.json", request)
    if images:
        raw = chat_with_images(
            json.dumps(request, ensure_ascii=False),
            images,
            model=model,
            temperature=0,
            max_tokens=2500,
            timeout=timeout,
        )
    else:
        request["review_scope"] = "Review whether abstaining loses needed explanatory content."
        raw = chat_with_system(
            json.dumps(request, ensure_ascii=False),
            model=model,
            temperature=0,
            max_tokens=2500,
            timeout=timeout,
        )
    return _save_review(directory, raw, geometry, model=model, has_images=bool(images))


def _save_review(
    directory: Path, raw: str, geometry: list, *, model: str, has_images: bool
) -> dict:
    with (directory / "review-response.txt").open("x", encoding="utf-8") as stream:
        stream.write(raw)
    report = _json(raw)
    revision = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    scores = report.get("scores", {})
    if (
        report.get("verdict") not in {"ACCEPT", "REVISE", "REJECT"}
        or set(scores) != {"accuracy", "relevance", "readability", "composition"}
        or any(type(v) is not int or not 0 <= v <= 4 for v in scores.values())
    ):
        raise ValueError("invalid visual review response")
    if not isinstance(report.get("issues"), list) or not report.get("reason"):
        raise ValueError("review requires specific issues and reason")
    page_plan = revision.get("page_plan") or {}
    replaced = set(page_plan.get("replaces_element_ids", []))
    if replaced:
        coverage = report.get("coverage", [])
        if (
            not isinstance(coverage, list)
            or len(coverage) != len(replaced)
            or {item.get("element_id") for item in coverage} != replaced
        ):
            raise ValueError("review must assess coverage of every replaced element")
        proofs = {item["element_id"]: item for item in page_plan["coverage"]}
        for item in coverage:
            expected = {
                "represented": "covered",
                "unsupported_in_source": "unsupported",
                "irrelevant_to_goal": "irrelevant",
            }[proofs[item["element_id"]]["decision"]]
            if item.get("verdict") != expected or not item.get("reason"):
                report["verdict"] = "REVISE"
    if any(r["issues"] for r in geometry) or min(scores.values()) < 3 or report["issues"]:
        if report["verdict"] == "ACCEPT":
            report["verdict"] = "REVISE"
    report.update(
        {
            "producer": "model-screenshot-review" if has_images else "model-abstention-review",
            "model": model,
            "human_review": "NOT_REVIEWED",
            "screenshot_hashes": [r["sha256"] for r in geometry],
            "execution_sha256": revision["execution_sha256"],
        }
    )
    _save(directory / "review.json", report)
    return report


def verify_failure(directory: Path, seen: set[str] | None = None) -> dict:
    seen = set() if seen is None else seen
    identity = str(directory.resolve()).casefold()
    if identity in seen:
        raise ValueError("cyclic revision parent")
    seen.add(identity)
    source = json.loads((directory / "source.json").read_text(encoding="utf-8"))
    failure = json.loads((directory / "failure.json").read_text(encoding="utf-8"))
    if digest(source["source_text"]) != source["sha256"]:
        raise ValueError("failed revision source hash drift")
    if failure.get("edit_base_sha256"):
        base = json.loads((directory / "edit_base.json").read_text(encoding="utf-8"))
        if digest(base) != failure["edit_base_sha256"]:
            raise ValueError("failed parent edit base hash drift")
    if failure.get("parent"):
        previous = Path(failure["parent"])
        path = previous / "revision.json"
        if path.exists():
            verify_revision(previous, seen)
            record = json.loads(path.read_text(encoding="utf-8"))
        else:
            record = verify_failure(previous, seen)
        if digest(record) != failure.get("parent_sha256"):
            raise ValueError("failed revision parent hash drift")
    return {"source_sha256": source["sha256"], "failure": failure}


def verify_revision(directory: Path, _seen: set[str] | None = None) -> None:
    """Refuse changed source, specs, pixels or compiled assets before consumption."""
    seen = set() if _seen is None else _seen
    identity = str(directory.resolve()).casefold()
    if identity in seen:
        raise ValueError("cyclic revision parent")
    seen.add(identity)
    revision = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    sealed = {k: v for k, v in revision.items() if k != "execution_sha256"}
    if revision.get("integrity_version") != "visual-revision-v2" or digest(sealed) != revision.get(
        "execution_sha256"
    ):
        raise ValueError("revision execution plan hash drift or legacy unsealed revision")
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    if digest(request) != revision["request_sha256"]:
        raise ValueError("revision request/page context hash drift")
    if revision.get("edit_base_sha256"):
        edit_base = json.loads((directory / "edit_base.json").read_text(encoding="utf-8"))
        if digest(edit_base) != revision["edit_base_sha256"]:
            raise ValueError("revision edit base hash drift")
    raw_request = json.loads((directory / "raw_tool_request.json").read_text(encoding="utf-8"))
    if digest(raw_request) != revision["raw_tool_request_sha256"]:
        raise ValueError("revision raw tool request hash drift")
    for element in request.get("page_context") or []:
        if element.get("source_image_path"):
            actual = hashlib.sha256(Path(element["source_image_path"]).read_bytes()).hexdigest()
            if actual != element.get("source_image_sha256"):
                raise ValueError("original source image hash drift")
    if revision.get("parent"):
        parent_dir = Path(revision["parent"])
        if parent_dir.resolve() == directory.resolve():
            raise ValueError("cyclic revision parent")
        parent_path = parent_dir / "revision.json"
        if parent_path.exists():
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            if parent.get("parent") == str(directory.resolve()):
                raise ValueError("cyclic revision parent")
            verify_revision(parent_dir, seen)
        else:
            parent = verify_failure(parent_dir, seen)
        if digest(parent) != revision["parent_sha256"]:
            raise ValueError("revision parent hash drift")
    source = json.loads((directory / "source.json").read_text(encoding="utf-8"))
    specs = json.loads((directory / "specs.json").read_text(encoding="utf-8"))
    if digest(source["source_text"]) != revision["source_sha256"]:
        raise ValueError("revision source hash drift")
    if digest(specs) != revision["spec_sha256"]:
        raise ValueError("revision spec hash drift")
    manifest = json.loads((directory / "compiled/visual_assets.json").read_text(encoding="utf-8"))
    if [a["spec"] for a in manifest["assets"]] != specs:
        raise ValueError("compiled manifest spec drift")
    for asset in manifest["assets"]:
        if asset.get("filename"):
            filename = asset["filename"]
            if Path(filename).name != filename:
                raise ValueError("asset path must be a filename")
            path = directory / "compiled/assets" / filename
            if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                raise ValueError("compiled asset hash drift")
    if (
        (directory / "composition_assets.json").exists()
        and "execution_assets_sha256" not in revision
    ):
        raise ValueError("composition assets require an execution seal")
    if "execution_assets_sha256" in revision:
        rendered_assets = execution_assets(directory)
        if digest(rendered_assets) != revision["execution_assets_sha256"]:
            raise ValueError("composition execution asset drift")
        for asset in rendered_assets:
            if asset.get("filename"):
                filename = asset["filename"]
                if Path(filename).name != filename:
                    raise ValueError("composition asset path must be a filename")
                path = directory / "compiled/assets" / filename
                if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                    raise ValueError("composition asset hash drift")
    for capture in revision.get("geometry", []):
        if (
            hashlib.sha256(Path(capture["screenshot"]).read_bytes()).hexdigest()
            != capture["sha256"]
        ):
            raise ValueError("review screenshot hash drift")
    review_path = directory / "review.json"
    if review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if review.get("execution_sha256") != revision["execution_sha256"]:
            raise ValueError("review is not bound to this execution plan")
        if review.get("screenshot_hashes") != [r["sha256"] for r in revision.get("geometry", [])]:
            raise ValueError("review screenshot binding drift")


def run_visual_agent(
    source: str,
    teaching_goal: str,
    output_dir: Path,
    *,
    model: str = "ecnu-plus",
    review_model: str | None = None,
    theme: str = "dark-blue-academic",
    browser: str = "msedge",
    max_iterations: int = 3,
    allow_images: bool = True,
    page_context: list[dict] | None = None,
    narration_text: str | None = None,
    planning_timeout: float = 180,
    review_timeout: float = 120,
) -> Path:
    """Bounded agent loop; revisions are immutable and failed attempts survive."""
    if not source.strip() or not teaching_goal.strip() or not 1 <= max_iterations <= 5:
        raise ValueError("agent needs source, teaching goal and 1-5 iterations")
    if not 1 <= planning_timeout <= 300 or not 1 <= review_timeout <= 300:
        raise ValueError("visual agent timeouts must be within 1-300 seconds")
    output_dir.mkdir(parents=True, exist_ok=False)
    history, seen = [], set()
    state: dict = {
        "status": "RUNNING",
        "source_sha256": digest(source),
        "model": model,
        "review_model": review_model or model,
        "max_iterations": max_iterations,
        "planning_timeout": planning_timeout,
        "review_timeout": review_timeout,
        "history": history,
        "accepted_revision": None,
        "human_review": "NOT_REVIEWED",
        "code_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                Path(__file__).with_name("visual_grammar.py"),
                Path(__file__).with_name("relationship_visuals.py"),
                Path(__file__).with_name("visual_synthesis.py"),
                Path(__file__).with_name("visual_source_refs.py"),
                Path(__file__).with_name("visual_composition.py"),
                Path(__file__).with_name("visual_graph_layout.py"),
                Path(__file__).with_name("visual_edits.py"),
                Path(__file__).with_name("visual_content_map.py"),
            )
        },
    }
    feedback = None
    incumbent_score = -1
    patience = 0
    try:
        for index in range(max_iterations):
            request = {
                "source_text": source,
                "source_units": source_units(source),
                "narration_text": narration_text if narration_text is not None else source,
                "teaching_goal": teaching_goal,
                "catalog": CATALOG,
                "optional_relationship_schema": PLANNER_RULES,
                "tools": TOOLS,
                "page_context": page_context,
                "feedback": feedback,
                "previous_candidate": (
                    history[-1].get("resolved_arguments", history[-1].get("arguments"))
                    if history else None
                ),
            }
            _save(output_dir / f"model-request-{index}.json", request)
            raw = chat_with_system(
                json.dumps(request, ensure_ascii=False),
                system_prompt=PLAN_RULES,
                model=model,
                temperature=0,
                max_tokens=6000,
                timeout=planning_timeout,
            )
            with (output_dir / f"model-response-{index}.txt").open("x", encoding="utf-8") as stream:
                stream.write(raw)
            try:
                envelope, envelope_changes = parse_tool_envelope(raw)
            except (ValueError, TypeError) as exc:
                directory = output_dir / f"revision-{index:02}"
                directory.mkdir(exist_ok=False)
                _save(directory / "source.json", {"source_text": source, "sha256": digest(source)})
                feedback = {
                    "verdict": "REVISE",
                    "validation_error": f"Return valid tool JSON: {exc}",
                }
                parse_failure = {"status": "FAILED_PRESERVED", **feedback}
                if index:
                    previous = output_dir / f"revision-{index - 1:02}"
                    previous_path = previous / "revision.json"
                    if previous_path.exists():
                        verify_revision(previous)
                        parent_record = json.loads(previous_path.read_text(encoding="utf-8"))
                    else:
                        parent_record = verify_failure(previous)
                    parse_failure.update(
                        parent=str(previous.resolve()), parent_sha256=digest(parent_record)
                    )
                _save(directory / "failure.json", parse_failure)
                history.append(
                    {
                        "revision": str(directory.resolve()),
                        "visuals": None,
                        "arguments": None,
                        "status": "FAILED_PRESERVED",
                        "error": feedback["validation_error"],
                    }
                )
                continue
            _save(output_dir / f"model-envelope-{index}.json", {
                "envelope": envelope, "normalizations": envelope_changes,
            })
            arguments = envelope["arguments"]
            directory = output_dir / f"revision-{index:02}"
            tool = "create" if index == 0 else "revise"
            if index:
                arguments.update(
                    {
                        "parent": str(output_dir / f"revision-{index - 1:02}"),
                        "reason": json.dumps(feedback, ensure_ascii=False),
                    }
                )
            if envelope["tool"] == "compose":
                arguments["composition"] = {
                    key: arguments[key]
                    for key in ("visual_ids", "axis", "horizontal_free", "vertical_free")
                    if key in arguments
                }
            specs = arguments.get("visuals")
            try:
                canonical_args, _ = materialize_content_map(
                    expand_revision_changes(arguments), page_context
                )
                canonical_args, _ = materialize_source_refs(canonical_args, source, page_context)
            except ValueError:
                canonical_args = arguments
            canonical_specs = deepcopy(canonical_args.get("visuals"))
            canonical_plan = canonical_args.get("page_plan")
            if isinstance(canonical_specs, list) and len(canonical_specs) == 1:
                nested_plan = canonical_specs[0].pop("page_plan", None)
                canonical_plan = canonical_plan if canonical_plan is not None else nested_plan
            fingerprint = digest(
                {
                    "visuals": canonical_specs,
                    "page_plan": canonical_plan,
                    "composition": canonical_args.get("composition"),
                    "content_map": canonical_args.get("content_map"),
                    "unresolved_changes": arguments.get("changes") if not canonical_specs else None,
                }
            )
            if fingerprint in seen:
                state["status"] = "STOPPED_REPEATED_STATE"
                _save(
                    output_dir / f"repeated-candidate-{index}.json",
                    {
                        "arguments": arguments,
                        "state_sha256": fingerprint,
                        "reason": "Canonical visuals, page plan and composition are unchanged",
                    },
                )
                break
            seen.add(fingerprint)
            entry = {
                "revision": str(directory.resolve()),
                "visuals": specs,
                "arguments": deepcopy(arguments),
                "spec_sha256": digest(canonical_specs),
                "state_sha256": fingerprint,
                "status": "ATTEMPTING",
            }
            history.append(entry)
            try:
                dispatch(
                    tool,
                    arguments,
                    source=source,
                    output_dir=directory,
                    theme=theme,
                    browser=browser,
                    allow_images=allow_images,
                    page_context=page_context,
                    narration_text=narration_text if narration_text is not None else source,
                )
                entry["resolved_arguments"] = json.loads(
                    (directory / "request.json").read_text(encoding="utf-8")
                )["arguments"]
                review = review_revision(
                    directory, model=review_model or model, timeout=review_timeout
                )
            except ValueError as exc:
                entry.update({"status": "FAILED_PRESERVED", "error": str(exc)})
                if (directory / "request.json").exists():
                    entry["resolved_arguments"] = json.loads(
                        (directory / "request.json").read_text(encoding="utf-8")
                    )["arguments"]
                elif (directory / "edit_base.json").exists():
                    entry["resolved_arguments"] = json.loads(
                        (directory / "edit_base.json").read_text(encoding="utf-8")
                    )
                feedback = {"verdict": "REVISE", "validation_error": str(exc)}
                continue
            entry.update(
                {"status": review["verdict"], "review": review, "review_sha256": digest(review)}
            )
            score = sum(review["scores"].values())
            patience = patience + 1 if score <= incumbent_score else 0
            incumbent_score = max(incumbent_score, score)
            if review["verdict"] == "ACCEPT":
                state.update(
                    {
                        "status": "MODEL_REVIEWED_PENDING_HUMAN",
                        "accepted_revision": str(directory.resolve()),
                    }
                )
                break
            if review["verdict"] == "REJECT" or patience >= 2:
                state["status"] = (
                    "STOPPED_REVIEW_REJECTED"
                    if review["verdict"] == "REJECT"
                    else "STOPPED_NO_IMPROVEMENT"
                )
                break
            feedback = review
        else:
            state["status"] = "STOPPED_ITERATION_BUDGET"
    except Exception as exc:
        state.update({"status": "FAILED_PRESERVED", "error_type": type(exc).__name__})
        raise
    finally:
        _save(output_dir / "run.json", state)
    return output_dir / "run.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=["catalog", "create", "revise", "compose", "run", "review"]
    )
    parser.add_argument("--request", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--goal", default="")
    parser.add_argument("--model", default="ecnu-plus")
    parser.add_argument("--theme", default="dark-blue-academic")
    args = parser.parse_args(argv)
    if args.operation == "catalog":
        result = {"tools": TOOLS, "kinds": CATALOG, "schema_version": GRAMMAR_VERSION}
    elif args.operation == "review":
        result = review_revision(args.output_dir, model=args.model)
    elif args.operation == "run":
        result = str(
            run_visual_agent(
                args.source.read_text(encoding="utf-8"),
                args.goal,
                args.output_dir,
                model=args.model,
                theme=args.theme,
            )
        )
    else:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        source = args.source.read_text(encoding="utf-8") if args.source else ""
        result = dispatch(
            args.operation, request, source=source, output_dir=args.output_dir, theme=args.theme
        )
        if isinstance(result, Path):
            result = str(result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
