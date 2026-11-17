"""Offline reproductions of current HTML state behavior, including known defects.

Passing assertions document the existing behavior; they do not endorse it.
Keep generate(), merge_html() and validate_output() real. Replace rendering,
layout observations and repair providers with deterministic, browser-free probes.
"""

import json
import sys
from types import SimpleNamespace

import pytest

from textbook2video import animation_gen as animation
from textbook2video import template_renderer

CSS_PATCH = 'id="css-probe" style="font-size:12px"'
LLM_PATCH = "LLM-repaired-second-slide"


def layout_report(*failed):
    return {
        "slides": [{"index": i, "passed": i not in failed} for i in (1, 2)],
        "staticRisks": [],
    }


@pytest.fixture
def generation_probe(tmp_path, monkeypatch):
    storyboard = tmp_path / "lesson_storyboard.json"
    storyboard.write_text(json.dumps({
        "lesson_title": "Fixed input",
        "segments": [
            {"id": i, "visual_type": "text", "narration": f"Narration {i}.",
             "audio_duration_sec": i,
             "elements": [{"id": f"e{i}", "type": "text", "text": f"Text {i}"}],
             "animations": []}
            for i in (1, 2)
        ],
    }), encoding="utf-8")
    initial_storyboard = storyboard.read_bytes()
    probe = SimpleNamespace(
        output=tmp_path / "lesson-pipeline-dark-blue-academic.html",
        merged=[], validated=[], qa=[], repairs=[],
        real_qa=animation.run_layout_qa,
    )
    monkeypatch.setenv("T2V_SKIP_SVG", "1")
    monkeypatch.delenv("T2V_DISABLE_TEMPLATE_RENDERER", raising=False)
    monkeypatch.setattr(animation, "configure_console_output", lambda: None)
    monkeypatch.setattr(animation, "package_cjk_font", lambda _: {"font_asset_exists": False})

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected model, browser or repair call")

    def render(segment, index, *_args, **_kwargs):
        content = '<p id="css-probe">First slide</p>' if index == 0 else '<p>Second slide</p>'
        return f'<div class="slide">{content}</div>'

    monkeypatch.setattr(template_renderer, "render_slide", render)
    monkeypatch.setattr(animation, "generate_batch", forbidden)
    monkeypatch.setattr(animation, "generate_batch_slides", forbidden)
    monkeypatch.setattr(animation, "run_layout_qa", forbidden)
    monkeypatch.setattr(animation, "repair_single_slides", forbidden)
    monkeypatch.setattr(animation, "replace_failed_batches", forbidden)
    monkeypatch.setitem(sys.modules, "textbook2video.css_hotfix",
                        SimpleNamespace(apply_css_hotfixes=forbidden))

    real_merge = animation.merge_html
    real_validate = animation.validate_output

    def merge(**kwargs):
        html = real_merge(**kwargs)
        probe.merged.append(html)
        return html

    def validate(html, expected_slides, **kwargs):
        disk = probe.output.read_text(encoding="utf-8")
        result = real_validate(html, expected_slides, **kwargs)
        probe.validated.append((html, disk, result))
        return result

    def run(attempts=1):
        path = animation.generate(
            storyboard, output_dir=tmp_path, theme_id="dark-blue-academic",
            skip_image_gen=True, layout_repair_attempts=attempts,
        )
        assert path == probe.output and path.is_file()
        assert storyboard.read_bytes() == initial_storyboard
        assert len(probe.validated) == 1
        return path.read_text(encoding="utf-8")

    probe.run = run
    monkeypatch.setattr(animation, "merge_html", merge)
    monkeypatch.setattr(animation, "validate_output", validate)
    return probe


def install_css_patch(monkeypatch, probe):
    def hotfix(path, _report, **_kwargs):
        probe.repairs.append("css")
        html = path.read_text(encoding="utf-8")
        assert CSS_PATCH not in html
        path.write_text(html.replace('id="css-probe"', CSS_PATCH), encoding="utf-8")
        return 1

    monkeypatch.setitem(sys.modules, "textbook2video.css_hotfix",
                        SimpleNamespace(apply_css_hotfixes=hotfix))


def test_initial_qa_pass_validates_delivered_html(generation_probe, monkeypatch):
    probe = generation_probe
    monkeypatch.setattr(animation, "run_layout_qa", lambda *_a, **_k: (True, layout_report()))
    disk = probe.run()
    validated, at_validation, result = probe.validated[0]
    assert disk == at_validation == validated == probe.merged[0]
    assert result["all_pass"] is True


def test_css_success_keeps_disk_patch_but_validates_old_html(generation_probe, monkeypatch):
    """Reproduce stale final_html after the CSS-success early break."""
    probe = generation_probe
    install_css_patch(monkeypatch, probe)

    def qa(path, *_args, **_kwargs):
        html = path.read_text(encoding="utf-8")
        probe.qa.append(html)
        return (True, layout_report()) if CSS_PATCH in html else (False, layout_report(1))

    monkeypatch.setattr(animation, "run_layout_qa", qa)
    disk = probe.run()
    validated, at_validation, _result = probe.validated[0]
    assert len(probe.qa) == 2 and probe.repairs == ["css"]
    assert CSS_PATCH in disk and disk == at_validation == probe.qa[-1]
    assert CSS_PATCH not in validated
    assert validated == probe.merged[0] != disk


@pytest.mark.parametrize("route", ["single", "batch"])
def test_partial_css_is_lost_when_llm_rebuilds_other_slide(
    generation_probe, monkeypatch, route, capsys,
):
    """Repair slide 2 only; rebuilding nevertheless drops the CSS repair on slide 1."""
    probe = generation_probe
    install_css_patch(monkeypatch, probe)

    def qa(path, *_args, **_kwargs):
        html = path.read_text(encoding="utf-8")
        failed = ([] if CSS_PATCH in html else [1]) + ([] if LLM_PATCH in html else [2])
        probe.qa.append((html, failed))
        return not failed, layout_report(*failed)

    def repair_single(**kwargs):
        probe.repairs.append("single")
        assert animation.failing_slide_indices(kwargs["report"]) == [2]
        if route == "batch":
            return False
        kwargs["batch_slide_lists"][0][1] = f'<div class="slide">{LLM_PATCH}</div>'
        return True

    def repair_batch(**kwargs):
        probe.repairs.append("batch")
        kwargs["batch_slide_lists"][0][1] = f'<div class="slide">{LLM_PATCH}</div>'
        return True

    monkeypatch.setattr(animation, "run_layout_qa", qa)
    monkeypatch.setattr(animation, "repair_single_slides", repair_single)
    monkeypatch.setattr(animation, "replace_failed_batches", repair_batch)
    disk = probe.run()
    assert [failed for _html, failed in probe.qa] == [[1, 2], [2], [1]]
    assert CSS_PATCH in probe.qa[1][0] and CSS_PATCH not in disk
    assert LLM_PATCH in disk
    assert probe.repairs == (["css", "single"] if route == "single"
                             else ["css", "single", "batch"])
    assert len(probe.merged) == 2
    assert disk == probe.validated[0][0] == probe.validated[0][1]
    assert "已达到布局修复上限" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["rejected", "exception"])
def test_partial_css_survives_failed_llm_but_validation_is_stale(
    generation_probe, monkeypatch, failure, capsys,
):
    probe = generation_probe
    install_css_patch(monkeypatch, probe)
    monkeypatch.setattr(animation, "run_layout_qa", lambda *_a, **_k: (False, layout_report(2)))

    def repair(**_kwargs):
        probe.repairs.append("llm")
        if failure == "exception":
            raise RuntimeError("offline repair failure")
        return False

    monkeypatch.setattr(animation, "repair_single_slides", repair)
    monkeypatch.setattr(animation, "replace_failed_batches", repair)
    disk = probe.run()
    assert probe.repairs == ["css", "llm", "llm"]
    assert len(probe.merged) == 1 and CSS_PATCH in disk
    assert disk == probe.validated[0][1] != probe.validated[0][0]
    assert "没有可接受的修复输出" in capsys.readouterr().out


def test_exhausted_budget_returns_html_despite_layout_failure(
    generation_probe, monkeypatch, capsys,
):
    probe = generation_probe
    monkeypatch.setattr(animation, "run_layout_qa", lambda *_a, **_k: (False, layout_report(1)))
    disk = probe.run(attempts=0)
    assert disk == probe.validated[0][0] == probe.validated[0][1]
    assert probe.validated[0][2]["all_pass"] is True
    output = capsys.readouterr().out
    assert "已达到布局修复上限 (0)，保留最后一次结果" in output
    assert "布局自检通过" not in output
    # The final summary describes structural checks, despite the failed layout gate.
    assert "所有校验通过" in output


def test_missing_checker_is_not_run_but_generate_logs_qa_pass(
    generation_probe, monkeypatch, tmp_path, capsys,
):
    probe = generation_probe
    package = tmp_path / "missing-checker-repo" / "src" / "textbook2video"
    monkeypatch.setattr(animation, "_PACKAGE_DIR", package)
    checker = package.parents[1] / "scripts" / "check_layout.py"
    assert not checker.exists()

    def forbidden_subprocess(*_args, **_kwargs):
        pytest.fail("Missing checker must not launch a subprocess")

    def real_qa(*args, **kwargs):
        result = probe.real_qa(*args, **kwargs)
        probe.qa.append(result)
        return result

    monkeypatch.setattr(animation.subprocess, "run", forbidden_subprocess)
    monkeypatch.setattr(animation, "run_layout_qa", real_qa)
    disk = probe.run()
    assert probe.qa == [(True, {})]
    assert not animation.layout_report_path(probe.output, 0).exists()
    assert disk == probe.validated[0][0] == probe.validated[0][1]
    output = capsys.readouterr().out
    assert "未找到布局自检脚本" in output
    assert "布局自检通过" in output
