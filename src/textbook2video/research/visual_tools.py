"""VisualPlanV1 generation with a compatible manual create/revise/compose dispatcher.

The model emits a mode-limited candidate plan. The executor owns operation,
wrapping, layout and materialization; the historical manual tool interface remains
available independently. Requests, raw responses and rejected revisions stay inspectable.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from textbook2video.llm.client import chat_with_images, chat_with_system
from textbook2video.research.exact_source_excerpts import exact_evidence
from textbook2video.research.relationship_visuals import validate_relationship
from textbook2video.research.visual_compact_review import (
    COMPACT_RULES,
    build_review_contract,
    expand_review,
)
from textbook2video.research.visual_composition import execution_assets, render_composition
from textbook2video.research.visual_content_map import materialize_content_map
from textbook2video.research.visual_edits import apply_changes
from textbook2video.research.visual_fact_audit import (
    VISIBLE_FACT_RULES,
    build_review_targets,
    fact_audit_findings,
    validate_fact_audit,
)
from textbook2video.research.visual_grammar import CATALOG, GRAMMAR_VERSION, KINDS, validate_visual
from textbook2video.research.visual_interface import materialize_layout, planner_view
from textbook2video.research.visual_model_interface import (
    check_structure,
    model_edit_contract,
    parse_visual_plan_response,
    renderer_graphs,
    renderer_updates,
    visual_plan_contract,
)
from textbook2video.research.visual_narration_refs import (
    materialize_narration_refs,
    narration_units,
)
from textbook2video.research.visual_object_edits import (
    apply_object_updates,
    detail_repair_requested,
    detail_repair_scope,
    label_repair_requested,
    label_repair_scope,
    validate_detail_repair,
    validate_label_repair,
)
from textbook2video.research.visual_panel_repair import (
    can_append_missing_panel,
    expand_missing_panel,
)
from textbook2video.research.visual_relation_semantics import (
    RELATION_REVIEW_RULES,
    RELATION_RULES,
    materialize_relation_audit,
    relation_audit_contract,
    relation_findings,
    validate_relation_audit,
)
from textbook2video.research.visual_semantic_graph import (
    SEMANTIC_GRAPH_RULES,
    materialize_semantic_graphs,
    requires_semantic_replacement,
)
from textbook2video.research.visual_source_refs import (
    SOURCE_REFERENCE_POLICY,
    materialize_source_refs,
    source_units,
)
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
                    "visual_refs": [
                        "visual-id, visual-id:node-id, or rendered visual-id:@constraint"
                    ],
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
            "changes": "instead: [{op:set|add|replace|remove,path:/visuals/0/...,value:...}]",
            "updates": "PREFERRED instead: [{visual_id,node_id? OR edge:{source,target}? OR "
                       "constraint:true?,set:{field:value},remove:[field]?}] or "
                       "[{element_id,set:{decision,reason,source_ref?,visual_refs?}}]. "
                       "delete:true removes a selected visual/node/edge. "
                       "Never mix updates/changes/visuals.",
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
VISUAL_PLAN_PROTOCOL_RULES = """Return one VisualPlanV1 JSON object, not a tool call.
The request's visual_plan_contract is authoritative: emit only its allowed_fields
and include its required_fields. Do not emit tool, name, arguments, operation, mode,
parent or reason; the executor selects operation and supplies revision metadata.
The executor also owns layout and source/narration reference materialization.
"""

REPRESENTATION_RULES = """All graph kinds INCLUDING relationship use ONE flat model interface:
nodes=[{id,label,role:entity|process|data|value|state|event,detail?,stored_by?,refers_to?,source_ref}]
at the visual root. edges=[{source,relation:input|produces|stores|compares|detects|changes|
references|precedes|causes|association,target,directed?,source_ref}]. Omit label on typed edges;
code supplies the action. Select source IDs, never retype quotes.
Do not write diagram, schema_version, columns, node.column or layout fields.
Code adapts the common nodes/edges to each renderer and calculates placement.
For relationship only, an optional top-level constraint is an exact source excerpt,
with constraint_source_ref. It is NOT a substitute for displaying required facts.
Use source-* IDs ONLY in source_ref; narration-* IDs ONLY in narration_refs.
Graph presentation can use text_scale=1|1.25|1.5 (never smaller than 1).
Use 2-8 nodes per panel. Keep labels short. Split complex facts into full-size panels
rather than inventing connections or deleting required facts to fill a template.
comparison has exactly two nodes and no edges; details show shared comparison dimensions.
chart/proportion: series=[{label,value,source_ref}], unit, chart_type=bar|line.
table: rows=[[header,...],[cell,...]], source_ref. formula/code: content,source_ref.
Every spec needs title and teaching_goal. Keep code indentation and exact formulas.
"""

PLAN_RULES = """Select the representation from teaching_goal and source, not image description.
You supply semantic nodes/edges and source_ref IDs; code supplies quotes and placement.
This agent uses layout_policy=automatic: placement is executor-owned. Omit layout_direction.
Any supported direction you propose is audited and normalized, not a manual layout instruction.
Use relationship only for a source-supported three-stage DAG with one middle node.
For other topology use flow/network. Code computes stages without changing edges.
Only source_text is evidence; instructions/descriptions are NOT source evidence.
Use none for decorative or irrelevant pictures. A person's portrait needs an explicit
source-supported teaching purpose. Do not invent nodes, numbers, edges or causal claims.
For a new candidate, provide visuals. Use one main visual, or split complex content into
up to six ordered panels. Each panel must have a short title, teaching_goal, id (safe
identifier), and kind. Precise structure goes to SVG, never image generation.
""" + REPRESENTATION_RULES + """
constraint_source_ref selects source IDs for constraint_evidence; the displayed
constraint itself must still be a short exact excerpt, never a generated conclusion.
For multiple panels, every visual needs narration_span: an exact consecutive substring
of narration_text. In panel order these spans must concatenate to narration_text exactly,
including whitespace/punctuation, with no omissions or added words. Plan before TTS.
PREFER narration_refs:["narration-001",...] using narration_units instead of retyping
narration_span. Select consecutive IDs in original order, and partition all units once
across panels. The executor copies the exact text; never leave one panel's span empty.
For one visual omit narration_span, or copy the ENTIRE narration_text exactly.
The requested teaching_goal and full narration remain the scope; a spec cannot narrow them.
Every source-supported fact explicitly spoken in narration_text remains in scope, including
applications/examples. Do not omit those as irrelevant merely because a chosen diagram
focuses on a definition. Use additional panels or retained supports to cover them.
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
It uses the SAME top-level nodes and edges as flow/network. Every edge needs source_ref.
An edge's action/label must be supported by that quote; shared words are not entailment.
For create and structural_replacement, if page_context is supplied, include content_map,
an object keyed by EVERY
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
IDs may be noncontiguous: code keeps separate exact excerpts, never joins across gaps
or includes unselected intervening facts. Each excerpt stays within a selected contiguous span.
This applies to nodes, edges, image/none specs and coverage entries. Do not also write
evidence/source_evidence when using source_ref. Coverage fact_quotes may be omitted:
the tool inventories ALL original visible strings from page_context automatically;
you still must supply each element's decision, visual_refs and reason.
irrelevant_to_goal is for adjacent subtopics or decorative assets, even when true
elsewhere in the textbook. Explain the scope mismatch; never drop the teaching goal's
unique supported facts under this label. The screenshot reviewer must assess it.
When the selected visual_plan_contract allows composition, it may contain
{visual_ids,axis,horizontal_free,vertical_free}. Every visual must be included exactly
once. Pairing requires NO retained
body supports. Labels must remain at least 16px in the actual course page; if they
would shrink below that, use separate panels instead. Do not declare space free when
body elements occupy it. Composition is rendered and screenshot-reviewed, not a plan only.
For local updates, provide updates=[...] only when allowed by visual_plan_contract.
Select visual_id and optionally node_id, edge:{source,target}, or constraint:true.
No JSON pointer or /diagram layer is needed; the executor resolves the unique object.
Use set:{label:"...",source_ref:"source-001"} or remove:["detail"]. An explicit new
source_ref refreshes its old derived evidence unless you also supply an exact quote.
For an edge update use {visual_id:"main",edge:{source:"a",target:"b"},set:{label:"..."}}.
Use delete:true to remove an explicitly selected visual/node/edge; explicitly update
its relationships, coverage and complete narration partition in the same batch.
Coverage uses {element_id:"e2",set:{decision:"represented",source_ref:"source-001",
visual_refs:["main:a"],reason:"..."}}. To retain a support set ONLY decision:support
and reason. To replace a previous support explicitly give its new decision and proof.
Use object-addressed updates for local edits; do not send JSON-pointer changes.
Use complete replacement visuals when a coherent structural redesign is needed.
Never mix updates with full replacement fields. All edited fields remain gated.
Every graph node must have a source-supported edge; never leave ledger copies isolated.
Coverage targets are visual-id or visual-id:node-id. A relationship's nonempty rendered
constraint may be referenced as visual-id:@constraint; absent constraints are invalid.
Select IDs from the current candidate, never infer numeric indices from IDs.
Changing source_ref refreshes inherited derived quotes for both update interfaces.
Explicit quotes supplied in this batch remain checked, never discarded.
The executor supplies parent/reason automatically.
All unchanged fields remain intact; edited results still need full source and screenshot QA.
"""

UPDATE_RULES = """Revise the existing candidate in response to screenshot/validation feedback.
For ordinary corrections provide updates=[...] only. Never provide visuals or a full
replacement in this mode. Select IDs from previous_candidate.
layout_policy=automatic keeps graph placement executor-owned; do not revise layout_direction.
Use edit_contract for exact selectors and allowed fields; do not invent style/size/ID fields.
feedback identifies the latest execution error; latest_screenshot_review remains the visual
correction goal, bound to the revision it actually reviewed. Fix both without guessing IDs.
An update selects {visual_id,node_id?} or {visual_id,edge:{source,target}} or
{visual_id,constraint:true}; then set:{field:value}, remove:[field], or delete:true
(delete an explicitly selected visual/node/edge). If deleting a visual, partition ALL narration
across the remaining panels in the same batch; source/coverage/partition gates still apply.
The executor selects the diagram layer automatically.
For relationship constraint text, select {visual_id,constraint:true} and
set:{constraint:"short exact SOURCE excerpt"}.
Placement, equal card sizes, coordinates and automatic directions are executor-owned.
Do not guess style/width/height fields or change direction as a styling repair.
For visual fields, select just visual_id. Structural redesign may explicitly set that
visual's nodes/edges, preserving every required fact and coverage reference, only when
those fields are permitted by the current contract. This request's mode is authoritative;
never switch modes or send a full candidate when only updates are allowed.
For page content, use {element_id,set:{decision,reason,source_ref?,visual_refs?}}.
To retain a support use ONLY decision:support and reason. To replace a support explicitly
give its decision, source_ref, visual_refs and reason. Never edit original page_context.
Setting source_ref refreshes old derived evidence; explicit quotes in this batch are
never discarded. Use source_units IDs; no invented IDs or source claims.
Use narration_refs for narration_units IDs rather than retyping spans; partition the full
narration in order. An explicit narration_span must match these references exactly.
Do not change source_text, narration_text, original teaching_goal, or audit fields.
All source-supported facts explicitly spoken in the narration remain in scope, including
examples/applications. Do not invent a process from old unsupported storyboard text.
Keep labels concise and source-language consistent. Existing theme and readable type apply.
The changed candidate still passes full source, coverage, geometry and screenshot review.
"""

SCOPED_LABEL_RULES = """The screenshot reviewer requested one label correction.
Return VisualPlanV1 with exactly one update selecting repair_scope.target.selector and
set:{label:"replacement text"}. Preserve every other field, object, relationship,
source citation, narration partition and page structure. Do not return changes,
full visuals, remove, delete, or additional updates. The executor enforces this scope.
Keep the replacement source-grounded and readable; it still requires a new screenshot review.
"""

SCOPED_DETAIL_RULES = """The screenshot reviewer identified one unreadable node detail.
Return VisualPlanV1 with exactly one update selecting repair_scope.target.selector and
set:{detail:"replacement text"}. Preserve every other field, object, relationship,
source citation, narration partition and page structure. Do not return changes,
full visuals, remove, delete, or additional updates. The executor enforces this scope.
Keep the replacement source-grounded and readable; it still requires a new screenshot review.
"""

STRUCTURAL_REPAIR_RULES = """The screenshot reviewer identified a factual or missing-content
problem that requires a coherent redesign. Provide a complete replacement visuals array,
and content_map/composition/page_plan only when allowed and needed. Do not return updates,
changes, delete, or a mixture of patch and replacement fields. Preserve source-supported
facts, exact source references, the entire narration in order, and stable IDs where the
same objects remain. Choose any supported diagram kind that faithfully expresses the
teaching goal; do not invent edges merely to satisfy graph validation. The executor will
validate and screenshot-review the entire replacement as a new candidate.
"""

MISSING_PANEL_RULES = """The screenshot reviewer found a missing fact, but the existing
panel is otherwise accurate. Keep that panel's diagram unchanged. Provide only panel,
existing_narration_refs and panel_narration_refs. The panel is ONE new
source-grounded VisualSpec with a distinct ID, title and teaching_goal. Use source_ref IDs
for every claim and relationship; never invent an edge. Split narration_units into a
nonempty prefix for the existing panel and a nonempty suffix for the new panel, listing
every unit exactly once in original order. The executor copies the existing panel, assigns
exact narration spans, and makes two full-size course pages. Do not supply visuals,
updates, changes, composition, narration_span or narration_refs inside the new panel.
The complete replacement still undergoes all source, geometry and screenshot checks.
""" + REPRESENTATION_RULES


def structural_repair_requested(review: dict) -> bool:
    if not isinstance(review, dict):
        return False
    issues = review.get("issues")
    if isinstance(issues, list) and any(
        isinstance(issue, dict) and issue.get("category") in {
            "factual_error", "missing_content", "irrelevant_content",
        }
        for issue in issues
    ):
        return True
    checks = review.get("checks")
    return isinstance(checks, dict) and any(
        checks.get(key) is False for key in ("accuracy", "relevance", "completeness")
    )


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
    changes = []
    if "tool" in envelope and "name" in envelope:
        raise ValueError("tool call must use either tool or name, not both")
    if "tool" not in envelope and envelope.get("name") in {"create", "revise", "compose"}:
        envelope["tool"] = envelope.pop("name")
        changes.append("Normalized explicit tool name alias; arguments unchanged")
    if envelope.get("tool") not in {"create", "revise", "compose"}:
        raise ValueError("model must call create/revise/compose")
    if "arguments" not in envelope:
        fields = {key: value for key, value in envelope.items() if key != "tool"}
        allowed = {"visuals", "content_map", "page_plan", "composition", "visual_ids",
                   "axis", "horizontal_free", "vertical_free", "changes", "updates",
                   "parent", "reason"}
        if not fields or not set(fields).issubset(allowed):
            raise ValueError(
                "tool call needs an arguments object containing visual tool parameters"
            )
        envelope = {"tool": envelope["tool"], "arguments": fields}
        changes.append("Wrapped explicit top-level tool parameters in arguments; values unchanged")
    if not isinstance(envelope["arguments"], dict):
        raise ValueError("tool arguments must be an object")
    return envelope, changes


def normalize_visual_arguments(
    arguments: dict, *, page_context: list[dict] | None = None,
    automatic_layout: bool = False,
) -> tuple[dict, list[str]]:
    """Supply protocol metadata; never infer teaching content or relationships."""
    normalized = deepcopy(arguments)
    changes = []
    if automatic_layout:
        normalized, changes = renderer_graphs(normalized)
    normalized, semantic_changes = materialize_semantic_graphs(normalized)
    changes.extend(semantic_changes)
    specs = normalized.get("visuals")
    if page_context == []:
        # No old body exists to retain or replace. This is an executor fact,
        # not a semantic disposition for the model to invent. Raw intent stays
        # in raw_tool_request.json; all actual visual claims remain validated.
        normalized.pop("content_map", None)
        normalized["page_plan"] = {
            "support_element_ids": [], "replaces_element_ids": [], "coverage": [],
            "reason": "No existing body elements; source and full narration define the new page",
        }
        changes.append("Executor supplied empty replacement plan for an explicitly empty page")
    for spec in specs if isinstance(specs, list) else []:
        if not isinstance(spec, dict):
            continue
        if page_context == []:
            spec.pop("page_plan", None)
        if spec.get("kind") in KINDS and "schema_version" not in spec:
            spec["schema_version"] = GRAMMAR_VERSION
            changes.append(f"Supplied current grammar version for {spec.get('id')}")
        diagram = spec.get("diagram")
        if (
            spec.get("kind") == "relationship" and "title" not in spec
            and isinstance(diagram, dict) and isinstance(diagram.get("title"), str)
        ):
            spec["title"] = diagram.pop("title")
            changes.append(
                f"Moved explicit nested title to visual {spec.get('id')}; text unchanged"
            )
    normalized, layout_changes = materialize_layout(normalized, automatic_layout=automatic_layout)
    return normalized, changes + layout_changes


def revision_edit_base(parent: Path) -> dict:
    if (parent / "revision.json").exists():
        verify_revision(parent)
    else:
        verify_failure(parent)
        structural = parent / "structural-base.json"
        if structural.exists():
            return json.loads(structural.read_text(encoding="utf-8"))
    candidate = parent / "request.json"
    if not candidate.exists():
        candidate = parent / "raw_tool_request.json"
    base = (
        json.loads(candidate.read_text(encoding="utf-8"))["arguments"]
        if candidate.exists() else None
    )
    if base is not None and "changes" not in base and "updates" not in base:
        return base
    snapshot = parent / "edit_base.json"
    if snapshot.exists():
        failure = json.loads((parent / "failure.json").read_text(encoding="utf-8"))
        base = json.loads(snapshot.read_text(encoding="utf-8"))
        if digest(base) != failure.get("edit_base_sha256"):
            raise ValueError("failed patch edit base hash drift")
        return base
    raise ValueError("parent has no resolved visual arguments; send a full replacement")


def latest_parent_review(parent: Path) -> dict | None:
    """Find the closest screenshot review on a verified revision/failure chain."""
    seen = set()
    while parent is not None:
        identity = str(parent.resolve()).casefold()
        if identity in seen:
            raise RevisionIntegrityError("cyclic revision parent")
        seen.add(identity)
        review_path = parent / "review.json"
        if review_path.exists():
            return json.loads(review_path.read_text(encoding="utf-8"))
        revision_path = parent / "revision.json"
        record_path = revision_path if revision_path.exists() else parent / "failure.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        parent = Path(record["parent"]) if record.get("parent") else None
    return None


def expand_revision_changes(arguments: dict, *, unified_graphs=False) -> dict:
    if "changes" not in arguments and "updates" not in arguments:
        return deepcopy(arguments)
    if not arguments.get("parent"):
        raise ValueError("local changes need a parent revision")
    base = revision_edit_base(Path(arguments["parent"]))
    if unified_graphs and "updates" in arguments:
        arguments = renderer_updates(base, arguments)
    return (apply_object_updates(base, arguments) if "updates" in arguments
            else apply_changes(base, arguments))


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
    teaching_goal: str | None = None,
    automatic_layout: bool = False,
    repair_scope: dict | None = None,
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
    elif repair_scope is not None:
        raise ValueError("repair scope requires a revise parent")
    output_dir.mkdir(parents=True, exist_ok=False)
    _save(output_dir / "source.json", {"source_text": source, "sha256": digest(source)})
    _save(output_dir / "raw_tool_request.json", {"tool": tool, "arguments": arguments})
    structural_base_sha256 = None
    interface_changes = []
    edit_base_sha256 = None
    try:
        if tool == "revise" and repair_scope is None:
            reviewed = latest_parent_review(Path(arguments["parent"]))
            if reviewed is not None and (label_repair_requested(reviewed)
                                         or detail_repair_requested(reviewed)):
                protected_base = revision_edit_base(Path(arguments["parent"]))
                repair_scope = (label_repair_scope(protected_base, reviewed)
                                if label_repair_requested(reviewed)
                                else detail_repair_scope(protected_base, reviewed))
                if repair_scope is None:
                    raise ValueError("reviewed text target is ambiguous; refusing broad revise")
                repair_scope["base_sha256"] = digest(protected_base)
        if "changes" in arguments or "updates" in arguments:
            if tool != "revise":
                raise ValueError("local changes are only supported by revise")
            edit_base = revision_edit_base(Path(arguments["parent"]))
            edit_base_sha256 = digest(edit_base)
            _save(output_dir / "edit_base.json", edit_base)
            if requires_semantic_replacement(edit_base):
                raise ValueError(
                    'Unmaterialized semantic graph requires complete replacement visuals; '
                    'do not patch roles, owners or topology through local updates'
                )
            if repair_scope is not None:
                if (repair_scope.get("mode") not in {"label", "detail"}
                        or repair_scope.get("base_sha256") != edit_base_sha256):
                    raise ValueError(
                        f"{repair_scope.get('mode')} repair parent changed since screenshot review"
                    )
                (validate_label_repair if repair_scope["mode"] == "label"
                 else validate_detail_repair)(arguments, repair_scope)
            if automatic_layout and "updates" in arguments:
                adapted = renderer_updates(edit_base, arguments)
                if adapted != arguments:
                    interface_changes.append("Resolved unified graph fields to renderer objects")
                arguments = adapted
            arguments = (apply_object_updates(edit_base, arguments) if "updates" in arguments
                         else apply_changes(edit_base, arguments))
        elif repair_scope is not None:
            raise ValueError(f"scoped {repair_scope['mode']} repair requires object updates")
        arguments, protocol_changes = normalize_visual_arguments(
            arguments, page_context=page_context, automatic_layout=automatic_layout
        )
        check_structure(arguments)
        if automatic_layout:
            structural_base_sha256 = digest(arguments)
            _save(output_dir / "structural-base.json", arguments)
        arguments, narration_changes = materialize_narration_refs(arguments, narration_text)
        arguments, map_changes = materialize_content_map(arguments, page_context)
        arguments, normalizations = materialize_source_refs(arguments, source, page_context)
        normalizations = (interface_changes + protocol_changes + narration_changes
                          + map_changes + normalizations)
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
                "teaching_goal": teaching_goal,
                "layout_policy": "automatic" if automatic_layout else "preserve_manual",
            },
        )
        if (
            len(specs) == 1 and narration_text is not None
            and "narration_span" in specs[0]
            and specs[0]["narration_span"] != narration_text
        ):
            raise ValueError(
                "single visual narration_span must cover the entire narration_text exactly; "
                "omit the field for one visual, or partition ALL narration into multiple panels"
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
                    exact_evidence(edge.get("evidence"), source, limit=None,
                                   label="relationship edges need exact source evidence")
            elif spec.get("kind") in IMAGE_KINDS | {"none"}:
                if not spec.get("teaching_goal") or not spec.get("evidence"):
                    raise ValueError("images/abstentions need a teaching goal and evidence")
                exact_evidence(spec["evidence"], source, limit=None, label="image evidence")
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
            else (Path(arguments["parent"]) / "compiled/asset-checkpoint.json")
            if parent and (Path(arguments["parent"]) / "compiled/asset-checkpoint.json").exists()
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
            if any("narration_refs" in spec for spec in specs) and flattened != [
                spec["id"] for spec in specs
            ]:
                raise ValueError("composition order must preserve narration_refs identity order")
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
        revision["raw_tool_request_sha256"] = digest(
            json.loads((output_dir / "raw_tool_request.json").read_text(encoding="utf-8"))
        )
        revision["request_sha256"] = digest(
            json.loads((output_dir / "request.json").read_text(encoding="utf-8"))
        )
        _save(output_dir / "render-pending.json", revision)
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
                "structural_base_sha256": structural_base_sha256,
                "parent": str(Path(arguments["parent"]).resolve()) if parent else None,
                "parent_sha256": digest(parent) if parent else None,
            },
        )
        raise


def _source_svg_glyph_checks(page, path):
    """Measure actual browser glyph boxes, also when course HTML embeds SVG as img."""
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(path.resolve().as_uri())
    page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
    result = page.evaluate("""() => {
        const root=document.documentElement.getBoundingClientRect(), issues=[];
        const texts=Array.from(document.querySelectorAll('text'));
        for(const text of texts){
            const r=text.getBoundingClientRect();
            if(r.left<root.left-1||r.right>root.right+1||r.top<root.top-1||r.bottom>root.bottom+1)
                issues.push({type:'source_svg_text_overflow',text:text.textContent});
            const rect=text.closest('[data-node-id]')?.querySelector('rect');
            if(rect){const b=rect.getBoundingClientRect();
                if(r.left<b.left-1||r.right>b.right+1||r.top<b.top-1||r.bottom>b.bottom+1)
                    issues.push({type:'node_text_overflow',
                                 id:text.closest('[data-node-id]').dataset.nodeId});}
        }
        return {text_nodes:texts.length,
                nested_images:document.querySelectorAll('image').length,issues};
    }""")
    return {"scope": "SOURCE_SVG_BROWSER_GLYPHS_NOT_FINAL_VIDEO",
            "asset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **result}


def _asset_svg_glyph_checks(page, directory, asset, originals):
    path = directory / "compiled/assets" / asset["filename"]
    result = _source_svg_glyph_checks(page, path)
    if result["asset_sha256"] != asset["sha256"]:
        raise ValueError("SVG glyph inspection asset hash drift")
    members = asset.get("members")
    if not members:
        if result["nested_images"]:
            result["issues"].append({"type": "unmeasured_nested_svg_content"})
        return result
    if result["nested_images"] != len(members):
        result["issues"].append({"type": "composition_member_coverage_mismatch"})
    result["direct_text_nodes"] = result["text_nodes"]
    result["members"], result["unmeasured_raster_members"] = [], []
    lookup = {a["id"]: a for a in originals}
    for member in members:
        original = lookup.get(member["id"])
        if original is None or original["sha256"] != member["sha256"]:
            raise ValueError("SVG glyph inspection member binding drift")
        member_path = directory / "compiled/assets" / original["filename"]
        if hashlib.sha256(member_path.read_bytes()).hexdigest() != member["sha256"]:
            raise ValueError("SVG glyph inspection member asset hash drift")
        if member_path.suffix.lower() != ".svg":
            result["unmeasured_raster_members"].append(member["id"])
            continue
        checked = _source_svg_glyph_checks(page, member_path)
        checked["visual_id"] = member["id"]
        if checked["nested_images"]:
            checked["issues"].append({"type": "unmeasured_nested_svg_content"})
        result["members"].append(checked)
        result["text_nodes"] += checked["text_nodes"]
        result["issues"].extend({**issue, "member_visual_id": member["id"]}
                                for issue in checked["issues"])
    return result


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
                glyphs = (_asset_svg_glyph_checks(page, directory, asset, manifest["assets"])
                          if path.suffix == ".svg" else None)
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
                preview_stem = Path(asset['filename']).stem
                preview = directory / f"{preview_stem}.html"
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
                    if glyphs is not None:
                        issues.extend(deepcopy(glyphs["issues"]))
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
                    screenshot = directory / f"{preview_stem}-{width}.png"
                    page.screenshot(path=str(screenshot))
                    reports.append(
                        {
                            "visual_id": name,
                            "viewport": [width, height],
                            "screenshot": str(screenshot.resolve()),
                            "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                            "issues": issues,
                            "source_svg_glyph_checks": glyphs,
                        }
                    )
        finally:
            instance.close()
    _save(directory / "geometry.json", reports)
    return reports


class ReviewResponseError(ValueError):
    """A reviewer protocol failure is not evidence that a diagram needs editing."""


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
    support_ids = set((revision.get("page_plan") or {}).get("support_element_ids", []))
    retained_texts = [
        element["text"] for element in tool_request.get("page_context") or []
        if element.get("id") in support_ids and element.get("type") in {"text", "label", "badge"}
        and isinstance(element.get("text"), str) and element["text"].strip()
    ]
    fact_targets = (
        None if len(specs) == 1 and specs[0].get("kind") == "none" else
        build_review_targets(specs, tool_request.get("narration_text") or source,
                             retained_texts=retained_texts)
    )
    request = {
        "source_text": source,
        "source_units": source_units(source),
        "source_reference_policy": SOURCE_REFERENCE_POLICY,
        "specs": specs,
        "geometry": geometry,
        "page_context": tool_request.get("page_context"),
        "page_plan": revision.get("page_plan"),
        "composition": revision.get("composition"),
        "source_images": source_images,
        "narration_text": tool_request.get("narration_text"),
        "teaching_goal": tool_request.get("teaching_goal"),
        "relation_review_rules": RELATION_REVIEW_RULES,
        "instructions": COMPACT_RULES,
        "visible_fact_rules": VISIBLE_FACT_RULES,
    }
    compact_contract = build_review_contract(specs, fact_targets, revision.get("page_plan"))
    request["review_contract"] = compact_contract
    from textbook2video.research.visual_cache import merge_findings

    carry_path = directory / 'prior-review-findings.json'
    prior_report = (
        json.loads(carry_path.read_text(encoding='utf-8')) if carry_path.exists() else None
    )
    if prior_report:
        request['prior_findings_on_identical_pixels'] = prior_report
    _save(directory / "review-request.json", request)
    if not images:
        request["review_scope"] = "Review whether abstaining loses needed explanatory content."
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        remaining = min(timeout, deadline - time.monotonic())
        if remaining <= 0:
            raise ReviewResponseError("review protocol repair exceeded total review timeout")
        if attempt:
            _save(directory / "review-request-retry-1.json", request)
        kwargs = dict(model=model, temperature=0, max_tokens=4000, timeout=remaining)
        raw = (
            chat_with_images(json.dumps(request, ensure_ascii=False), images, **kwargs)
            if images else chat_with_system(json.dumps(request, ensure_ascii=False), **kwargs)
        )
        if time.monotonic() > deadline:
            response_file = "review-response.txt" if not attempt else "review-response-retry-1.txt"
            with (directory / response_file).open("x", encoding="utf-8") as stream:
                stream.write(raw)
            _save(directory / f"review-protocol-error-{attempt}.json", {
                "error": "review response arrived after total review deadline",
            })
            raise ReviewResponseError("review response arrived after total review deadline")
        try:
            return _save_review(
                directory, raw, geometry, model=model, has_images=bool(images),
                attempt=attempt, prior_report=prior_report,
                relation_specs=specs, relation_source=source,
                fact_targets=fact_targets,
                compact_contract=compact_contract,
            )
        except ValueError as exc:
            _save(directory / f"review-protocol-error-{attempt}.json", {"error": str(exc)})
            if attempt:
                raise ReviewResponseError(
                    f"review response invalid after one repair: {exc}"
                ) from exc
            try:
                prior_report = merge_findings([
                    prior_report, expand_review(_json(raw), compact_contract, partial=True)
                ])
            except ValueError:
                pass
            request["protocol_repair"] = {
                "error": str(exc), "previous_response": raw,
                "instruction": "Review the SAME unchanged images. Return complete valid JSON, "
                "including every review_contract target ID exactly once. "
                "Do not modify the diagram. "
                "Keep previously identified semantic issues and any rejection.",
            }
    raise AssertionError("unreachable review loop")


def _save_review(
    directory: Path, raw: str, geometry: list, *, model: str, has_images: bool,
    attempt: int = 0, prior_report: dict | None = None,
    relation_specs: list | None = None, relation_source: str = "",
    fact_targets: dict | None = None,
    compact_contract: dict | None = None,
) -> dict:
    response_file = "review-response.txt" if not attempt else "review-response-retry-1.txt"
    with (directory / response_file).open("x", encoding="utf-8") as stream:
        stream.write(raw)
    report = _json(raw)
    if compact_contract is not None:
        report = expand_review(report, compact_contract)
    revision = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
    scores = report.get("scores", {})
    if (
        not isinstance(report.get("verdict"), str)
        or report.get("verdict") not in {"ACCEPT", "REVISE", "REJECT"}
        or not isinstance(scores, dict)
        or set(scores) != {"accuracy", "relevance", "readability", "composition"}
        or any(type(v) is not int or not 0 <= v <= 4 for v in scores.values())
    ):
        raise ValueError("invalid visual review response")
    if not isinstance(report.get("issues"), list) or not report.get("reason"):
        raise ValueError("review requires specific issues and reason")
    if relation_specs is not None:
        report, source_materializations = materialize_relation_audit(report, relation_source)
        scores = report["scores"]
        validate_relation_audit(report, relation_specs, relation_source)
        report["relation_source_materializations"] = source_materializations
        findings = relation_findings(report)
        if findings:
            report["issues"].extend(issue for issue in findings if issue not in report["issues"])
            if report["verdict"] != "REJECT":
                report["verdict"] = "REVISE"
            checks = report.setdefault("checks", {})
            if not isinstance(checks, dict):
                raise ValueError("review checks must be an object")
            if any(i["category"] == "factual_error" for i in findings):
                checks["accuracy"] = False
            if any(i["category"] == "missing_content" for i in findings):
                checks["completeness"] = False
    if fact_targets is not None:
        validate_fact_audit(report, fact_targets, relation_specs)
        findings = fact_audit_findings(report)
        if findings:
            report["issues"].extend(issue for issue in findings if issue not in report["issues"])
            if report["verdict"] != "REJECT":
                report["verdict"] = "REVISE"
            checks = report.setdefault("checks", {})
            if not isinstance(checks, dict):
                raise ValueError("review checks must be an object")
            if any(i["category"] == "factual_error" for i in findings):
                checks["accuracy"] = False
            if any(i["category"] == "missing_content" for i in findings):
                checks["completeness"] = False
    page_plan = revision.get("page_plan") or {}
    if prior_report:
        # Protocol repair reviews the SAME pixels; it may complete the envelope,
        # but cannot erase an already observed coverage disagreement.
        expected_coverage = {
            item["element_id"]: {
                "represented": "covered", "unsupported_in_source": "unsupported",
                "irrelevant_to_goal": "irrelevant",
            }[item["decision"]]
            for item in page_plan.get("coverage", [])
        }
        prior_coverage = prior_report.get("coverage", [])
        conflicts = []
        for item in prior_coverage if isinstance(prior_coverage, list) else []:
            if (
                isinstance(item, dict)
                and isinstance(item.get("element_id"), str)
                and item["element_id"] in expected_coverage
                and isinstance(item.get("verdict"), str)
                and item["verdict"] in {"covered", "unsupported", "irrelevant", "missing"}
                and item["verdict"] != expected_coverage[item["element_id"]]
            ):
                conflicts.append(deepcopy(item))
        if conflicts:
            report["prior_coverage_conflicts"] = conflicts
            if report["verdict"] != "REJECT":
                report["verdict"] = "REVISE"
        prior_checks = prior_report.get("checks")
        if isinstance(prior_checks, dict):
            checks = report.get("checks")
            if not isinstance(checks, dict):
                checks = {}
            for name, value in prior_checks.items():
                if value is False:
                    checks[name] = False
            report["checks"] = checks
        prior_scores = prior_report.get("scores")
        if isinstance(prior_scores, dict):
            for name, score in prior_scores.items():
                if name in scores and type(score) is int and 0 <= score <= 4:
                    scores[name] = min(scores[name], score)
        prior_issues = prior_report.get("issues", [])
        for issue in prior_issues if isinstance(prior_issues, list) else []:
            if issue not in report["issues"]:
                report["issues"].append(issue)
        if prior_report.get("verdict") == "REJECT":
            report["verdict"] = "REJECT"
        elif prior_report.get("verdict") == "REVISE" and report["verdict"] == "ACCEPT":
            report["verdict"] = "REVISE"
    replaced = set(page_plan.get("replaces_element_ids", []))
    if replaced:
        coverage = report.get("coverage", [])
        if (
            not isinstance(coverage, list)
            or len(coverage) != len(replaced)
            or any(not isinstance(item, dict) for item in coverage)
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
                if report["verdict"] != "REJECT":
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
            "response_file": response_file,
            "protocol_repairs": attempt,
        }
    )
    _save(directory / "review.json", report)
    return report


class RevisionIntegrityError(ValueError):
    """Preserved execution evidence has changed; never ask a model to repair it."""


def verify_failure(directory: Path, seen: set[str] | None = None) -> dict:
    try:
        return _verify_failure(directory, seen)
    except RevisionIntegrityError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise RevisionIntegrityError(f"failed revision integrity failure: {error}") from error


def _verify_failure(directory: Path, seen: set[str] | None = None) -> dict:
    seen = set() if seen is None else seen
    identity = str(directory.resolve()).casefold()
    if identity in seen:
        raise ValueError("cyclic revision parent")
    seen.add(identity)
    source = json.loads((directory / "source.json").read_text(encoding="utf-8"))
    failure = json.loads((directory / "failure.json").read_text(encoding="utf-8"))
    structural = directory / "structural-base.json"
    if bool(failure.get("structural_base_sha256")) != structural.exists():
        raise ValueError("failed structural base missing or unexpectedly present")
    if structural.exists():
        structural_value = json.loads(structural.read_text(encoding="utf-8"))
        if digest(structural_value) != failure["structural_base_sha256"]:
            raise ValueError("failed structural base hash drift")
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
    try:
        _verify_revision(directory, _seen)
    except RevisionIntegrityError:
        raise
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise RevisionIntegrityError(f"revision integrity failure: {error}") from error


def _verify_revision(directory: Path, _seen: set[str] | None = None) -> None:
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
    review_policy: str = "strict",
    resume_from: Path | None = None,
    cache_context: dict | None = None,
) -> Path:
    """Bounded agent loop; revisions are immutable and failed attempts survive."""
    from textbook2video.research.visual_cache import (
        artifact_hashes,
        input_binding,
        read_run,
        recover_candidate,
    )
    from textbook2video.research.visual_review_policy import POLICIES, review_disposition

    if review_policy not in POLICIES:
        raise ValueError("review_policy must be strict or development")
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
        "teaching_goal": teaching_goal,
        "review_model": review_model or model,
        "max_iterations": max_iterations,
        "planning_timeout": planning_timeout,
        "planning_response_format": "json_object",
        "review_timeout": review_timeout,
        "history": history,
        "accepted_revision": None,
        "usable_revision": None,
        "review_policy": review_policy,
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
                Path(__file__).with_name("visual_object_edits.py"),
                Path(__file__).with_name("visual_panel_repair.py"),
                Path(__file__).with_name("visual_relation_semantics.py"),
                Path(__file__).with_name("visual_fact_audit.py"),
                Path(__file__).with_name("visual_compact_review.py"),
                Path(__file__).with_name("visual_semantic_graph.py"),
                Path(__file__).with_name("visual_model_interface.py"),
                Path(__file__).with_name("exact_source_excerpts.py"),
                Path(__file__).with_name("visual_narration_refs.py"),
                Path(__file__).with_name("visual_review_policy.py"),
                Path(__file__).with_name("visual_content_map.py"),
            )
        },
    }
    binding = input_binding(
        source,
        teaching_goal,
        model=model,
        review_model=review_model,
        theme=theme,
        browser=browser,
        allow_images=allow_images,
        page_context=page_context,
        narration_text=narration_text,
        review_policy=review_policy,
        cache_context=cache_context,
    )
    state["input_binding"] = binding
    feedback = None
    incumbent_score = -1
    patience = 0
    revision_only = False
    try:
        if resume_from is not None:
            old = read_run(resume_from, binding)
            history.extend(deepcopy(old["history"]))
            state["resumed_from"] = str(Path(resume_from).resolve())
            state["resumed_run_sha256"] = hashlib.sha256(Path(resume_from).read_bytes()).hexdigest()
            seen.update(e["state_sha256"] for e in history if e.get("state_sha256"))
            if history:
                last = history[-1]
                previous = Path(last["revision"])
                feedback = last.get("review") or {
                    "verdict": "REVISE",
                    "validation_error": last.get("error", "Retry the failed candidate stage"),
                    **({"edit_error": last["edit_error"]} if "edit_error" in last else {}),
                }
                revision_only = any("review" in e for e in history)
                partial = next(
                    (
                        previous / "compiled" / name
                        for name in ("visual_assets.json", "asset-checkpoint.json")
                        if (previous / "compiled" / name).exists()
                    ),
                    None,
                )
                retry_compilation = (
                    "review" not in last
                    and (previous / "request.json").exists()
                    and partial is not None
                    and any(
                        a.get("status") == "IMAGE_GENERATION_FAILED"
                        for a in json.loads(partial.read_text(encoding="utf-8"))["assets"]
                    )
                )
                if (
                    (previous / "revision.json").exists()
                    and "review" not in last
                    or (previous / "render-pending.json").exists()
                    and not (previous / "revision.json").exists()
                    or retry_compilation
                ):
                    directory = output_dir / "recovery-00"
                    entry = {
                        **deepcopy(last),
                        "revision": str(directory.resolve()),
                        "status": "ATTEMPTING",
                        "recovered_from": str(previous),
                    }
                    entry.pop("review_sha256", None)
                    history.append(entry)
                    if (
                        not (previous / "revision.json").exists()
                        and not (previous / "render-pending.json").exists()
                    ):
                        arguments = json.loads(
                            (previous / "request.json").read_text(encoding="utf-8")
                        )["arguments"]
                        arguments.update(
                            parent=str(previous), reason="Retry compilation using preserved assets"
                        )
                        dispatch(
                            "revise",
                            arguments,
                            source=source,
                            output_dir=directory,
                            theme=theme,
                            browser=browser,
                            allow_images=allow_images,
                            page_context=page_context,
                            narration_text=narration_text if narration_text is not None else source,
                            teaching_goal=teaching_goal,
                            automatic_layout=True,
                        )
                    else:
                        recover_candidate(previous, directory, browser=browser)
                    review = _agent_review(
                        directory, model=review_model or model, timeout=review_timeout
                    )
                    entry.update(
                        status=review["verdict"], review=review, review_sha256=digest(review)
                    )
                    record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
                    disposition = review_disposition(
                        review, record.get("geometry", []), record.get("page_plan")
                    )
                    entry["disposition"] = disposition
                    if (
                        disposition["strict_approved"]
                        or review_policy == "development"
                        and disposition["draft_usable"]
                    ):
                        state.update(
                            status="MODEL_REVIEWED_PENDING_HUMAN"
                            if disposition["strict_approved"]
                            else "DRAFT_WITH_WARNINGS_PENDING_HUMAN",
                            accepted_revision=str(directory.resolve())
                            if disposition["strict_approved"]
                            else None,
                            usable_revision=str(directory.resolve()),
                            warnings=disposition["warnings"],
                        )
                        return output_dir / "run.json"
                    if review["verdict"] == "REJECT":
                        state["status"] = "STOPPED_REVIEW_REJECTED"
                        return output_dir / "run.json"
                    feedback, revision_only = review, True
        for index in range(max_iterations):
            previous_dir = Path(history[-1]["revision"]) if history else None
            request = {
                "source_text": source,
                "source_units": source_units(source),
                "source_reference_policy": SOURCE_REFERENCE_POLICY,
                "relation_semantics": RELATION_RULES,
                "semantic_graph_contract": SEMANTIC_GRAPH_RULES,
                "relation_questions": relation_audit_contract()["questions"],
                "visible_fact_rules": VISIBLE_FACT_RULES,
                "narration_text": narration_text if narration_text is not None else source,
                "narration_units": narration_units(
                    narration_text if narration_text is not None else source
                ),
                "teaching_goal": teaching_goal,
                "catalog": {**CATALOG, "relationship":
                            "Three-stage directed graph with one middle node; "
                            "use the same top-level nodes/edges as other graphs."},
                "page_context": page_context,
                "feedback": feedback,
                "layout_policy": "automatic",
                "previous_candidate": (
                    planner_view(
                        history[-1].get("resolved_arguments", history[-1].get("arguments")),
                        unified_graphs=True,
                    )
                    if history
                    else None
                ),
            }
            candidate = request["previous_candidate"]
            if isinstance(candidate, dict):
                request["edit_contract"] = model_edit_contract(candidate)
            request["latest_screenshot_review"] = next(
                (
                    {"revision": item["revision"], "review_sha256": item.get("review_sha256"),
                     "review": deepcopy(item["review"])}
                    for item in reversed(history) if "review" in item
                ),
                None,
            )
            repair_scope = None
            if (revision_only and isinstance(candidate, dict)
                    and request["latest_screenshot_review"] and previous_dir is not None):
                parent_base = revision_edit_base(previous_dir)
                reviewed = request["latest_screenshot_review"]["review"]
                repair_scope = (label_repair_scope(parent_base, reviewed)
                                if label_repair_requested(reviewed)
                                else detail_repair_scope(parent_base, reviewed))
                if repair_scope is not None:
                    repair_scope["base_sha256"] = digest(parent_base)
                    repair_scope["review_sha256"] = request[
                        "latest_screenshot_review"
                    ]["review_sha256"]
                elif (label_repair_requested(reviewed) or detail_repair_requested(reviewed)):
                    state["status"] = "STOPPED_REPAIR_TARGET_UNRESOLVED"
                    state["repair_target_error"] = (
                        "Screenshot feedback named text but did not identify one "
                        "unique existing editable object; the reviewed candidate is preserved"
                    )
                    break
            semantic_recovery = requires_semantic_replacement(candidate)
            structural_repair = semantic_recovery or (
                revision_only and request["latest_screenshot_review"] is not None
                and structural_repair_requested(request["latest_screenshot_review"]["review"])
            )
            reviewed_base = (
                revision_edit_base(Path(request["latest_screenshot_review"]["revision"]))
                if structural_repair and request["latest_screenshot_review"] else None
            )
            additive_repair = (
                structural_repair and request['latest_screenshot_review'] is not None
                and not semantic_recovery and previous_dir is not None
                and can_append_missing_panel(
                    request["latest_screenshot_review"]["review"],
                    reviewed_base,
                    narration_text if narration_text is not None else source,
                )
            )
            if repair_scope:
                request["repair_scope"] = repair_scope
            elif additive_repair:
                request["repair_mode"] = "append_missing_panel"
                request["previous_candidate"] = planner_view(reviewed_base, unified_graphs=True)
                request["edit_contract"] = model_edit_contract(request["previous_candidate"])
            elif structural_repair:
                request["repair_mode"] = "structural_replacement"
            if semantic_recovery:
                request.pop('edit_contract', None)
                request['recovery_contract'] = (
                    'The previous semantic graph failed before becoming editable renderer '
                    'objects. Return a complete VisualPlanV1 replacement candidate; the '
                    'executor owns operation and revision metadata. Updates cannot repair '
                    'its roles, missing owners or topology. '
                    'Do not invent referenced nodes: include source-supported entities '
                    'or remove unsupported declarations. Recheck ALL roles and endpoints.'
                )
            if revision_only or semantic_recovery:
                request["phase"] = "revise_existing_visual"
                request["representation_rules"] = REPRESENTATION_RULES
            plan_mode = (
                f"scoped_{repair_scope['mode']}" if repair_scope else
                "append_missing_panel" if additive_repair else
                "structural_replacement" if structural_repair else
                "updates" if revision_only else "full_candidate"
            )
            request["visual_plan_contract"] = visual_plan_contract(plan_mode)
            _save(output_dir / f"model-request-{index}.json", request)
            raw = chat_with_system(
                json.dumps(request, ensure_ascii=False),
                system_prompt=(VISUAL_PLAN_PROTOCOL_RULES + "\n" + (
                               SCOPED_LABEL_RULES
                               if repair_scope and repair_scope["mode"] == "label" else
                               SCOPED_DETAIL_RULES if repair_scope else
                               MISSING_PANEL_RULES if additive_repair else
                               request['recovery_contract'] + REPRESENTATION_RULES
                               if semantic_recovery else
                               STRUCTURAL_REPAIR_RULES if structural_repair else
                               UPDATE_RULES if revision_only else PLAN_RULES)),
                model=model,
                temperature=0,
                max_tokens=6000,
                timeout=planning_timeout,
                extra_body={"response_format": {"type": "json_object"}},
            )
            with (output_dir / f"model-response-{index}.txt").open("x", encoding="utf-8") as stream:
                stream.write(raw)
            try:
                plan, envelope_changes = parse_visual_plan_response(
                    raw, plan_mode,
                )
                tool = "create" if previous_dir is None else "revise"
                arguments = plan
                if additive_repair:
                    arguments = expand_missing_panel(
                        arguments, reviewed_base,
                        narration_text if narration_text is not None else source,
                    )
                    envelope_changes.append(
                        "Expanded source-grounded additive panel; preserved reviewed diagram"
                    )
                envelope = {"tool": tool, "arguments": arguments}
                replacement_allowed = {
                    "visuals", "content_map", "composition", "page_plan", "parent", "reason",
                } | ({"page_plan"} if additive_repair else set())
                if revision_only and (
                    envelope["tool"] != "revise"
                    or not ({"visuals"} if structural_repair else
                            {"updates"}).intersection(envelope["arguments"])
                    or set(envelope["arguments"]) - (
                        replacement_allowed
                        if structural_repair else
                        {"updates", "parent", "reason"}
                    )
                ):
                    raise ValueError(
                        "semantic screenshot repair requires complete replacement visuals"
                        if structural_repair else
                        "after screenshot feedback call revise with updates only"
                    )
                if repair_scope:
                    if (previous_dir is None or digest(revision_edit_base(previous_dir))
                            != repair_scope["base_sha256"]):
                        raise ValueError(
                            "scoped text repair parent changed since screenshot review"
                        )
                    (validate_label_repair if repair_scope["mode"] == "label"
                     else validate_detail_repair)(envelope["arguments"], repair_scope)
                elif structural_repair and (
                    envelope["tool"] != "revise"
                    or not isinstance(envelope["arguments"].get("visuals"), list)
                    or set(envelope["arguments"]) - replacement_allowed
                ):
                    raise ValueError(
                        "semantic screenshot repair requires complete replacement visuals"
                    )
            except (ValueError, TypeError) as exc:
                directory = output_dir / f"revision-{index:02}"
                directory.mkdir(exist_ok=False)
                _save(directory / "source.json", {"source_text": source, "sha256": digest(source)})
                feedback = {
                    "verdict": "REVISE",
                    "validation_error": f"Return valid VisualPlanV1 JSON: {exc}",
                }
                details = getattr(exc, "details", None)
                if details is not None:
                    feedback["edit_error"] = deepcopy(details)
                parse_failure = {"status": "FAILED_PRESERVED", **feedback}
                if revision_only or semantic_recovery:
                    previous_args = (revision_edit_base(previous_dir) if previous_dir is not None
                                     else request["previous_candidate"])
                    _save(directory / "edit_base.json", previous_args)
                    parse_failure["edit_base_sha256"] = digest(previous_args)
                if previous_dir is not None:
                    previous = previous_dir
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
                        **({"edit_error": deepcopy(details)} if details is not None else {}),
                        **(
                            {"resolved_arguments": deepcopy(request["previous_candidate"])}
                            if revision_only or semantic_recovery
                            else {}
                        ),
                    }
                )
                continue
            _save(
                output_dir / f"model-envelope-{index}.json",
                {
                    "envelope": envelope,
                    "normalizations": envelope_changes,
                },
            )
            arguments = envelope["arguments"]
            directory = output_dir / f"revision-{index:02}"
            tool = "create" if previous_dir is None else "revise"
            if previous_dir is not None:
                arguments.update(
                    {
                        "parent": str(previous_dir),
                        "reason": json.dumps(feedback, ensure_ascii=False),
                    }
                )
            specs = arguments.get("visuals")
            try:
                canonical_args, _ = normalize_visual_arguments(
                    expand_revision_changes(arguments, unified_graphs=True),
                    page_context=page_context,
                    automatic_layout=True,
                )
                canonical_args, _ = materialize_narration_refs(
                    canonical_args, narration_text if narration_text is not None else source
                )
                canonical_args, _ = materialize_content_map(canonical_args, page_context)
                canonical_args, _ = materialize_source_refs(canonical_args, source, page_context)
            except RevisionIntegrityError:
                raise
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
                    "unresolved_updates": arguments.get("updates") if not canonical_specs else None,
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
                    teaching_goal=teaching_goal,
                    automatic_layout=True,
                    repair_scope=repair_scope,
                )
                entry["resolved_arguments"] = json.loads(
                    (directory / "request.json").read_text(encoding="utf-8")
                )["arguments"]
                review = _agent_review(
                    directory, model=review_model or model, timeout=review_timeout
                )
            except RevisionIntegrityError:
                raise
            except ReviewResponseError as exc:
                entry.update({"status": "REVIEW_PROTOCOL_FAILED", "error": str(exc)})
                state["status"] = "STOPPED_REVIEW_PROTOCOL"
                break
            except ValueError as exc:
                entry.update({"status": "FAILED_PRESERVED", "error": str(exc)})
                details = getattr(exc, "details", None)
                if details is not None:
                    entry["edit_error"] = deepcopy(details)
                if (directory / "request.json").exists():
                    entry["resolved_arguments"] = json.loads(
                        (directory / "request.json").read_text(encoding="utf-8")
                    )["arguments"]
                elif (directory / "structural-base.json").exists():
                    entry["resolved_arguments"] = json.loads(
                        (directory / "structural-base.json").read_text(encoding="utf-8")
                    )
                elif (directory / "edit_base.json").exists():
                    entry["resolved_arguments"] = json.loads(
                        (directory / "edit_base.json").read_text(encoding="utf-8")
                    )
                feedback = {"verdict": "REVISE", "validation_error": str(exc)}
                if details is not None:
                    feedback["edit_error"] = deepcopy(details)
                continue
            entry.update(
                {"status": review["verdict"], "review": review, "review_sha256": digest(review)}
            )
            revision_only = True
            record = json.loads((directory / "revision.json").read_text(encoding="utf-8"))
            disposition = review_disposition(
                review, record.get("geometry", []), record.get("page_plan")
            )
            entry["disposition"] = disposition
            score = sum(review["scores"].values())
            patience = patience + 1 if score <= incumbent_score else 0
            incumbent_score = max(incumbent_score, score)
            if disposition["strict_approved"]:
                state.update(
                    {
                        "status": "MODEL_REVIEWED_PENDING_HUMAN",
                        "accepted_revision": str(directory.resolve()),
                        "usable_revision": str(directory.resolve()),
                    }
                )
                break
            if review_policy == "development" and disposition["draft_usable"]:
                state.update(
                    {
                        "status": "DRAFT_WITH_WARNINGS_PENDING_HUMAN",
                        "usable_revision": str(directory.resolve()),
                        "warnings": disposition["warnings"],
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
        state["artifact_hashes"] = artifact_hashes(output_dir)
        _save(output_dir / "run.json", state)
    return output_dir / "run.json"


def _agent_review(directory, *, model, timeout):
    from litellm import (
        APIConnectionError,
        APIError,
        InternalServerError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
    )

    from textbook2video.pipeline.review_health import ReviewServiceUnavailable

    try:
        return review_revision(directory, model=model, timeout=timeout)
    except (
        APIError,
        APIConnectionError,
        InternalServerError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
        TimeoutError,
        ConnectionError,
    ) as error:
        raise ReviewServiceUnavailable(
            f"Review service failed ({type(error).__name__}); batch stopped"
        ) from None


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
