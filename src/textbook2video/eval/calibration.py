"""Local evaluator calibration metrics with explicit pending labels."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .report import write_json
from .schemas import validate_with_contract

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


@dataclass
class GoldUnit:
    unit_id: str
    evaluator: str
    case_id: str
    location: dict[str, Any] = field(default_factory=dict)
    auto_label: Any = None
    human_label: Any = None
    abstained: bool = False
    evidence: Any = None
    notes: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldUnit":
        required = ("unit_id", "evaluator", "case_id")
        missing = [name for name in required if not str(value.get(name) or "").strip()]
        if missing:
            raise ValueError(f"gold unit missing required fields: {', '.join(missing)}")
        location = value.get("location")
        if not isinstance(location, dict):
            location = {}
        return cls(
            unit_id=str(value["unit_id"]),
            evaluator=str(value["evaluator"]),
            case_id=str(value["case_id"]),
            location=location,
            auto_label=value.get("auto_label"),
            human_label=value.get("human_label"),
            abstained=bool(value.get("abstained", False)),
            evidence=value.get("evidence"),
            notes=value.get("notes"),
        )


def load_gold_units(path: str | Path) -> list[GoldUnit]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_units = value.get("units") if isinstance(value, dict) else value
    if not isinstance(raw_units, list):
        raise ValueError("calibration input must be a list or an object with a units array")
    return [GoldUnit.from_dict(item) for item in raw_units if isinstance(item, dict)]


def _label(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    aliases = {
        "1": "positive", "true": "positive", "yes": "positive", "issue": "positive",
        "problem": "positive", "fail": "positive", "failed": "positive", "error": "positive",
        "0": "negative", "false": "negative", "no": "negative", "no_issue": "negative",
        "ok": "negative", "pass": "negative", "passed": "negative", "valid": "negative",
    }
    return aliases.get(normalized, normalized)


def _kappa(human: list[str], auto: list[str]) -> float | None:
    if not human:
        return None
    observed = sum(left == right for left, right in zip(human, auto)) / len(human)
    human_counts = Counter(human)
    auto_counts = Counter(auto)
    labels = set(human_counts) | set(auto_counts)
    expected = sum(
        human_counts[label] * auto_counts[label] for label in labels
    ) / (len(human) * len(auto))
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return round((observed - expected) / (1 - expected), 6)


def _evaluator_metrics(units: list[GoldUnit]) -> dict[str, Any]:
    eligible = [
        unit for unit in units
        if unit.human_label is not None and unit.auto_label is not None and not unit.abstained
    ]
    human = [_label(unit.human_label) for unit in eligible]
    auto = [_label(unit.auto_label) for unit in eligible]
    pairs = [(h, a) for h, a in zip(human, auto) if h is not None and a is not None]
    human = [pair[0] for pair in pairs]
    auto = [pair[1] for pair in pairs]
    confusion: dict[str, dict[str, int]] = {}
    for expected, predicted in pairs:
        confusion.setdefault(expected, {})[predicted] = confusion.setdefault(expected, {}).get(predicted, 0) + 1
    labels = set(human) | set(auto)
    binary = labels <= {"positive", "negative"}
    tp = sum(expected == predicted == "positive" for expected, predicted in pairs)
    fp = sum(expected == "negative" and predicted == "positive" for expected, predicted in pairs)
    fn = sum(expected == "positive" and predicted == "negative" for expected, predicted in pairs)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    abstain_count = sum(unit.abstained or unit.auto_label is None for unit in units)
    pending_count = sum(unit.human_label is None for unit in units)
    return {
        "unit_count": len(units),
        "labeled_count": len(pairs),
        "pending_human_label_count": pending_count,
        "abstain_count": abstain_count,
        "abstain_rate": round(abstain_count / len(units), 6) if units else None,
        "agreement": round(sum(expected == predicted for expected, predicted in pairs) / len(pairs), 6) if pairs else None,
        "cohen_kappa": _kappa(human, auto),
        "confusion_matrix": confusion,
        "label_space": "binary" if binary else "multiclass",
        "precision": round(precision, 6) if binary and precision is not None else None,
        "recall": round(recall, 6) if binary and recall is not None else None,
        "f1": round(f1, 6) if binary and f1 is not None else None,
    }


def calibrate(units: list[GoldUnit]) -> dict[str, Any]:
    """Compute per-evaluator metrics without changing any unit labels."""

    groups: dict[str, list[GoldUnit]] = {}
    for unit in units:
        groups.setdefault(unit.evaluator, []).append(unit)
    pending = sum(unit.human_label is None for unit in units)
    report = {
        "schema_version": "textbookeval-calibration-v0.1",
        "unit_count": len(units),
        "pending_human_label_count": pending,
        "evaluators": {
            name: _evaluator_metrics(group) for name, group in sorted(groups.items())
        },
        "units": [asdict(unit) for unit in units],
        "metadata": {
            "human_labels_are_never_inferred": True,
            "eligible_definition": "human_label and auto_label present, abstained=false",
        },
    }
    validate_with_contract(report, "calibration_report.schema.json", contracts_dir=_CONTRACTS_DIR)
    return report


def render_calibration_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TextbookEval Evaluator Calibration",
        "",
        f"- Units: {report['unit_count']}",
        f"- Pending human labels: {report['pending_human_label_count']}",
        "- Pending human labels are preserved; no labels are inferred.",
        "",
        "| Evaluator | Labeled | Pending | Abstain Rate | Precision | Recall | F1 | Agreement | Kappa |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, value in report["evaluators"].items():
        lines.append(
            f"| {name} | {value['labeled_count']} | {value['pending_human_label_count']} | "
            f"{value['abstain_rate']} | {value['precision']} | {value['recall']} | "
            f"{value['f1']} | {value['agreement']} | {value['cohen_kappa']} |"
        )
    return "\n".join(lines) + "\n"


def write_calibration_report(output_dir: str | Path, report: dict[str, Any]) -> tuple[Path, Path]:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output / "calibration_report.json", report)
    markdown_path = output / "calibration_report.md"
    markdown_path.write_text(render_calibration_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute local evaluator calibration metrics")
    parser.add_argument("--gold", required=True, type=Path, help="Gold unit JSON")
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = calibrate(load_gold_units(args.gold))
    write_calibration_report(args.out, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
