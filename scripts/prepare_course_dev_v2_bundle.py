"""Freeze the page, asset, review, and audio inputs for lesson 002 v2 replay.

The builder only reads saved offline artifacts. It never calls a model, TTS, or
asset service. Its output is a hash-sealed input bundle for
``replay_course_dev_bundle.py``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import wave
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


def _norm(text: str) -> str:
    return re.sub(r"[\s，,。！？!?；;、：:“”‘’（）()《》【】\[\]…]", "", text)


def _anchor_time(
    cues: list[dict[str, Any]], phrase: str, duration: float, *, lead_sec: float = 0.0
) -> float:
    normalized_phrase = _norm(phrase)
    estimate = None
    for cue in cues:
        normalized_text = _norm(str(cue.get("text", "")))
        index = normalized_text.find(normalized_phrase)
        if index < 0:
            continue
        cue_start = float(cue.get("start_sec", 0.0))
        cue_end = float(cue.get("end_sec", cue_start))
        fraction = index / max(1, len(normalized_text))
        estimate = cue_start + (cue_end - cue_start) * fraction - max(0.0, lead_sec)
        break
    if estimate is None:
        raise ValueError(f"anchor phrase not found in measured sentence cues: {phrase!r}")
    return round(max(0.0, min(duration - 0.75, estimate)), 3)


def _cue_start(
    cues: list[dict[str, Any]], phrase: str, duration: float, *, lead_sec: float = 0.0
) -> float:
    normalized_phrase = _norm(phrase)
    for cue in cues:
        if normalized_phrase in _norm(str(cue.get("text", ""))):
            return round(max(0.0, float(cue.get("start_sec", 0.0)) - max(0.0, lead_sec)), 3)
    raise ValueError(f"sentence anchor not found in measured sentence cues: {phrase!r}")


def _event_time(item: dict[str, Any]) -> float:
    for key in ("at_sec", "trigger_at_sec", "start_sec"):
        if key in item:
            return float(item[key])
    return float(item.get("start_ms", item.get("at_ms", 0))) / 1000


def _copy_review_evidence(bundle: Path, page3_run: Path, source_run: Path) -> list[dict[str, Any]]:
    evidence_sources = [
        (
            "page3-source-figure.review.json",
            page3_run / "selection-02/asset-review-3-000.review.json",
        ),
        (
            "page3-retrieved-figure.review.json",
            page3_run / "selection-retrieved/asset-review-3-000.review.json",
        ),
        (
            "page3-retrieved-hash-diagram.review.json",
            page3_run / "selection-retrieved/asset-review-3-001.review.json",
        ),
        ("page3-selection-02.json", page3_run / "selection-02/selection.json"),
        ("page3-selection-retrieved.json", page3_run / "selection-retrieved/selection.json"),
        ("prior-content-event-filters.json", source_run / "input/content-event-filters.json"),
        ("prior-render-exclusions.json", source_run / "render-03/render-exclusions.json"),
    ]
    records: list[dict[str, Any]] = []
    for name, source in evidence_sources:
        if not source.is_file():
            if "asset-review" in name or name.startswith("page3-selection"):
                raise FileNotFoundError(
                    f"required saved page-3 review evidence is missing: {source}"
                )
            continue
        target = bundle / "reviews" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records.append(
            {
                "path": target.relative_to(bundle).as_posix(),
                "sha256": _sha(target),
                "bytes": target.stat().st_size,
            }
        )
    return records


def prepare_bundle(
    source_run: Path, page3_run: Path, page4_run: Path, output: Path
) -> dict[str, Any]:
    source_run, page3_run, page4_run = (p.resolve() for p in (source_run, page3_run, page4_run))
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite a bundle: {output}")
    for required in (
        source_run / "input/storyboard.json",
        source_run / "input/execution-map.json",
        page3_run / "audio/s1.wav",
        page4_run / "audio/s1.wav",
        page4_run / "audio/s2.wav",
        page4_run / "audio/s3.wav",
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    from textbook2video.animation_ids import visual_node_animation_id
    from textbook2video.pipeline.subtitles import build_subtitle_cues
    from textbook2video.pipeline.timing import apply_timing

    output.mkdir(parents=True)
    for name in ("audio", "images", "reviews"):
        (output / name).mkdir()
    shutil.copytree(source_run / "input/images", output / "images", dirs_exist_ok=True)

    storyboard = json.loads((source_run / "input/storyboard.json").read_text(encoding="utf-8"))
    execution_map = json.loads(
        (source_run / "input/execution-map.json").read_text(encoding="utf-8")
    )
    segments = {str(segment["id"]): segment for segment in storyboard["segments"]}
    source_records = {
        str(record["derived_segment_id"]): record for record in execution_map["source_to_derived"]
    }

    # Preserve byte-identical existing WAVs; no TTS is run for this bundle.
    p4_audio = page4_run / "audio"
    reused_paths = {
        "3": page3_run / "audio/s1.wav",
        "4-inputs": p4_audio / "s1.wav",
        "4-payment-inputs": p4_audio / "s2.wav",
        "4-outputs": p4_audio / "s3.wav",
    }
    audio_entries: list[dict[str, Any]] = []
    for index, segment in enumerate(storyboard["segments"], start=1):
        segment_id = str(segment["id"])
        source = source_run / "audio" / f"s{index}.wav"
        target = output / "audio" / source.name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target)
        if segment_id in reused_paths:
            prior = reused_paths[segment_id]
            if not prior.is_file() or _sha(prior) != _sha(target):
                raise ValueError(
                    f"saved reused audio differs from the full-course copy: {segment_id}"
                )
            mode, provenance = "reused_saved_audio", str(prior)
        else:
            mode, provenance = (
                "existing_local_sapi_audio_from_v1",
                "exact bytes copied from the preceding full-course run",
            )
        duration = round(_wav_duration(target), 3)
        if abs(duration - float(segment["audio_duration_sec"])) > 0.03:
            raise ValueError(f"WAV/storyboard duration mismatch for {segment_id}")
        segment["audio_duration_sec"] = duration
        mapping = source_records[segment_id]
        audio_entries.append(
            {
                "source_page_id": mapping["source_page_id"],
                "derived_segment_id": segment_id,
                "path": f"audio/{source.name}",
                "sha256": _sha(target),
                "narration_sha256": hashlib.sha256(
                    str(segment["narration"]).encode("utf-8")
                ).hexdigest(),
                "duration_sec": duration,
                "mode": mode,
                "source": provenance,
            }
        )

    original_timeline: dict[str, dict[str, float]] = {}
    for segment in storyboard["segments"]:
        original_timeline[str(segment["id"])] = {
            target.strip(): _event_time(event)
            for event in segment.get("timeline", []) or []
            for target in str(event.get("target", "")).split(",")
            if target.strip()
        }

    # Page 5 retains e7's stable target and replaces only its short explanation
    # with the source-supported 100 -> 500 -> recompute -> compare -> detect chain.
    page5 = segments["5"]
    old_e7 = copy.deepcopy(
        next(element for element in page5["elements"] if element.get("id") == "e7")
    )
    e7 = next(element for element in page5["elements"] if element.get("id") == "e7")
    e7.clear()
    e7.update(
        {
            "id": "e7",
            "type": "flow_step",
            "steps": [
                "改交易金额：100元 → 500元",
                "重算被改区块的哈希",
                "对照已分布式保存的原哈希",
                "结果不一致，其他参与者发现",
            ],
        }
    )

    # Remove the page-4 quote that claims this UTXO example itself guarantees
    # traceability and security. Neither the UTXO source paragraph nor this
    # segment's narration makes that claim; source paragraph 22 discusses
    # trust/traceability at the distributed-ledger level, not this transaction.
    page4_outputs = segments["4-outputs"]
    removed_quote = next(
        (element for element in page4_outputs["elements"] if element.get("id") == "e7"), None
    )
    removed_quote_events = []
    if removed_quote is not None:
        removed_quote_events = [
            copy.deepcopy(event)
            for key in ("animations", "timeline")
            for event in page4_outputs.get(key, []) or []
            if event.get("target") == "e7"
        ]
        page4_outputs["elements"] = [
            element for element in page4_outputs["elements"] if element.get("id") != "e7"
        ]
        for key in ("animations", "timeline"):
            page4_outputs[key] = [
                event for event in page4_outputs.get(key, []) or [] if event.get("target") != "e7"
            ]

    # Preserve the renderer's strict source-image rejection, but also remove
    # the corresponding dead targets from this saved replay storyboard.
    blocked_image_filters: list[dict[str, Any]] = []
    blocked_image_records: list[dict[str, Any]] = []
    for segment_id, element_id, destination in (
        (
            "5",
            "e8",
            (
                "The newly grounded e7 four-step tamper-detection flow and unchanged narration "
                "cover the relevant hash-chain check; the blocked repeated figure adds no "
                "separately admitted content."
            ),
        ),
        (
            "7",
            "e2",
            (
                "The original narration and its existing text/cards still explain the combined "
                "technology example; page 7 remains a deliberate none decision."
            ),
        ),
    ):
        segment = segments[segment_id]
        element = next(
            (item for item in segment.get("elements", []) or [] if item.get("id") == element_id),
            None,
        )
        if element is None:
            raise ValueError(
                f"expected previously excluded image {segment_id}:{element_id} is missing"
            )
        events_by_collection = {
            key: [
                copy.deepcopy(event)
                for event in segment.get(key, []) or []
                if element_id in {part.strip() for part in str(event.get("target", "")).split(",")}
            ]
            for key in ("animations", "timeline")
        }
        removed = copy.deepcopy(element)
        segment["elements"] = [
            item for item in segment.get("elements", []) or [] if item.get("id") != element_id
        ]
        for key in ("animations", "timeline"):
            segment[key] = [
                event
                for event in segment.get(key, []) or []
                if element_id
                not in {part.strip() for part in str(event.get("target", "")).split(",")}
            ]
        removed_events = [
            {"collection": collection, **event}
            for collection, events in events_by_collection.items()
            for event in events
        ]
        record = {
            "source_page_id": int(segment_id),
            "derived_segment_id": segment_id,
            "element_id": element_id,
            "type": element.get("type"),
            "content": removed,
            "removed_events": removed_events,
            "reason": (
                "strict source-image admission failed in the saved render exclusion record; "
                "dependent visual events cannot target an image that was refused"
            ),
            "content_destination": destination,
        }
        blocked_image_filters.append(record)
        blocked_image_records.append(
            {
                "source_page_id": int(segment_id),
                "derived_segment_id": segment_id,
                "element_id": element_id,
                "type": element.get("type"),
                "reason": record["reason"],
                "removed_events": removed_events,
                "removed_event_collections": sorted(
                    {item["collection"] for item in removed_events}
                ),
                "content_destination": destination,
            }
        )

    # Place the same saved UTXO asset on all three derived p4 slides before
    # running the repository's existing semantic timing function.
    svg_name = "local-visual-bc1c188e6d95e541.svg"
    svg_path = output / "images" / svg_name
    svg_hash = _sha(svg_path)
    visual_id = "local-visual-018b0bbb891a4a10"
    for segment_id in ("4-inputs", "4-payment-inputs"):
        segment = segments[segment_id]
        if not any(element.get("id") == visual_id for element in segment["elements"]):
            segment["elements"].append(
                {
                    "id": visual_id,
                    "type": "image",
                    "src": svg_name,
                    "description": "UTXO交易示例：两个输入、一次交易、接收者输出与找零",
                    "visual_asset_sha256": svg_hash,
                    "visual_brief_role": "EXPLANATORY_DIAGRAM",
                    "local_visual_size": [1600.0, 680.0],
                }
            )

    # Reuse the repository's sentence splitter and semantic timing policy.
    # Cue intervals are proportional estimates over each exact measured WAV;
    # they are not claimed to be forced acoustic word alignment.
    sentence_groups: list[dict[str, Any]] = []
    cue_map: dict[str, list[dict[str, Any]]] = {}
    for segment in storyboard["segments"]:
        segment_id = str(segment["id"])
        cues = [
            {
                "sentence_id": cue.sentence_id,
                "sentence_index": cue.sentence_index,
                "start_sec": cue.start_sec,
                "end_sec": cue.end_sec,
                "text": cue.text,
            }
            for cue in build_subtitle_cues({"segments": [segment]})
        ]
        cue_map[segment_id] = cues
        sentence_groups.append({"segment_id": segment_id, "cues": cues})
    storyboard = apply_timing(storyboard, {"segments": sentence_groups}, timing_mode="semantic")
    segments = {str(segment["id"]): segment for segment in storyboard["segments"]}

    timeline_corrections: list[dict[str, Any]] = []
    for segment in storyboard["segments"]:
        sid = str(segment["id"])
        old_by_target = original_timeline.get(sid, {})
        for event in segment.get("timeline", []) or []:
            targets = [
                part.strip() for part in str(event.get("target", "")).split(",") if part.strip()
            ]
            for target in targets:
                if target not in old_by_target:
                    continue
                new_time = _event_time(event)
                old_time = old_by_target[target]
                animation = next(
                    (
                        item
                        for item in segment.get("animations", []) or []
                        if item.get("target") == target
                    ),
                    {},
                )
                timeline_corrections.append(
                    {
                        "segment_id": sid,
                        "target": target,
                        "from_sec": round(old_time, 3),
                        "to_sec": round(new_time, 3),
                        "trigger_source": animation.get(
                            "trigger_source", event.get("trigger_source", "preserved_legacy_event")
                        ),
                        "matched_sentence_index": animation.get(
                            "matched_sentence_index", event.get("matched_sentence_index")
                        ),
                        "matched_sentence_text": animation.get(
                            "matched_sentence_text", event.get("matched_sentence_text")
                        ),
                    }
                )

    page5 = segments["5"]
    page5_anchor = _anchor_time(
        cue_map["5"],
        "如果有人修改了交易记录",
        float(page5["audio_duration_sec"]),
        lead_sec=0.12,
    )
    for animation in page5.get("animations", []) or []:
        if animation.get("target") == "e7":
            animation.update(
                {
                    "trigger_at_sec": page5_anchor,
                    "trigger_source": "text_match",
                    "anchor_phrase": "如果有人修改了交易记录",
                    "timing_source": "measured_subtitle_sentence_window_phrase_position",
                }
            )
    for event in page5.get("timeline", []) or []:
        if event.get("target") == "e7":
            event.update(
                {
                    "at_sec": page5_anchor,
                    "trigger_at_sec": page5_anchor,
                    "trigger_source": "text_match",
                    "anchor_phrase": "如果有人修改了交易记录",
                    "timing_source": "measured_subtitle_sentence_window_phrase_position",
                }
            )
    for correction in timeline_corrections:
        if correction["segment_id"] == "5" and correction["target"] == "e7":
            correction["to_sec"] = page5_anchor
            correction["matched_sentence_text"] = next(
                (cue["text"] for cue in cue_map["5"] if "如果有人修改了交易记录" in cue["text"]),
                None,
            )
            correction["trigger_source"] = "text_match"

    # The existing p10 summary stays thesis -> mechanism -> properties ->
    # takeaway. Bind those four existing elements to the corresponding spoken
    # sentences; no image or new content is introduced. The old diagram e2 and
    # its dependent callouts e3/e4 were already excluded by strict source-image
    # admission. Remove their now-dead targets from the saved storyboard too.
    page10 = segments["10"]
    page10_excluded_ids = {"e2", "e3", "e4"}
    page10_removed_elements = [
        copy.deepcopy(element)
        for element in page10.get("elements", []) or []
        if element.get("id") in page10_excluded_ids
    ]
    page10_removed_events = {
        key: [
            copy.deepcopy(event)
            for event in page10.get(key, []) or []
            if any(
                part.strip() in page10_excluded_ids
                for part in str(event.get("target", "")).split(",")
            )
        ]
        for key in ("animations", "timeline")
    }
    page10_removed_records: list[dict[str, Any]] = []
    page10["elements"] = [
        element
        for element in page10.get("elements", []) or []
        if element.get("id") not in page10_excluded_ids
    ]
    for key in ("animations", "timeline"):
        page10[key] = [
            event
            for event in page10.get(key, []) or []
            if not any(
                part.strip() in page10_excluded_ids
                for part in str(event.get("target", "")).split(",")
            )
        ]

    page10_anchors = {
        "e5": ("区块链利用计算机技术", 0.15),
        "e6": ("综合使用密码学", 0.25),
        "e7": ("建立信任关系", 0.25),
        "e8": ("理解区块链，也是在理解", 0.25),
    }
    page10_timing = {}
    for target, (phrase, lead) in page10_anchors.items():
        at = _anchor_time(cue_map["10"], phrase, float(page10["audio_duration_sec"]), lead_sec=lead)
        page10_timing[target] = {"at_sec": at, "anchor_phrase": phrase}
        for animation in page10.get("animations", []) or []:
            if animation.get("target") == target:
                animation.update(
                    {"trigger_at_sec": at, "trigger_source": "text_match", "anchor_phrase": phrase}
                )
        for event in page10.get("timeline", []) or []:
            if event.get("target") == target:
                event.update(
                    {
                        "at_sec": at,
                        "trigger_at_sec": at,
                        "trigger_source": "text_match",
                        "anchor_phrase": phrase,
                    }
                )
        for correction in timeline_corrections:
            if correction["segment_id"] == "10" and correction["target"] == target:
                correction["to_sec"] = at
                correction["trigger_source"] = "text_match"
                correction["matched_sentence_text"] = next(
                    (cue["text"] for cue in cue_map["10"] if phrase in cue["text"]),
                    None,
                )

    if removed_quote is not None:
        execution_map.setdefault("explicit_content_event_filters", []).append(
            {
                "source_page_id": 4,
                "derived_segment_id": "4-outputs",
                "element_id": "e7",
                "type": "quote",
                "reason": (
                    "the local UTXO example does not establish that it guarantees transaction "
                    "security; the source's separate traceability/trust statement concerns "
                    "distributed accounting, and this quote is absent from the page narration"
                ),
                "removed_events": removed_quote_events,
                "removed_event_collections": ["animations", "timeline"],
                "content_destination": (
                    "No UTXO teaching content is lost; input/output amounts and their "
                    "transaction remain in the same hash-bound diagram and narration."
                ),
            }
        )
    execution_map.setdefault("explicit_content_event_filters", []).extend(blocked_image_records)
    if page10_removed_elements:
        for element in page10_removed_elements:
            element_id = str(element.get("id", ""))
            removed_events = [
                {"collection": collection, **event}
                for collection, events in page10_removed_events.items()
                for event in events
                if element_id in {part.strip() for part in str(event.get("target", "")).split(",")}
            ]
            execution_map.setdefault("explicit_content_event_filters", []).append(
                {
                    "source_page_id": 10,
                    "derived_segment_id": "10",
                    "element_id": element_id,
                    "type": element.get("type"),
                    "reason": (
                        "the previously excluded textbook figure was not admitted for this "
                        "summary page; its callout depends on that figure and must not remain "
                        "as a detached event"
                    ),
                    "removed_events": removed_events,
                    "removed_event_collections": sorted(
                        {event["collection"] for event in removed_events}
                    ),
                    "content_destination": (
                        "The existing summary order e5 thesis -> e6 mechanism -> e7 properties "
                        "-> e8 takeaway remains. No rejected image or callout is restored."
                    ),
                }
            )
            page10_removed_records.append(
                {
                    "source_page_id": 10,
                    "derived_segment_id": "10",
                    "element_id": element_id,
                    "content": element,
                    "removed_events": removed_events,
                    "reason": (
                        "the previously excluded textbook figure was not admitted for this "
                        "summary page; its callout depends on that figure and must not remain "
                        "as a detached event"
                    ),
                    "destination": (
                        "the existing thesis, mechanism, properties, and takeaway remain in "
                        "e5-e8; no rejected image or callout is restored"
                    ),
                }
            )

    # Reuse one exact hash-bound SVG throughout the existing three-part split.
    svg_name = "local-visual-bc1c188e6d95e541.svg"
    svg_path = output / "images" / svg_name
    svg_hash = _sha(svg_path)
    visual_id = "local-visual-018b0bbb891a4a10"
    node_descriptions = {
        "input_05": "0.5 BTC 输入UTXO",
        "input_03": "0.3 BTC 输入UTXO",
        "process_txn": "支付0.6 BTC 的交易",
        "output_06": "接收者的0.6 BTC 输出UTXO",
        "output_02": "找零的0.2 BTC 输出UTXO",
    }
    stage_specs = {
        "4-inputs": {
            "asset_phrase": "0.5和0.3",
            "asset_lead": 0.18,
            "stages": [(["input_05", "input_03"], "0.5和0.3", 0.12, "输入UTXO")],
        },
        "4-payment-inputs": {
            "asset_phrase": "支付0.6比特币",
            "asset_lead": 0.18,
            "stages": [
                (["input_05", "input_03"], "支付0.6比特币", 0.12, "输入UTXO"),
                (["process_txn"], "作为交易输入", 1.1, "支付交易"),
            ],
        },
        "4-outputs": {
            "asset_phrase": "0.6比特币的新UTXO",
            "asset_lead": 0.18,
            "stages": [
                (
                    ["input_05", "input_03", "process_txn"],
                    "0.6比特币的新UTXO",
                    0.0,
                    "输入与交易上下文",
                ),
                (["output_06"], "给接收者", 0.0, "接收者输出"),
                (["output_02"], "0.2比特币的新UTXO", 0.08, "找零输出"),
            ],
        },
    }
    utxo_events: list[dict[str, Any]] = []
    for segment_id, spec in stage_specs.items():
        segment = segments[segment_id]
        duration = float(segment["audio_duration_sec"])
        element = next((item for item in segment["elements"] if item.get("id") == visual_id), None)
        if element is None:
            element = {
                "id": visual_id,
                "type": "image",
                "src": svg_name,
                "description": "UTXO交易示例：两个输入、一次交易、接收者输出与找零",
                "visual_asset_sha256": svg_hash,
                "visual_brief_role": "EXPLANATORY_DIAGRAM",
                "local_visual_size": [1600.0, 680.0],
            }
            segment["elements"].append(element)
        elif element.get("src") != svg_name or element.get("visual_asset_sha256") != svg_hash:
            raise ValueError(f"saved UTXO visual id/hash changed on {segment_id}")
        element["visual_object_targets"] = {
            visual_node_animation_id(visual_id, node): {"node_id": node, "description": description}
            for node, description in node_descriptions.items()
        }
        image_at = _anchor_time(
            cue_map[segment_id],
            spec["asset_phrase"],
            duration,
            lead_sec=float(spec["asset_lead"]),
        )
        animations = segment.setdefault("animations", [])
        parent_animation = next(
            (item for item in animations if item.get("target") == visual_id), None
        )
        if parent_animation is None:
            parent_animation = {"target": visual_id, "effect": "fadeInUp"}
            animations.append(parent_animation)
        parent_animation.update(
            {
                "trigger_at_sec": image_at,
                "timing_source": (
                    "existing_sentence_cue_window_and_phrase_position_scaled_to_measured_wav_duration"
                ),
                "anchor_phrase": spec["asset_phrase"],
            }
        )
        timeline = segment.setdefault("timeline", [])
        parent_event = next(
            (
                item
                for item in timeline
                if item.get("target") == visual_id and item.get("action", "show") == "show"
            ),
            None,
        )
        if parent_event is None:
            parent_event = {
                "event_id": f"{segment_id}-{visual_id}-show",
                "target": visual_id,
                "action": "show",
                "effect": "fadeInUp",
            }
            timeline.append(parent_event)
        parent_event.setdefault("event_id", f"{segment_id}-{visual_id}-show")
        parent_event.update(
            {
                "at_sec": image_at,
                "timing_source": (
                    "existing_sentence_cue_window_and_phrase_position_scaled_to_measured_wav_duration"
                ),
                "anchor_phrase": spec["asset_phrase"],
            }
        )
        utxo_events.append(
            {
                "segment_id": segment_id,
                "event_id": parent_event["event_id"],
                "target": visual_id,
                "action": "show",
                "at_sec": image_at,
                "anchor_phrase": spec["asset_phrase"],
                "measured_audio_duration_sec": duration,
            }
        )

        stage_schedule: list[dict[str, Any]] = []
        prior_stage_at: float | None = None
        for node_ids, phrase, lead, label in spec["stages"]:
            at = _anchor_time(cue_map[segment_id], phrase, duration, lead_sec=float(lead))
            at = max(at, round(image_at + 0.7, 3))
            if prior_stage_at is not None:
                at = max(at, round(prior_stage_at + 0.45, 3))
            at = min(at, round(duration - 0.5, 3))
            prior_stage_at = at
            stage_schedule.append(
                {
                    "node_ids": node_ids,
                    "phrase": phrase,
                    "label": label,
                    "at_sec": at,
                }
            )

        for stage_index, stage in enumerate(stage_schedule):
            stage_number = stage_index + 1
            node_ids = stage["node_ids"]
            phrase = stage["phrase"]
            label = stage["label"]
            at = float(stage["at_sec"])
            next_at = (
                float(stage_schedule[stage_index + 1]["at_sec"])
                if stage_index + 1 < len(stage_schedule)
                else duration
            )
            hold_sec = round(max(0.0, next_at - at - 0.1), 3)
            node_targets = [visual_node_animation_id(visual_id, node_id) for node_id in node_ids]
            event_id = f"{segment_id}-{visual_id}-stage-{stage_number}"
            timeline.append(
                {
                    "event_id": event_id,
                    "target": ",".join(node_targets),
                    "action": "focus",
                    "effect": "highlight",
                    "at_sec": at,
                    "hold_sec": hold_sec,
                    "stage": label,
                    "timing_source": (
                        "existing_sentence_cue_window_and_phrase_position_scaled_to_measured_wav_duration"
                    ),
                    "anchor_phrase": phrase,
                }
            )
            for target in node_targets:
                animations.append(
                    {
                        "target": target,
                        "action": "focus",
                        "effect": "highlight",
                        "trigger_at_sec": at,
                        "hold_sec": hold_sec,
                        "timing_source": (
                            "existing_sentence_cue_window_and_phrase_position_scaled_to_measured_wav_duration"
                        ),
                        "anchor_phrase": phrase,
                    }
                )
            utxo_events.append(
                {
                    "segment_id": segment_id,
                    "event_id": event_id,
                    "target": ",".join(node_targets),
                    "node_ids": node_ids,
                    "stage": label,
                    "action": "focus",
                    "at_sec": at,
                    "hold_sec": hold_sec,
                    "reading_window_sec": hold_sec,
                    "anchor_phrase": phrase,
                    "measured_audio_duration_sec": duration,
                }
            )
        segment["visual_object_timing"] = {
            "mode": "existing_hash_bound_svg_nodes_with_phrase_anchors",
            "human_timing_review": "pending",
            "events": [event for event in utxo_events if event["segment_id"] == segment_id],
        }

    for record in execution_map["source_to_derived"]:
        if str(record["derived_segment_id"]) in stage_specs:
            record["assets"] = [
                f"same hash-bound UTXO SVG; stable element id {visual_id}",
                "historical model screenshot ACCEPT is report-only; "
                "human/page review remains pending",
            ]

    verified_by_name = {
        Path(record["destination"]).name: record
        for record in execution_map.get("verified_asset_copies", [])
    }
    assets = []
    for image_path in sorted((output / "images").iterdir()):
        if not image_path.is_file():
            continue
        previous = verified_by_name.get(image_path.name, {})
        assets.append(
            {
                "path": f"images/{image_path.name}",
                "sha256": _sha(image_path),
                "bytes": image_path.stat().st_size,
                "source": previous.get("source", "copied from the prior saved full-course bundle"),
            }
        )

    review_evidence = _copy_review_evidence(output, page3_run, source_run)
    reviews = {
        "schema": "course-dev-review-evidence-v1",
        "scope_note": (
            "Run evidence index only. It does not modify G0 or grant page/whole-course acceptance."
        ),
        "records": [
            {
                "asset_file": "images/generated-517860c76815c79e-002.png",
                "verdict": "ACCEPT",
                "scope": "page3 selected hash diagram only",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [
                    item
                    for item in review_evidence
                    if "retrieved-hash-diagram.review.json" in item["path"]
                    or "page3-selection-retrieved.json" in item["path"]
                ],
            },
            {
                "asset_file": "images/generated-9269bc182103e223-001.png",
                "verdict": "ACCEPT",
                "scope": "page3 element e2 only",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [
                    item
                    for item in review_evidence
                    if "source-figure.review.json" in item["path"]
                    or "page3-selection-02.json" in item["path"]
                ],
            },
            {
                "asset_file": "images/fig7-6_区块链数据结构.png",
                "verdict": "page3-scope ACCEPT only; not inherited by other pages",
                "scope": "page3 element e2 only; no ACCEPT for pages 5, 6, 7, or 10",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [
                    item for item in review_evidence if "source-figure.review.json" in item["path"]
                ],
            },
            {
                "asset_file": "images/local-visual-bc1c188e6d95e541.svg",
                "verdict": (
                    "historical model screenshot ACCEPT reported in prior page4/full-course "
                    "reports; no standalone review file copied"
                ),
                "scope": "UTXO segments only",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [],
            },
            {
                "asset_file": "page5 e7 native flow_step",
                "verdict": (
                    "deterministic source-derived component; no external image or model review"
                ),
                "scope": "page5 only",
                "source_reference": "frozen lesson_002.md paragraph 18",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [],
            },
            {
                "asset_file": "images/fig7-6_区块链数据结构.png",
                "verdict": (
                    "not admitted in pages 5, 6, 7, or 10; existing render exclusions retained"
                ),
                "scope": "source image proposals on pages 5, 6, 7, and 10",
                "whole_page_review": "pending",
                "human_review": "pending",
                "evidence_files": [
                    item
                    for item in review_evidence
                    if "prior-render-exclusions.json" in item["path"]
                ],
            },
        ],
    }
    _write_json(output / "asset-review-records.json", reviews)

    execution_map["audio"] = audio_entries
    execution_map["assets"] = assets
    execution_map["timeline_corrections"] = {
        "method": (
            "repository apply_timing semantic mode uses existing sentence cues built from each "
            "measured WAV; runtime timeline entries are updated from those triggers"
        ),
        "records": timeline_corrections,
        "cue_source": (
            "repository build_subtitle_cues over unchanged narration and measured per-segment "
            "WAV durations"
        ),
        "caveat": (
            "sentence windows are proportional estimates over each measured WAV, not forced "
            "acoustic word alignment; exact listening review remains pending"
        ),
    }
    execution_map["p5_page_update"] = {
        "element_id": "e7",
        "operation": "local replacement preserving stable id and tamper-detection claim",
        "from": old_e7,
        "to": copy.deepcopy(e7),
        "source_reference": (
            "frozen lesson_002.md paragraph 18: 100 yuan -> 500 yuan, changed input changes "
            "the hash, original hash is distributed, tampering is quickly detected"
        ),
        "event_target": "e7",
        "event_at_sec": page5_anchor,
        "anchor_phrase": "如果有人修改了交易记录",
        "model_attempts_this_run": 0,
        "existing_generation_budget": "3 attempts used; exhausted; not reset",
        "review_state": "source-grounded deterministic structure; page and human review pending",
    }
    execution_map["page10_summary_timing"] = {
        "existing_order": ["e5 thesis", "e6 mechanism", "e7 summary properties", "e8 takeaway"],
        "events": page10_timing,
        "image_added": False,
        "rejected_image_restored": False,
        "page_review": "pending",
    }
    execution_map["removed_content_and_events"] = []
    if removed_quote is not None:
        execution_map["removed_content_and_events"].append(
            {
                "source_page_id": 4,
                "derived_segment_id": "4-outputs",
                "element_id": "e7",
                "content": removed_quote,
                "removed_events": removed_quote_events,
                "reason": (
                    "the claim that this UTXO example guarantees security is not supported by "
                    "the source example or this segment's narration; broader trust/traceability "
                    "language occurs elsewhere in the textbook and does not justify attaching "
                    "it here"
                ),
                "destination": (
                    "none; the two input amounts, payment, recipient output, and change output "
                    "remain in the existing UTXO diagram and unchanged narration"
                ),
            }
        )
    execution_map["removed_content_and_events"].extend(page10_removed_records)
    execution_map["removed_content_and_events"].extend(blocked_image_filters)
    execution_map["utxo_staged_visual"] = {
        "asset": f"images/{svg_name}",
        "sha256": svg_hash,
        "stable_element_id": visual_id,
        "events": utxo_events,
        "asset_review": "historical status is report-only; no new acceptance asserted",
        "narration_unchanged": True,
    }
    execution_map["page7_page10_decisions"] = {
        "page7": (
            "none; the saved text and three technology cards state co-presence. The source "
            "gives no directed mapping from each field to each property, "
            "so no arrows were invented."
        ),
        "page10": (
            "none; retain existing thesis -> mechanism -> properties -> takeaway elements and "
            "bind them to their spoken cues; do not restore the rejected textbook image or its "
            "detached callouts."
        ),
    }
    execution_map["replay_run"] = {
        "model_calls": 0,
        "image_generation_calls": 0,
        "health_checks": 0,
        "tts_api_calls": 0,
        "audio_bytes_changed": False,
        "split_mapping_changed": False,
    }
    _write_json(output / "storyboard.json", storyboard)
    _write_json(output / "execution-map.json", execution_map)

    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append(
                {
                    "path": path.relative_to(output).as_posix(),
                    "sha256": _sha(path),
                    "bytes": path.stat().st_size,
                }
            )
    manifest = {
        "schema": "course-dev-bundle-v1",
        "course_id": "lesson_002",
        "storyboard": "storyboard.json",
        "execution_map": "execution-map.json",
        "asset_reviews": "asset-review-records.json",
        "files": files,
        "offline_only": True,
        "theme_id": "bright",
        "browser_channel": "msedge",
        # Let the existing renderer's scale-to-fit use the measured natural
        # content height. A fixed CSS transform here overrides its inline
        # result and can push the page outside the safe area at 1366x768.
        "render_adjustments": [],
        "generation_budget": {
            "page5_existing_attempts": 3,
            "page5_budget_reset": False,
            "new_model_attempts": 0,
        },
        "input_audio_reuse": (
            "all 12 exact WAVs copied from the preceding full-course run; no new TTS"
        ),
        "human_review": "pending",
    }
    _write_json(output / "manifest.json", manifest)
    return {
        "bundle": str(output),
        "segments": len(storyboard["segments"]),
        "audio_entries": len(audio_entries),
        "asset_count": len(assets),
        "review_evidence": review_evidence,
        "page5_anchor_sec": page5_anchor,
        "utxo_events": utxo_events,
        "timeline_corrections": len(timeline_corrections),
        "audio_total_sec": round(sum(item["duration_sec"] for item in audio_entries), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-run", type=Path, required=True, help="saved full-course v1 run directory"
    )
    parser.add_argument(
        "--page3-run", type=Path, required=True, help="saved page3 review/audio directory"
    )
    parser.add_argument(
        "--page4-run", type=Path, required=True, help="saved page4 composed audio directory"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new bundle path; existing paths are never overwritten",
    )
    args = parser.parse_args()
    local_src = str(Path(__file__).resolve().parents[1] / "src")
    if local_src not in sys.path:
        sys.path.insert(0, local_src)
    print(
        json.dumps(
            prepare_bundle(args.source_run, args.page3_run, args.page4_run, args.output),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
