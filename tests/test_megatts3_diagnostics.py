from pathlib import Path


def test_megatts3_diagnostic_script_is_importable():
    script = Path(__file__).parents[1] / "scripts" / "diagnose_megatts3.py"
    source = script.read_text(encoding="utf-8")
    compile(source, str(script), "exec")
    assert "stage=init" in source
    assert "stage=preprocess" in source
    assert "stage=forward" in source
