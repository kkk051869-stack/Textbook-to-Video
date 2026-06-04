"""TTS 容错测试：单段失败不拖垮整批，返回长度恒等于段数且同序（mock edge-tts）。"""

from pathlib import Path

import pytest

from textbook2video.pipeline import narrator


class _FakeCommunicate:
    """模拟 edge_tts.Communicate：文本含 'FAIL' 则 save 抛异常，否则写入字节。"""

    def __init__(self, text, voice=None, rate=None):
        self.text = text

    async def save(self, path):
        if "FAIL" in self.text:
            raise RuntimeError("模拟 TTS 失败")
        Path(path).write_bytes(b"fake-audio-bytes")


@pytest.fixture(autouse=True)
def _patch_tts(monkeypatch):
    monkeypatch.setattr(narrator.edge_tts, "Communicate", _FakeCommunicate)

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(narrator.asyncio, "sleep", _no_sleep)


def test_all_segments_succeed(tmp_path):
    out = narrator.generate_audio(["一", "二", "三"], output_dir=str(tmp_path))
    assert [p.name for p in out] == ["s1.mp3", "s2.mp3", "s3.mp3"]
    assert all(p.exists() and p.stat().st_size > 0 for p in out)


def test_one_failing_segment_does_not_abort_batch(tmp_path):
    # 第 2 段失败，其余应正常；返回长度仍为 3、同序
    out = narrator.generate_audio(["一", "二FAIL", "三"], output_dir=str(tmp_path))
    assert [p.name for p in out] == ["s1.mp3", "s2.mp3", "s3.mp3"]
    assert out[0].exists() and out[0].stat().st_size > 0
    assert out[2].exists() and out[2].stat().st_size > 0
    # 失败段：路径仍返回（供下游按 0 时长降级），但文件未生成
    assert not out[1].exists()


def test_empty_text_uses_placeholder_not_crash(tmp_path):
    out = narrator.generate_audio(["", "   ", "正常"], output_dir=str(tmp_path))
    assert len(out) == 3
    # 空文本走占位文案，仍能生成音频
    assert out[0].exists() and out[0].stat().st_size > 0
    assert out[1].exists()


def test_returns_one_path_per_segment(tmp_path):
    segs = [f"seg{i}" for i in range(7)]
    out = narrator.generate_audio(segs, output_dir=str(tmp_path))
    assert len(out) == len(segs)
    assert [p.name for p in out] == [f"s{i + 1}.mp3" for i in range(7)]
