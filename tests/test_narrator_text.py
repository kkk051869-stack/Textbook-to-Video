from textbook2video.pipeline.narrator import normalize_tts_text


def test_normalize_tts_text_expands_standalone_technical_abbreviations():
    assert normalize_tts_text("CPU 与 GPU 协同，AI 可以使用 NPU。") == (
        "C P U 与 G P U 协同，A I 可以使用 N P U。"
    )


def test_normalize_tts_text_does_not_change_words_containing_abbreviations():
    assert normalize_tts_text("GPUKernel 和 CPU2 不应被拆开。") == "GPUKernel 和 CPU2 不应被拆开。"
