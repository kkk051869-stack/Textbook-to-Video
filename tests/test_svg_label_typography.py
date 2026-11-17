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


@pytest.mark.parametrize('source,display', [
    (r'Predicted Frame ($\bar{x}_t$)', 'Predicted Frame (x̄ₜ)'),
    (r'$\hat{x}_t = \hat{r}_t + \bar{x}_t$', 'x̂ₜ = r̂ₜ + x̄ₜ'),
    (r'Motion Estimation ($t+1$)', 'Motion Estimation (t+1)'),
    (r'Used by the $(t+1)$th frame', 'Used by the (t+1)th frame'),
    (r'\(x_t\)', 'xₜ'),
    (r'\[\hat{x}_{t-1}\]', 'x̂ₜ₋₁'),
    (r'$$x_t = 2$$', 'xₜ = 2'),
])
def test_complete_supported_math_spans_have_no_delimiters(source, display):
    assert svg_label_math(source) == display


@pytest.mark.parametrize('source', [
    r'$\frac{x}{y} + \hat{x}_t$', r'$\hat{x}_{q}$', r'$x_t^2$',
    r'$\hat{x}_theta$', r'$cost$', r'Price \$5$',
])
def test_unsupported_delimited_expression_is_preserved_whole(source):
    assert svg_label_math(source) == source


@pytest.mark.parametrize('source,display', [(r'$\hat{x}_t$', 'x̂ₜ'),
                                            (r'$\hat{x}_{t-1}$', 'x̂ₜ₋₁')])
def test_svg_wrap_keeps_accent_and_subscript_attached_to_variable(source, display):
    lines = _wrap('A ' + source, 2)
    assert ''.join(lines) == 'A ' + display
    assert any(display in line for line in lines)


def test_literal_formula_path_keeps_math_delimiters():
    assert _wrap(r'$\hat{x}_t$', 40, math_labels=False) == [r'$\hat{x}_t$']


def test_standalone_equation_uses_label_size_without_rewriting_spec():
    from copy import deepcopy
    from xml.etree import ElementTree as ET

    from textbook2video.research.visual_grammar import GRAMMAR_VERSION, render_visual

    spec = {'id': 'equation', 'kind': 'flow', 'title': 'Reconstruction',
            'schema_version': GRAMMAR_VERSION, 'teaching_goal': 'Show the reconstruction formula',
            'nodes': [{'id': 'frame', 'label': 'Frame',
                       'detail': r'$\hat{x}_t = \hat{r}_t + \bar{x}_t$', 'evidence': 'Source'},
                      {'id': 'next', 'label': 'Next frame', 'evidence': 'Source'}],
            'edges': [{'source': 'frame', 'target': 'next', 'evidence': 'Source'}]}
    before = deepcopy(spec)
    root = ET.fromstring(render_visual(spec))
    texts = root.findall('.//{http://www.w3.org/2000/svg}text')
    math = next(t for t in texts if '=' in ''.join(t.itertext()))
    label = next(t for t in texts if t.text == 'Frame')
    assert float(math.get('font-size')) == float(label.get('font-size'))
    assert '$' not in ''.join(root.itertext())
    assert spec == before
