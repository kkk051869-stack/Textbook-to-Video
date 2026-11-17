"""Offline behavior baselines for the legacy CLI and production builders."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from textbook2video import cli
from textbook2video.pipeline import orchestrator
from textbook2video.pipeline.timing import apply_timing


@pytest.mark.parametrize("entry", ["cli_pdf", "cli_docx", "builder_pdf", "builder_docx"])
@pytest.mark.parametrize("skip_tts,broken_duration", [(False, False), (True, False), (False, True)])
def test_generation_entry_contract(tmp_path, monkeypatch, entry, skip_tts, broken_duration):
    for key in ("T2V_TIMING_MODE", "T2V_SENTENCE_SYNC", "T2V_RESEARCH_GENERATION_V2"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("T2V_TTS_BACKEND", "edge")
    calls = []
    images = [{"id": "fig1", "filename": "figure.png", "description": "source figure"}]
    plan = {"knowledge_points": [{"id": "k1"}]}
    segments = ["First sentence.", "Second sentence."]
    original = {"metadata": {}, "total_slides": 2, "segments": [
        {"id": i, "narration": text, "elements": [{"id": "e1", "type": "text", "text": text}]}
        for i, text in enumerate(segments, 1)
    ]}

    def fake_plan(text, **kwargs):
        calls.append(("plan", text, kwargs))
        return copy.deepcopy(plan)

    def fake_script(text, **kwargs):
        calls.append(("script", text, kwargs))
        return list(segments)

    def fake_storyboard(texts, **kwargs):
        calls.append(("storyboard", texts, kwargs))
        return copy.deepcopy(original)

    def extract_pdf(path, lesson):
        calls.append(("pdf", path, lesson))
        return {"text": "source text", "title": "PDF title", "pages": [2, 3]}

    def extract_docx(path, **kwargs):
        calls.append(("docx", path, kwargs))
        return {"text": "source text", "images": images}

    def audio(narrations, **kwargs):
        calls.append(("audio", narrations, kwargs))
        folder = Path(kwargs["output_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        files = [folder / "s1.mp3", folder / "s2.mp3"]
        for path in files:
            path.write_bytes(b"offline audio stub")
        return files

    def duration(path):
        if broken_duration and Path(path).name == "s2.mp3":
            raise ValueError("unreadable duration")
        return {"s1.mp3": 3.1467, "s2.mp3": 4.6619}[Path(path).name]

    modules = {
        "lesson_plan": SimpleNamespace(generate_lesson_plan=fake_plan),
        "scriptwriter": SimpleNamespace(generate_script=fake_script),
        "storyboard": SimpleNamespace(generate_storyboard=fake_storyboard),
        "parser": SimpleNamespace(
            extract_lesson_info=extract_pdf, extract_section_from_docx=extract_docx,
            extract_pdf_image_inventory=lambda *_args, **_kwargs: [],
        ),
        "narrator": SimpleNamespace(generate_audio=audio, get_audio_duration=duration),
    }
    from textbook2video import pipeline
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, f"textbook2video.pipeline.{name}", module)
        monkeypatch.setattr(pipeline, name, module, raising=False)

    is_docx = entry.endswith("docx")
    is_cli = entry.startswith("cli")
    source = "source.docx" if is_docx else "source.pdf"
    common = dict(output_dir=tmp_path, model="offline-model", skip_tts=skip_tts,
                  agent_review=True, agent_review_rounds=3, agent_review_strict=True)
    if is_cli:
        args = SimpleNamespace(input=source, output=str(tmp_path), lesson=4, chapter=2,
                               section=1, **{k: v for k, v in common.items() if k != "output_dir"})
        (cli.cmd_generate_docx if is_docx else cli.cmd_generate)(args)
    elif is_docx:
        orchestrator.build_storyboard_docx(source, chapter=2, section=1, **common)
    else:
        orchestrator.build_storyboard_pdf(source, lesson=4, **common)

    stem = "ch2_s1" if is_docx else "lesson4"
    title = "第3章" if is_docx else "PDF title"
    assert (tmp_path / f"{stem}_raw.txt").read_text(encoding="utf-8") == "source text"
    assert json.loads((tmp_path / f"{stem}_lesson_plan.json").read_text(encoding="utf-8")) == plan
    headers = ([f"第{i}段：" if is_cli else f"第{i}：" for i in (1, 2)] if is_docx
               else ["Segment 1:", "Segment 2:"])
    assert (tmp_path / f"{stem}_script.txt").read_text(encoding="utf-8") == "".join(
        f"{header}\n{text}\n\n" for header, text in zip(headers, segments))
    image_kwargs = {"available_images": images} if is_docx else {}
    assert calls[1:4] == [
        ("plan", "source text", dict(lesson_title=title, model="offline-model", **image_kwargs)),
        ("script", "source text", dict(model="offline-model", lesson_plan=plan,
                                     raw_response_path=tmp_path / f"{stem}_script_model_response.txt")),
        ("storyboard", segments, dict(lesson_title=title, model="offline-model", lesson_plan=plan,
                                     agent_review=True, agent_review_rounds=3,
                                     agent_review_strict=True, **image_kwargs,
                                     **({"use_script_segment_ids": True} if not is_cli else {}))),
    ]
    expected = copy.deepcopy(original)
    if is_docx:
        expected["metadata"]["available_images"] = images
    if not skip_tts:
        assert calls[4] == ("audio", segments, {"output_dir": str(tmp_path / f"{stem}_audio")})
        precision = 1 if is_cli else 3
        for segment, value in zip(expected["segments"], [3.1467, 0 if broken_duration else 4.6619]):
            segment["audio_duration_sec"] = round(value, precision)
        expected = (apply_timing(expected) if is_cli
                    else apply_timing(expected, timing_mode="legacy"))
        timed_path = tmp_path / f"{stem}_timed_storyboard.json"
        assert json.loads(timed_path.read_text(encoding="utf-8")) == expected
    else:
        assert len(calls) == 4
        assert not (tmp_path / f"{stem}_audio").exists()
    storyboard_path = tmp_path / f"{stem}_storyboard.json"
    assert json.loads(storyboard_path.read_text(encoding="utf-8")) == expected
