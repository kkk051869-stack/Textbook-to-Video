from textbook2video.math_render import html_with_math, replace_latex_in_html_text


def test_inline_latex_becomes_offline_mathml_and_prose_stays_escaped() -> None:
    rendered = html_with_math(r"概率是 $P(X)=\frac{1}{2}$，而 <tag> 只是文本。")
    assert '<span class="t2v-math t2v-math-inline">' in rendered
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML"' in rendered
    assert "&lt;tag&gt;" in rendered
    assert r"\frac" not in rendered


def test_display_latex_becomes_block_mathml() -> None:
    rendered = html_with_math(r"$$E=mc^2$$")
    assert '<div class="t2v-math t2v-math-display">' in rendered
    assert 'display="block"' in rendered


def test_invalid_latex_falls_back_without_breaking_html() -> None:
    rendered = html_with_math(r"坏公式 $\frac{$")
    assert rendered == r"坏公式 $\frac{$"


def test_llm_html_formula_is_converted_but_script_is_left_untouched() -> None:
    source = r'<p>$x^2$</p><script>const source = "$x^2$";</script>'
    rendered = replace_latex_in_html_text(source)
    assert "<math" in rendered
    assert 'const source = "$x^2$";' in rendered
