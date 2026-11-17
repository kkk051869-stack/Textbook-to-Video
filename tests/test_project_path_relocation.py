"""Offline checks for the directory migration helper; no experiment execution."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/resolve_project_paths.py"
SPEC = importlib.util.spec_from_file_location("resolve_project_paths", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_transitive_moves_and_boundary():
    moves = [
        {"from": "D:/old/research", "to": "D:/project/.worktrees/current"},
        {
            "from": "D:/project/.worktrees/current/.local/runs/case",
            "to": "D:/project/.local/runs/case",
        },
    ]
    assert (
        MODULE.relocate(r"D:\old\research\.local\runs\case\a.json", moves)
        == "D:/project/.local/runs/case/a.json"
    )
    assert MODULE.relocate("D:/old/research-other/a.json", moves) == "D:/old/research-other/a.json"


def test_json_view_preserves_statuses_hashes_and_original():
    original = {
        "path": "D:/old/input.png",
        "status": "USED_WITH_WARNING",
        "research_condition": None,
        "sha256": "abc",
        "events": [{"status": "EXECUTED"}],
    }
    result = MODULE.relocate(original, [{"from": "D:/old", "to": "D:/project"}])
    assert result == {**original, "path": "D:/project/input.png"}
    assert original["path"] == "D:/old/input.png"


def test_script_copy_maps_literal_slashes_without_prefix_collision():
    text = (
        "ROOT=Path(r'D:\\old\\tree')\nOTHER='D:/old/tree-extra'\nRUN='D:/old/tree/.local/runs/a'\n"
    )
    result = MODULE.relocated_script(
        text, [{"from": "D:/old/tree", "to": "D:/project/.worktrees/current"}]
    )
    assert "r'D:\\project\\.worktrees\\current'" in result
    assert "'D:/old/tree-extra'" in result
    assert "'D:/project/.worktrees/current/.local/runs/a'" in result


def test_html_encoded_file_uri_and_relative_asset():
    old = Path(__file__).resolve().parent / "old tree"
    new = old.parent / "new tree"
    text = '<img src="' + old.as_uri() + '/figure.svg"><img src="images/keep.svg">'
    result = MODULE.relocated_script(text, [{"from": str(old), "to": str(new)}])
    assert new.as_uri() + "/figure.svg" in result
    assert 'src="images/keep.svg"' in result


def test_html_cli_preserves_original_bytes_and_refuses_overwrite(tmp_path, monkeypatch):
    source = tmp_path / "original.html"
    raw = b'<!doctype html>\r\n<img src="images/keep.svg">\r\n'
    source.write_bytes(raw)
    moves = tmp_path / "moves.json"
    moves.write_text("[]", encoding="utf-8")
    output = tmp_path / "original.relocated.html"
    monkeypatch.setattr(
        "sys.argv", ["paths", "--map", str(moves), "--html", str(source), "--output", str(output)]
    )
    MODULE.main()
    assert source.read_bytes() == raw
    assert output.read_bytes().endswith(raw + b"\n")
    with pytest.raises(FileExistsError):
        MODULE.main()


def test_json_cli_cannot_overwrite_frozen_input(tmp_path, monkeypatch):
    source = tmp_path / "manifest.json"
    raw = b'{"status":"USED_WITH_WARNING","research_condition":null}'
    source.write_bytes(raw)
    moves = tmp_path / "moves.json"
    moves.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["paths", "--map", str(moves), "--json", str(source), "--output", str(source)]
    )
    with pytest.raises(FileExistsError):
        MODULE.main()
    assert source.read_bytes() == raw
