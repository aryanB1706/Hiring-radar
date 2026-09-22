from app.core.text import clean_text, content_hash, html_to_text, normalize_for_hash


def test_html_is_stripped_but_paragraphs_and_entities_survive() -> None:
    html = 'Acme | R&amp;D<p>Remote &#x2F; US<p>Apply: <a href="https://a.example/x">here</a>'
    text = html_to_text(html)
    assert text == "Acme | R&D\n\nRemote / US\n\nApply: here (https://a.example/x)"


def test_link_target_is_not_repeated_when_it_is_the_link_text() -> None:
    text = html_to_text('<a href="https://a.example/x" rel="nofollow">https://a.example/x</a>')
    assert text == "https://a.example/x"


def test_script_like_markup_never_reaches_the_text() -> None:
    assert "<" not in html_to_text("<b>bold</b><br>line<i>two</i>")


def test_clean_text_is_idempotent_and_collapses_blank_runs() -> None:
    once = clean_text("a   b \n\n\n\n c\t d")
    assert once == "a b\n\nc d"
    assert clean_text(once) == once


def test_content_hash_ignores_case_and_whitespace_but_not_words() -> None:
    assert content_hash("We are  Hiring\n a Dev") == content_hash("we are hiring a dev")
    assert content_hash("we are hiring a dev") != content_hash("we are hiring two devs")
    assert normalize_for_hash("  A\tB ") == "a b"
