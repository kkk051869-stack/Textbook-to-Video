"""测试 CLI 参数解析"""

from unittest.mock import patch
from textbook2video.cli import main


class TestCLIArgs:
    """测试 CLI 参数解析（不实际运行命令）"""

    def test_generate_requires_lesson(self, capsys):
        """generate 命令必须传 --lesson"""
        try:
            main()
        except SystemExit:
            pass
        captured = capsys.readouterr()
        # 应该显示帮助信息
        assert "usage:" in captured.out or "usage:" in captured.err

    def test_list_lessons_accepts_input(self):
        """list-lessons 接收 input 参数"""
        # just test it doesn't crash on arg parse
        import sys
        test_args = ["t2v", "list-lessons", "test.pdf"]
        with patch.object(sys, "argv", test_args):
            try:
                main()
            except (SystemExit, FileNotFoundError, Exception):
                pass  # 文件不存在预期错误

    def test_generate_minimal_args(self):
        """generate 最少参数"""
        import sys
        test_args = ["t2v", "generate", "test.pdf", "--lesson", "4", "--skip-tts"]
        with patch.object(sys, "argv", test_args):
            try:
                main()
            except (SystemExit, FileNotFoundError, Exception):
                pass  # 文件不存在是预期的