"""P0 research preparation on either side of production TTS.

Owns research artifacts and their compatibility protocol; never synthesizes audio
or renders video, and does not import the production orchestrator or Artifacts.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from .p0_integration import P0IntegrationPaths, apply_p0_event_schedule, prepare_p0_candidate


@dataclass(frozen=True)
class P0Preparation:
    """Persisted research inputs carried across the production TTS boundary."""

    paths: P0IntegrationPaths
    plan_path: str | Path | None
    evidence_path: Path
    graph_path: Path
    visual_decision_path: Path
    visual_acquisition_path: Path
    compiled_visual_manifest_path: Path | None = None
    compiled_visual_bindings: list[dict] | None = None


def prepare_p0_research(
    storyboard_path: Path, *, raw_path: Path, images: list[dict],
    lesson_plan_path: Path | None, output_dir: Path, stem: str,
    model: str | None = None, p0_plan: str | Path | None = None,
    p0_proposition_graph: str | Path | None = None,
    p0_visual_decisions: str | Path | None = None,
    p0_retrieval_catalog: str | Path | None = None,
    p0_enable_generation: bool = False, p0_vlm_review: str | Path | None = None,
    p0_method_mode: str = "phase2", p0_visual_specs: str | Path | None = None,
    p0_visual_bindings: str | Path | None = None, p0_auto_visuals: bool = False,
    theme: str | None = None,
) -> P0Preparation:
    """Prepare evidence, decisions, acquisition and a candidate before measured TTS."""
    p0_base_storyboard_path = storyboard_path
    compiled_visual_manifest_path: Path | None = None
    compiled_visual_bindings: list[dict[str, object]] = []
    if p0_visual_specs:
        specs_path = Path(p0_visual_specs)
        bindings_path = Path(p0_visual_bindings)  # guarded above
        if not specs_path.is_file() or not bindings_path.is_file():
            raise FileNotFoundError("P0 visual specs and bindings must both exist")
        specs_payload = json.loads(specs_path.read_text(encoding="utf-8"))
        specs = specs_payload.get("visuals") if isinstance(specs_payload, dict) else specs_payload
        bindings_payload = json.loads(bindings_path.read_text(encoding="utf-8"))
        bindings = (
            bindings_payload.get("bindings")
            if isinstance(bindings_payload, dict)
            else bindings_payload
        )
        if not isinstance(specs, list) or not isinstance(bindings, list):
            raise ValueError("P0 visual specs and bindings must be JSON lists or visuals/bindings objects")
        if not bindings or not all(isinstance(item, dict) for item in bindings):
            raise ValueError("P0 visual bindings must be a non-empty list of objects")
        from textbook2video.research.visual_synthesis import compile_visuals

        compiled_visual_manifest_path = compile_visuals(
            specs,
            output_dir / f"{stem}_p0_visuals",
            theme_id=theme or "bright",
        )
        compiled_visual_bindings = bindings
        print(f"  P0 compiled teaching visuals: {compiled_visual_manifest_path}")
    p0_paths = prepare_p0_candidate(
        p0_base_storyboard_path,
        output_dir=output_dir,
        # Bootstrap paths and source evidence only.  A supplied plan may
        # reference IDs from the real proposition graph, so validating it
        # against temporary sentence-derived propositions here would reject
        # a correct formal plan before the graph is loaded below.
        proposition_graph_path=p0_proposition_graph,
    )
    from textbook2video.research.proposition_graph import build_proposition_graph
    from textbook2video.research.source_evidence import build_source_evidence

    evidence_path = p0_paths.sidecar_path.with_name(
        p0_paths.sidecar_path.name.replace("_research_p0.json", "_source_evidence.json")
    )
    build_source_evidence(
        raw_path,
        images,
        output_path=evidence_path,
    )
    graph_path = Path(p0_proposition_graph) if p0_proposition_graph else p0_paths.sidecar_path.with_name(
        p0_paths.sidecar_path.name.replace("_research_p0.json", "_proposition_graph.json")
    )
    if not p0_proposition_graph:
        build_proposition_graph(
            raw_path=raw_path,
            source_evidence_path=evidence_path,
            storyboard_path=p0_base_storyboard_path,
            lesson_plan_path=lesson_plan_path,
            output_path=graph_path,
            model=model,
        )
    elif not graph_path.is_file():
        raise FileNotFoundError(f"P0 proposition graph does not exist: {graph_path}")
    from textbook2video.research.visual_acquisition import execute_visual_acquisition
    from textbook2video.research.visual_decision import decide_visual_support

    visual_decision_path = Path(p0_visual_decisions) if p0_visual_decisions else p0_paths.sidecar_path.with_name(
        p0_paths.sidecar_path.name.replace("_research_p0.json", "_visual_decisions.json")
    )
    if not p0_visual_decisions:
        decide_visual_support(
            proposition_graph_path=graph_path,
            source_evidence_path=evidence_path,
            output_path=visual_decision_path,
            model=model,
            retrieval_catalog_path=p0_retrieval_catalog,
            storyboard_path=p0_base_storyboard_path,
        )
    elif not visual_decision_path.is_file():
        raise FileNotFoundError(f"P0 visual decision file does not exist: {visual_decision_path}")
    # External/frozen decision files from the first P0 iteration are
    # upgraded once at the boundary.  Downstream code then consumes one
    # validated v2 shape rather than treating omitted audit fields as
    # implicit guarantees.
    from .visual_decision import upgrade_visual_decision_file
    upgrade_visual_decision_file(
        visual_decision_path, proposition_graph_path=graph_path, source_evidence_path=evidence_path,
    )
    if p0_auto_visuals:
        from textbook2video.research.auto_visual_plan import build_auto_visual_plan
        from textbook2video.research.visual_synthesis import compile_visuals

        auto_plan_path = output_dir / f"{stem}_p0_auto_visual_plan.json"
        build_auto_visual_plan(
            proposition_graph_path=graph_path,
            visual_decision_path=visual_decision_path,
            output_path=auto_plan_path,
            model=model,
        )
        auto_plan = json.loads(auto_plan_path.read_text(encoding="utf-8"))
        p0_plan_path = output_dir / f"{stem}_p0_auto_plan.json"
        p0_plan_path.write_text(
            json.dumps(auto_plan["plan"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        p0_plan = p0_plan_path
        compiled_visual_bindings = auto_plan["bindings"]
        compiled_visual_manifest_path = compile_visuals(
            auto_plan["visuals"], output_dir / f"{stem}_p0_visuals",
            theme_id=theme or "bright",
        )
        print(f"  P0 auto visual plan: {auto_plan_path}")
    visual_acquisition_path = execute_visual_acquisition(
        decision_path=visual_decision_path,
        output_dir=output_dir / f"{stem}_p0_acquisition",
        retrieval_catalog_path=p0_retrieval_catalog,
        enable_generation=p0_enable_generation and not p0_auto_visuals,
    )
    if p0_vlm_review:
        from textbook2video.research.visual_acquisition import apply_vlm_review_to_acquisition
        review_path = Path(p0_vlm_review)
        if not review_path.is_file():
            raise FileNotFoundError(f"P0 VLM review does not exist: {review_path}")
        visual_acquisition_path = apply_vlm_review_to_acquisition(
            acquisition_path=visual_acquisition_path,
            vlm_review_path=review_path,
            output_path=Path(visual_acquisition_path).with_name("visual_acquisition_reviewed.json"),
        )
    p0_paths = prepare_p0_candidate(
        storyboard_path,
        output_dir=output_dir,
        proposition_graph_path=graph_path,
    )
    if p0_plan is None and p0_method_mode == "legacy":
        from textbook2video.research.p0_planner import build_local_p0_plan
        p0_plan = build_local_p0_plan(
            p0_paths,
            source_evidence_path=evidence_path,
            visual_decision_path=visual_decision_path,
            require_visual_decisions=True,
        )
        p0_paths = prepare_p0_candidate(
            p0_base_storyboard_path,
            output_dir=output_dir,
            plan_path=p0_plan,
            proposition_graph_path=graph_path,
            visual_decision_path=visual_decision_path,
            compiled_visual_manifest_path=compiled_visual_manifest_path,
            compiled_visual_bindings=compiled_visual_bindings,
        )
        print(f"  P0 legacy local plan: {p0_plan}")
    else:
        p0_paths = prepare_p0_candidate(
            p0_base_storyboard_path,
            output_dir=output_dir,
            plan_path=p0_plan,
            proposition_graph_path=graph_path,
            visual_decision_path=visual_decision_path,
            compiled_visual_manifest_path=compiled_visual_manifest_path,
            compiled_visual_bindings=compiled_visual_bindings,
        )
    candidate_sidecar = json.loads(p0_paths.sidecar_path.read_text(encoding="utf-8"))
    candidate_sidecar["visual_decision_path"] = str(visual_decision_path)
    candidate_sidecar["visual_acquisition_path"] = str(visual_acquisition_path)
    if compiled_visual_manifest_path:
        candidate_sidecar["compiled_visual_manifest_path"] = str(compiled_visual_manifest_path)
        candidate_sidecar["compiled_visual_bindings"] = compiled_visual_bindings
    p0_paths.sidecar_path.write_text(
        json.dumps(candidate_sidecar, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return P0Preparation(
        p0_paths, p0_plan, evidence_path, graph_path, visual_decision_path, visual_acquisition_path,
        compiled_visual_manifest_path, compiled_visual_bindings,
    )


def schedule_p0_research(
    preparation: P0Preparation, *, output_dir: Path, stem: str, audio_dir: Path,
    p0_retrieval_catalog: str | Path | None = None,
) -> P0IntegrationPaths:
    """Require measured cues, compile phase2 if needed, then apply the event schedule."""
    p0_paths = preparation.paths
    p0_plan = preparation.plan_path
    p0_base_storyboard_path = p0_paths.baseline_storyboard_path
    graph_path = preparation.graph_path
    visual_decision_path = preparation.visual_decision_path
    p0_sentence_cues = None
    p0_sentence_cues_path = audio_dir / "sentence_cues.json"
    if p0_sentence_cues_path.is_file():
        try:
            p0_sentence_cues = json.loads(
                p0_sentence_cues_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"P0 sentence cues could not be read: {exc}") from exc
    if p0_sentence_cues is None:
        raise ValueError(
            "formal P0 generation requires measured sentence_cues.json; "
            "duration-weighted timing fallback is disabled"
        )
    candidate_before_plan = json.loads(p0_paths.candidate_storyboard_path.read_text(encoding="utf-8"))
    if p0_plan is None:
        from .p0_method_runner import prepare_p0_phase2_plan

        p0_plan = prepare_p0_phase2_plan(
            output_dir=output_dir, stem=stem,
            storyboard_path=preparation.paths.candidate_storyboard_path,
            baseline_storyboard_path=p0_base_storyboard_path, graph_path=graph_path,
            evidence_path=preparation.evidence_path, visual_decision_path=visual_decision_path,
            visual_acquisition_path=preparation.visual_acquisition_path,
            sentence_cues_path=p0_sentence_cues_path, retrieval_catalog_path=p0_retrieval_catalog,
        )
        p0_paths = prepare_p0_candidate(
            p0_base_storyboard_path,
            output_dir=output_dir,
            plan_path=p0_plan,
            proposition_graph_path=graph_path,
            visual_decision_path=visual_decision_path,
            compiled_visual_manifest_path=preparation.compiled_visual_manifest_path,
            compiled_visual_bindings=preparation.compiled_visual_bindings,
        )
        # Retain the original post-compilation read and its failure behavior.
        candidate = json.loads(p0_paths.candidate_storyboard_path.read_text(encoding="utf-8"))
        _carry_measured_p0_timing(candidate_before_plan, candidate)
        p0_paths.candidate_storyboard_path.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        print(f"  P0 phase-two plan: {p0_plan}")
    apply_p0_event_schedule(p0_paths, sentence_cues=p0_sentence_cues)
    return p0_paths


def _carry_measured_p0_timing(
    measured_storyboard: dict,
    planned_storyboard: dict,
) -> None:
    """Keep measured TTS timing when phase two rematerializes a P0 candidate."""
    measured_segments = measured_storyboard.get("segments")
    planned_segments = planned_storyboard.get("segments")
    if not isinstance(measured_segments, list) or not isinstance(planned_segments, list):
        raise ValueError("P0 timing carry-forward requires storyboard segment lists")

    measured_by_id = {
        str(segment.get("id", index)): segment
        for index, segment in enumerate(measured_segments, start=1)
        if isinstance(segment, dict)
    }
    planned_by_id = {
        str(segment.get("id", index)): segment
        for index, segment in enumerate(planned_segments, start=1)
        if isinstance(segment, dict)
    }
    if set(measured_by_id) != set(planned_by_id):
        raise ValueError("P0 timing carry-forward segment IDs do not match")

    for segment_id, measured in measured_by_id.items():
        planned = planned_by_id[segment_id]
        if str(measured.get("narration") or "") != str(planned.get("narration") or ""):
            raise ValueError(f"P0 timing carry-forward narration mismatch: {segment_id}")
        duration = measured.get("audio_duration_sec")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError(f"P0 timing carry-forward missing measured duration: {segment_id}")
        planned["audio_duration_sec"] = float(duration)
        for key in ("timeline", "animations"):
            value = measured.get(key)
            if isinstance(value, list):
                planned[key] = copy.deepcopy(value)
