import json

from textbook2video.eval.calibration import GoldUnit, calibrate, load_gold_units, parse_args, write_calibration_report


def test_calibration_reports_binary_metrics_and_pending_labels(tmp_path):
    units = [
        GoldUnit("u1", "visual_vlm", "case", auto_label="issue", human_label="issue"),
        GoldUnit("u2", "visual_vlm", "case", auto_label="issue", human_label="no_issue"),
        GoldUnit("u3", "visual_vlm", "case", auto_label="no_issue", human_label="no_issue"),
        GoldUnit("u4", "visual_vlm", "case", auto_label=None, human_label=None, abstained=True),
        GoldUnit("u5", "visual_vlm", "case", auto_label="issue", human_label=None),
    ]
    report = calibrate(units)
    metrics = report["evaluators"]["visual_vlm"]
    assert report["pending_human_label_count"] == 2
    assert metrics["labeled_count"] == 3
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 0.666667
    assert metrics["agreement"] == 0.666667
    assert metrics["cohen_kappa"] == 0.4
    assert metrics["abstain_rate"] == 0.2
    assert report["metadata"]["human_labels_are_never_inferred"] is True
    output = tmp_path / "calibration"
    write_calibration_report(output, report)
    persisted = json.loads((output / "calibration_report.json").read_text(encoding="utf-8"))
    assert persisted["units"][4]["human_label"] is None
    assert (output / "calibration_report.md").exists()


def test_calibration_keeps_evaluator_label_spaces_separate():
    report = calibrate([
        GoldUnit("u1", "pedagogy", "case", auto_label="ordering_good", human_label="ordering_good"),
        GoldUnit("u2", "pedagogy", "case", auto_label="ordering_bad", human_label="ordering_good"),
    ])
    metrics = report["evaluators"]["pedagogy"]
    assert metrics["label_space"] == "multiclass"
    assert metrics["precision"] is None
    assert metrics["confusion_matrix"]["ordering_good"]["ordering_bad"] == 1


def test_calibration_input_loader_and_cli_parse(tmp_path):
    source = tmp_path / "gold.json"
    source.write_text(json.dumps({"units": [{"unit_id": "u", "evaluator": "x", "case_id": "c"}]}), encoding="utf-8")
    assert load_gold_units(source)[0].unit_id == "u"
    args = parse_args(["--gold", str(source), "--out", str(tmp_path / "out")])
    assert args.gold == source
