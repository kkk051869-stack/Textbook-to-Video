import pytest

from textbook2video.math_render import svg_label_math
from textbook2video.research.relationship_visuals import _wrap


@pytest.mark.parametrize(
    "label", ["Predicted Frame", "Reconstructed Residual", "Motion Estimation"]
)
def test_short_english_words_are_not_cut_across_lines(label):
    lines = _wrap(label, 10)
    assert "".join(lines) == label
    assert all(word in line for word, line in zip(label.split(), lines, strict=True))


@pytest.mark.parametrize(
    "source,display",
    [
        (r"\bar{x}_t", "x̄ₜ"),
        (r"\hat{r}_t", "r̂ₜ"),
        (r"\hat{x}_{t-1}", "x̂ₜ₋₁"),
    ],
)
def test_svg_label_math_preserves_accent_and_subscript(source, display):
    assert svg_label_math(source) == display


@pytest.mark.parametrize("source", [r"\hat{x}_theta", r"\hat{x}_{q}", r"\frac{x}{y}",
                                   r"\hat{x}_{t}^{2}", r"\hat{x} ^{2}"])
def test_unsupported_math_is_not_partially_rewritten(source):
    assert svg_label_math(source) == source


def test_literal_code_and_formula_wrapping_preserves_tex_and_indentation():
    value = r"    result = \hat{x}_t"
    assert _wrap(value, 45, math_labels=False) == [value]
