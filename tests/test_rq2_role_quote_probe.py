import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_rq2_role_quote_probe as probe


def case(tmp_path):
    probe.auto.write(tmp_path / "tasks.json", [{"id": "p1"}, {"id": "p2"}])
    probe.auto.write(tmp_path / "candidates.json", [])
    shutil.copy2(
        probe.ROOT / "src/textbook2video/research/binding_methods.py",
        tmp_path / "binding_methods.py",
    )
    probe.auto.write(
        tmp_path / "input_manifest.json",
        {p.name: probe.auto.sha(p) for p in tmp_path.iterdir() if p.is_file()},
    )


def test_transport_failure_stops_second_request_and_prevents_resume(tmp_path, monkeypatch):
    case(tmp_path)
    calls = []

    def failed(prop, *args, **kwargs):
        calls.append(prop["id"])
        probe.auto.write(tmp_path / "run/calls.json", [{"status": "FAILED"}])
        raise RuntimeError("Transport fixture")

    monkeypatch.setattr(probe.auto.binding, "bind_source_conditioned", failed)
    with pytest.raises(RuntimeError, match="Transport fixture"):
        probe.execute(tmp_path)
    assert calls == ["p1"]
    with pytest.raises(FileExistsError):
        probe.execute(tmp_path)
    assert calls == ["p1"]


def test_changed_frozen_inputs_stop_before_any_model_call(tmp_path):
    case(tmp_path)
    probe.auto.write(tmp_path / "tasks.json", [])
    with pytest.raises(ValueError, match="Frozen input changed"):
        probe.execute(tmp_path)
    assert not (tmp_path / "run").exists()
