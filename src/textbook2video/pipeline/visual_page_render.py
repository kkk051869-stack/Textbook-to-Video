"""Use the production page renderer and shell for visual-tool page previews."""

from __future__ import annotations

from pathlib import Path


def course_page_html(
    segment: dict, images: dict[str, str], *, theme: str, static: bool = True,
) -> str:
    import base64
    import mimetypes

    from textbook2video.animation_gen import (
        build_slide_timelines,
        inject_generated_images,
        merge_html,
    )
    from textbook2video.template_renderer import render_slide
    from textbook2video.themes import load_theme

    template_dir = Path(__file__).resolve().parents[1] / "templates"
    selected_theme = load_theme(theme)
    rendered = render_slide(segment, 0, set(images), selected_theme.get("preferred_variants"))
    if rendered is None:
        raise ValueError("course page is not supported by the deterministic renderer")
    uris = {}
    for key, path in images.items():
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        uris[key] = f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()
    rendered = inject_generated_images([rendered], [segment], uris)[0]
    shell = (template_dir / "base-template.html").read_text(encoding="utf-8")
    if not static:
        # Interactive offline previews start immediately, unlike the recorder's
        # deferred hook. Make existing timelines available before initialization.
        shell = shell.replace(
            "{{JS_CONTROLLER}}",
            "var slideTimelines = {{SLIDE_TIMELINES}};"
            "var slideDurations = {{SLIDE_DURATIONS}};\n{{JS_CONTROLLER}}",
        )
    return merge_html(
        [rendered],
        [".anim{opacity:1!important;transform:none!important;animation:none!important}"
         if static else ""],
        shell,
        (template_dir / "base.css").read_text(encoding="utf-8"),
        (template_dir / "slide-controller.js").read_text(encoding="utf-8"),
        "",
        [int(segment.get("audio_duration_sec", 10) * 1000)],
        "课程视觉开发预览",
        theme=selected_theme,
        timelines=build_slide_timelines([segment]) if not static else None,
    )


def validate_local_page(segment, images, *, output_dir: Path, browser: str) -> dict:
    """Static geometry/glyph admission, separate from runtime animation evidence."""
    import hashlib
    import json

    from playwright.sync_api import sync_playwright

    from textbook2video.pipeline.visual_page_plan import visible_facts

    reports, glyphs, network = [], {}, []
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel=browser, headless=True)
        try:
            context = instance.new_context()

            def block_transport(route):
                network.append(route.request.url.split("?", 1)[0])
                route.abort()

            context.route("https://**/*", block_transport)
            context.route("http://**/*", block_transport)
            page = context.new_page()
            page.add_init_script("window.__t2vDeferPlayback=true")
            # Inspect source glyphs at unit SVG scale, then project onto each
            # actual contained image rectangle in the composed page.
            for element in segment["elements"]:
                key = f"{segment['id']}:{element['id']}"
                if element.get("type") != "image" or Path(images[key]).suffix.lower() != ".svg":
                    continue
                page.set_content(Path(images[key]).read_text(encoding="utf-8"))
                page.evaluate("document.fonts.ready")
                glyphs[element["id"]] = page.evaluate("""() => {
                    const svg=document.querySelector('svg'), v=svg.viewBox.baseVal;
                    svg.style.width=v.width+'px';svg.style.height=v.height+'px';
                    const issues=[], texts=[];
                    for(const t of svg.querySelectorAll('text')) {
                        const b=t.getBBox(), m=t.getCTM(), s=getComputedStyle(t);
                        if(s.display==='none'||s.visibility==='hidden'||+s.opacity===0) continue;
                        const p=new DOMPoint(b.x,b.y).matrixTransform(m);
                        const q=new DOMPoint(b.x+b.width,b.y+b.height).matrixTransform(m);
                        if(p.x< -1||p.y< -1||q.x>v.width+1||q.y>v.height+1)
                            issues.push({type:'svg_glyph_clipping',text:t.textContent});
                        texts.push({text:t.textContent,
                            object_id:t.closest('[data-node-id]')?.dataset.nodeId,
                            font:parseFloat(s.fontSize)*Math.hypot(m.a,m.b)});
                    }
                    if(svg.querySelector('image,foreignObject'))
                        issues.push({type:'unmeasured_nested_svg'});
                    return {width:v.width,height:v.height,texts,issues};
                }""")
            for width, height in ((1600, 900), (1366, 768)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto((output_dir / "static.html").as_uri())
                page.evaluate("document.fonts.ready")
                page.wait_for_function("Array.from(document.images).every(i=>i.complete)")
                page.wait_for_timeout(150)
                result = page.evaluate("""() => {
                    const issues=[], ids={}, images={};
                    const box=document.querySelector('.t2v-content-box');
                    const fs=document.querySelector('.fit-scale');
                    if(!box||!fs) return {issues:[{type:'unsupported_local_layout'}],ids,images};
                    if(fs.scrollHeight>box.clientHeight+2)
                        issues.push({type:'content_overflow_split_required'});
                    function inspect(r, el, label) {
                        if(r.width<1||r.height<1||r.left<-.5||r.top<-.5||
                           r.right>innerWidth+.5||r.bottom>innerHeight+.5)
                            issues.push({type:'viewport_clipping',label});
                        for(let a=el.parentElement;a;a=a.parentElement){
                            const s=getComputedStyle(a), b=a.getBoundingClientRect();
                            if((/(hidden|clip|scroll|auto)/.test(s.overflowX)&&(r.left<b.left-1||r.right>b.right+1))||
                               (/(hidden|clip|scroll|auto)/.test(s.overflowY)&&(r.top<b.top-1||r.bottom>b.bottom+1)))
                                issues.push({type:'ancestor_clipping',label});
                        }
                    }
                    for(const el of document.querySelectorAll('.slide [data-anim-id]')){
                        ids[el.dataset.animId]=(ids[el.dataset.animId]||0)+1;
                        inspect(el.getBoundingClientRect(),el,el.dataset.animId);
                    }
                    const walker=document.createTreeWalker(
                        document.querySelector('.slide'),NodeFilter.SHOW_TEXT);
                    while(walker.nextNode()){
                        const t=walker.currentNode;
                        if(!t.textContent.trim()||t.parentElement.closest('svg,script,style'))
                            continue;
                        const r=document.createRange();r.selectNodeContents(t);
                        for(const b of r.getClientRects())
                            inspect(b,t.parentElement,t.textContent.slice(0,40));
                        if(parseFloat(getComputedStyle(t.parentElement).fontSize)<12)
                            issues.push({type:'unreadable_body_text'});
                    }
                    for(const img of document.querySelectorAll('.slide img')){
                        const r=img.getBoundingClientRect();
                        const id=img.closest('[data-anim-id]')?.dataset.animId;
                        images[id]={width:r.width,height:r.height};
                        if(!img.naturalWidth) issues.push({type:'missing_pixels',id});
                        inspect(r,img,id);
                    }
                    return {issues,ids,images};
                }""")
                for element in segment["elements"]:
                    ident = element["id"]
                    if result["ids"].get(ident) != 1:
                        result["issues"].append(
                            {"type": "missing_or_duplicate_element", "id": ident}
                        )
                    if element.get("type") not in {"image", "focus_box", "callout"}:
                        locator = page.locator(f'[data-anim-id="{ident}"]')
                        displayed = "".join(locator.all_text_contents()).split()
                        displayed = "".join(displayed)
                        for fact in visible_facts(element):
                            if "".join(fact.split()) not in displayed:
                                result["issues"].append(
                                    {"type": "missing_displayed_content", "id": ident, "fact": fact}
                                )
                    if ident in glyphs:
                        glyph = glyphs[ident]
                        result["issues"].extend(glyph["issues"])
                        bounds = result["images"].get(ident, {"width": 0, "height": 0})
                        scale = min(bounds["width"] / glyph["width"],
                                    bounds["height"] / glyph["height"])
                        sizes = [t["font"] * scale for t in glyph["texts"]]
                        result.setdefault("svg_text_min_px", {})[ident] = min(sizes, default=0)
                        if sizes and min(sizes) < 16:
                            result["issues"].append({"type": "unreadable_svg_text", "id": ident,
                                                     "min_px": min(sizes)})
                for operation in segment["local_visual_operations"]:
                    for proof in operation["coverage"]:
                        texts = glyphs[operation["element_id"]]["texts"]
                        refs = proof["visual_refs"]
                        asset_id = operation["asset_id"]
                        text = "".join(
                            t["text"] for t in texts if asset_id in refs
                            or f"{asset_id}:{t.get('object_id')}" in refs
                        )
                        for fact in proof["fact_quotes"]:
                            if "".join(fact.split()) not in "".join(text.split()):
                                result["issues"].append(
                                    {"type": "replacement_fact_not_visible", "fact": fact}
                                )
                screenshot = output_dir / f"static-{width}x{height}.png"
                page.screenshot(path=str(screenshot))
                reports.append({"viewport": [width, height], **result,
                                "screenshot": str(screenshot),
                                "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
        finally:
            instance.close()
    report = {"scope": "OFFLINE_STATIC_LAYOUT_NOT_ANIMATION_OR_SEMANTIC_ACCEPTANCE",
              "passed": not network and all(not r["issues"] for r in reports),
              "blocked_network": network, "viewports": reports}
    with (output_dir / "layout.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report
