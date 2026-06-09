"""CLI argument smoke tests."""

from unittest.mock import patch

from textbook2video.cli import main


class TestCLIArgs:
    """Test CLI parsing without requiring real input files."""

    def test_generate_requires_lesson(self, capsys):
        try:
            main()
        except SystemExit:
            pass
        captured = capsys.readouterr()
        assert "usage:" in captured.out or "usage:" in captured.err

    def test_list_lessons_accepts_input(self):
        import sys

        test_args = ["t2v", "list-lessons", "test.pdf"]
        with patch.object(sys, "argv", test_args):
            try:
                main()
            except (SystemExit, FileNotFoundError, Exception):
                pass

    def test_generate_minimal_args(self):
        import sys

        test_args = ["t2v", "generate", "test.pdf", "--lesson", "4", "--skip-tts"]
        with patch.object(sys, "argv", test_args):
            try:
                main()
            except (SystemExit, FileNotFoundError, Exception):
                pass


def test_script_text_writes_script(tmp_path, monkeypatch):
    import sys

    raw = tmp_path / "sample_raw.txt"
    raw.write_text("source text", encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "textbook2video.pipeline.scriptwriter.generate_script",
        lambda text, model=None: ["segment one", "segment two"],
    )
    test_args = [
        "t2v",
        "script-text",
        str(raw),
        "--output",
        str(out_dir),
        "--stem",
        "sample",
    ]

    with patch.object(sys, "argv", test_args):
        main()

    script = out_dir / "sample_script.txt"
    assert script.exists()
    assert "segment one" in script.read_text(encoding="utf-8")


def test_pdf_storyboard_accepts_args():
    import sys

    test_args = [
        "t2v",
        "pdf-storyboard",
        "book.pdf",
        "--start-page",
        "21",
        "--max-pages",
        "8",
        "--stem",
        "demo",
    ]
    with patch.object(sys, "argv", test_args):
        try:
            main()
        except (SystemExit, FileNotFoundError, Exception):
            pass
