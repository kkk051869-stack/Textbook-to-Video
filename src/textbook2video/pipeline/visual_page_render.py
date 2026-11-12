"""Use the production page renderer and shell for visual-tool page previews."""

from __future__ import annotations

from pathlib import Path

from textbook2video.variants.layouts import (
    VISUAL_MIN_TEXT_PX,
    has_visual_support,
    image_text_slot,
)

# Temporary product policy: retain measurements without blocking on visual size.
VISUAL_SIZE_WARNINGS = {
    'unreadable_svg_text',
    'visual_exceeds_mixed_page_budget',
    'visual_group_exceeds_mixed_page_budget',
}
DEVELOPMENT_LAYOUT_WARNINGS = {
    'viewport_clipping', 'ancestor_clipping', 'content_overflow_split_required',
    'unreadable_body_text', 'svg_glyph_clipping', 'unmeasured_nested_svg',
}

class UnsupportedCoursePage(ValueError):
    """This page needs the production renderer's fallback."""


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
        raise UnsupportedCoursePage("course page is not supported by the deterministic renderer")
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


def validate_local_page(
    segment, images, *, output_dir: Path, browser: str, review_policy: str = 'strict',
) -> dict:
    """Static geometry/glyph admission, separate from runtime animation evidence."""
    if review_policy not in {'strict', 'development'}:
        raise ValueError('review policy must be strict or development')
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
                    const inlineSvgTextMin={}, inlineSvgRects={};
                    for(const svg of document.querySelectorAll('.slide svg')){
                        const id=svg.closest('[data-anim-id]')?.dataset.animId;
                        if(!id) continue;
                        const r=svg.getBoundingClientRect();
                        inlineSvgRects[id]={width:r.width,height:r.height};
                        const sizes=[...svg.querySelectorAll('text')].map(t=>{
                            const m=t.getScreenCTM();
                            return m ? parseFloat(getComputedStyle(t).fontSize)*Math.hypot(m.a,m.b) : 0;
                        });
                        if(sizes.length) inlineSvgTextMin[id]=Math.min(...sizes);
                    }
                    const rect = e => {const r=e.getBoundingClientRect();
                        return {x:r.x,y:r.y,width:r.width,height:r.height};};
                    const style=getComputedStyle(fs);
                    const components=[...document.querySelectorAll('[data-anim-id]')]
                        .filter(e=>e.closest('.t2v-content-box'))
                        .map(e=>({id:e.dataset.animId,...rect(e)}));
                    const visualGroup=document.querySelector(
                        '.t2v-image-text-classic > div:first-child')
                        ||document.querySelector('.t2v-image-gallery-row');
                    return {issues,ids,images,inlineSvgTextMin,inlineSvgRects,
                        visual_group:visualGroup?rect(visualGroup):null,capacity:{
                        image_text_gap:parseFloat(getComputedStyle(document.documentElement)
                            .getPropertyValue('--t2v-image-text-gap'))||46,
                        available:rect(box),natural_height:fs.scrollHeight,
                        overflow_height:Math.max(0,fs.scrollHeight-box.clientHeight),
                        vertical_padding:parseFloat(style.paddingTop)+parseFloat(style.paddingBottom),
                        horizontal_padding:parseFloat(style.paddingLeft)+parseFloat(style.paddingRight),
                        gap:parseFloat(style.rowGap)||0,components}};
                }""")
                mixed = (bool(segment.get('local_visual_operations')) or
                         segment.get('visual_timing_rebuild', {}).get('page_strategy')
                         == 'preserve-components-with-acquisition') and has_visual_support(
                             segment['elements'])
                enforce_slot = mixed and segment.get('local_visual_layout', 'auto') in {
                    'auto', 'classic'}
                slot = image_text_slot(result.get('capacity', {})) if enforce_slot else None
                if slot:
                    result['visual_slot'] = slot
                    group = result.get('visual_group')
                    if group and group['width'] > slot['max_width_px'] + 2:
                        result['issues'].append({'type': 'visual_group_exceeds_mixed_page_budget',
                                                 'actual': group, 'budget': slot})
                for element in segment["elements"]:
                    ident = element["id"]
                    if slot and element.get('type') == 'image':
                        bounds = (result.get('inlineSvgRects', {}).get(ident)
                                  or result['images'].get(ident))
                        if bounds and (bounds['width'] > slot['max_width_px'] + 2
                                       or bounds['height'] > slot['max_height_px'] + 2):
                            result['issues'].append({'type': 'visual_exceeds_mixed_page_budget',
                                                     'id': ident, 'actual': bounds, 'budget': slot})
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
                        measured = result.get('inlineSvgTextMin', {}).get(ident, min(sizes, default=0))
                        result.setdefault('svg_text_min_px', {})[ident] = measured
                        source_min = min((t['font'] for t in glyph['texts']), default=0)
                        result.setdefault('capacity', {}).setdefault('svg_requirements', {})[ident] = {
                            'minimum_font_px': VISUAL_MIN_TEXT_PX, 'source_min_font': source_min,
                            'minimum_width': (glyph['width'] * VISUAL_MIN_TEXT_PX / source_min
                                              if source_min else None),
                            'minimum_height': (glyph['height'] * VISUAL_MIN_TEXT_PX / source_min
                                               if source_min else None),
                            'actual_font_px': measured,
                        }
                        if sizes and measured < VISUAL_MIN_TEXT_PX:
                            result["issues"].append({"type": "unreadable_svg_text", "id": ident,
                                                     "min_px": measured})
                for operation in segment.get("local_visual_operations", []):
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
                warning_types = VISUAL_SIZE_WARNINGS | (
                    DEVELOPMENT_LAYOUT_WARNINGS if review_policy == 'development' else set())
                result['warnings'] = [
                    issue for issue in result['issues'] if issue['type'] in warning_types
                ]
                result['issues'] = [
                    issue for issue in result['issues'] if issue['type'] not in warning_types
                ]
                screenshot = output_dir / f"static-{width}x{height}.png"
                page.screenshot(path=str(screenshot))
                reports.append({"viewport": [width, height], **result,
                                "screenshot": str(screenshot),
                                "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
        finally:
            instance.close()
    report = {"scope": "OFFLINE_STATIC_LAYOUT_NOT_ANIMATION_OR_SEMANTIC_ACCEPTANCE",
              "visual_size_policy": "WARNINGS_ONLY",
              "review_policy": review_policy,
              "passed": not network and all(not r["issues"] for r in reports),
              "blocked_network": network, "viewports": reports}
    with (output_dir / "layout.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return report


def measure_generation_capacity(segment, images, *, output_dir: Path, theme: str, browser: str):
    """Measure the unchanged page before generation; no hypothetical asset fit claim."""
    import json

    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / 'static.html').write_text(
        course_page_html(segment, images, theme=theme), encoding='utf-8')
    report = validate_local_page(segment, images, output_dir=output_dir, browser=browser)
    capacity = {
        'scope': 'MEASURED_ORIGINAL_PAGE_NOT_CANDIDATE_ADMISSION',
        'visual_size_policy': 'WARNINGS_ONLY',
        'minimum_svg_font_px': VISUAL_MIN_TEXT_PX,
        'interpretation': 'Produce an asset only. Original components and events are owned by the '
        'executor. Width and free height describe the current unchanged layout, not hard maximum '
        'asset dimensions. Existing components may reflow or use different spacing in another '
        'layout. Do not delete facts, shrink type or invent page splitting to satisfy it. '
        'The generated asset must still pass real dual-viewport page preflight. '
        'Do not echo capacity metadata in the VisualPlanV1 reply.',
        'original_page_passed': report['passed'],
        'viewports': [{
            'viewport': item['viewport'],
            'available': item.get('capacity', {}).get('available'),
            'original_components': item.get('capacity', {}).get('components', []),
            'stack_free_height': max(0, item['capacity']['available']['height']
                                     - item['capacity']['natural_height'])
            if item.get('capacity', {}).get('available') else None,
            'usable_width': max(0, item['capacity']['available']['width']
                                - item['capacity']['horizontal_padding'])
            if item.get('capacity', {}).get('available') else None,
        } for item in report['viewports']],
    }
    if has_visual_support(segment.get('elements', [])):
        slots = [image_text_slot(v.get('capacity', {})) for v in report['viewports']]
        capacity['visual_slot'] = {
            'layout': 'classic', 'minimum_text_px': VISUAL_MIN_TEXT_PX,
            'max_width_px': min(s['max_width_px'] for s in slots),
            'max_height_px': min(s['max_height_px'] for s in slots),
        }
        capacity['interpretation'] += (
            ' visual_slot reserves the image column beside existing teaching content. '
            'Plan for this display size, not the fullscreen asset preview. '
            'Use concise source-faithful labels and avoid redundant detail already expressed '
            'on the page. Never delete needed '
            'relations or shrink type to fit. If it cannot fit, keep required content intact; '
            'page preflight will report adjustment/splitting. Do not invent new response fields. '
            'The executor will not silently switch a mixed page to a fullscreen figure.'
        )
    capacity['interpretation'] += (
        ' Temporary policy: all size and minimum visual font measurements above are '
        'recommendations only, not admission limits. Size/font findings are warnings '
        'and do not require a split. Other content and asset checks still apply.'
    )
    (output_dir / 'generation-capacity.json').write_text(
        json.dumps(capacity, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['passed']:
        raise ValueError(f'original page requires layout adjustment before generation; see {output_dir}')
    return capacity


def select_local_page_layout(
    segment, images, *, output_dir: Path, theme: str, browser: str,
    review_policy: str = 'strict',
):
    """Try existing layouts without changing content, events, or type sizes."""
    import json
    import shutil
    from copy import deepcopy

    output_dir.mkdir(parents=True, exist_ok=False)
    trials = []
    selected = None
    requested = segment.get('local_visual_layout', 'auto')
    if requested != 'auto':
        choices = [(requested, False), (requested, True)]
    elif has_visual_support(segment.get('elements', [])):
        choices = [('classic', False), ('classic', True)]
    else:
        choices = [('auto', False), ('full_stack', False), ('full_stack', True)]
    for index, (layout, compact) in enumerate(choices):
        candidate = deepcopy(segment)
        candidate['local_visual_layout'] = layout
        candidate['local_visual_compact_spacing'] = compact
        directory = output_dir / f'trial-{index}'
        directory.mkdir()
        (directory / 'static.html').write_text(
            course_page_html(candidate, images, theme=theme), encoding='utf-8')
        report = validate_local_page(candidate, images, output_dir=directory, browser=browser,
                                     review_policy=review_policy)
        trials.append({'layout': layout, 'compact_spacing': compact,
                       'passed': report['passed'], 'report': str(directory / 'layout.json')})
        if report['passed']:
            selected = index
            break
    (output_dir / 'capacity.json').write_text(json.dumps({
        'scope': 'LAYOUT_ONLY_NOT_ASSET_ADMISSION', 'trials': trials,
        'selected': selected, 'action': 'use_existing_layout' if selected is not None
        else 'adjust_or_split_required',
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    # Keep every failed trial. The chosen preview is also easy to locate.
    chosen = output_dir / f'trial-{selected if selected is not None else 0}'
    for path in chosen.iterdir():
        if path.is_file():
            shutil.copy2(path, output_dir / path.name)
    if selected is None:
        raise ValueError(f'local composition needs layout adjustment or page split; see {output_dir}')
    assert candidate['elements'] == segment['elements']
    assert candidate.get('timeline') == segment.get('timeline')
    assert candidate.get('narration') == segment.get('narration')
    return candidate


def validate_local_runtime(segment, *, output_dir: Path, browser: str) -> dict:
    """Exercise the existing controller; never substitute static full-show evidence."""
    import json

    from playwright.sync_api import sync_playwright

    from textbook2video.animation_gen import build_slide_timelines

    expected = build_slide_timelines([segment])[0]
    reports, network = [], []
    with sync_playwright() as p:
        instance = p.chromium.launch(channel=browser, headless=True)
        try:
            for width, height in ((1600, 900), (1366, 768)):
                page = instance.new_page(viewport={"width": width, "height": height})

                def block(route):
                    network.append(route.request.url.split("?", 1)[0])
                    route.abort()

                page.route("http://**/*", block)
                page.route("https://**/*", block)
                item = {"viewport": [width, height], "issues": [], "trace": []}
                try:
                    page.goto((output_dir / "runtime.html").resolve().as_uri())
                    page.evaluate("document.fonts.ready")
                    page.wait_for_function(
                        "Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)")
                    page.wait_for_function(
                        "n=>window.exportAnimationTrace&&window.exportAnimationTrace().length>=n"
                        "&&window.exportAnimationTrace().every(e=>e.status!=='scheduled')",
                        arg=len(expected), timeout=30000)
                    page.wait_for_timeout(max((e.get("duration_ms", 0) for e in expected),
                                              default=0) + 100)
                    trace = page.evaluate("window.exportAnimationTrace()")
                    item["trace"] = trace
                    if len(trace) != len(expected) or any(e["status"] != "executed" for e in trace):
                        item["issues"].append("compiled_events_not_executed")
                    fields = ("event_id", "target", "action", "effect", "duration_ms", "hold_ms")
                    wanted = {e["event_id"]: e for e in expected}
                    for e in trace:
                        planned = wanted.get(e["event_id"], {})
                        if (any(e.get(k) != planned.get(k) for k in fields)
                                or e.get("planned_ms") != planned.get("start_ms")):
                            item["issues"].append("runtime_event_differs_from_compiled_input")
                    for event in trace:
                        if page.locator(f'[data-anim-id="{event["target"]}"]').count() != 1:
                            item["issues"].append("event_target_missing_or_ambiguous")
                    item["images"] = page.evaluate("""() => Array.from(document.images).map(i=>({
                        loaded:i.complete&&i.naturalWidth>0, width:i.getBoundingClientRect().width,
                        height:i.getBoundingClientRect().height}))""")
                    if any(not i["loaded"] or i["width"] <= 0 or i["height"] <= 0
                           for i in item["images"]):
                        item["issues"].append("runtime_image_not_visible")
                    screenshot = output_dir / f"runtime-{width}x{height}.png"
                    page.screenshot(path=str(screenshot))
                    item["screenshot"] = str(screenshot)
                except Exception as exc:
                    item["issues"].append(type(exc).__name__)
                finally:
                    reports.append(item)
                    page.close()
        finally:
            instance.close()
    result = {"scope": "BROWSER_RUNTIME_NOT_FINAL_VIDEO_OR_ALIGNMENT",
              "compiled_events": expected, "viewports": reports, "blocked_network": network,
              "passed": not network and all(not r["issues"] for r in reports)}
    (output_dir / "runtime-checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
