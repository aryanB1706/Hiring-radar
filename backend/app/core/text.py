import hashlib
import re
import unicodedata

from bs4 import BeautifulSoup

MAX_TEXT_CHARS = 20_000

_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """Strip HTML to readable text. Paragraph/line breaks are kept; link targets are kept when
    they differ from the link text (so an emailed or shortened link is not lost)."""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if href not in anchor.get_text():
            anchor.append(f" ({href})")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for paragraph in soup.find_all("p"):
        paragraph.insert_before("\n\n")
        paragraph.insert_after("\n\n")
    for block in soup.find_all(["pre", "li", "div"]):
        block.insert_before("\n")
        block.insert_after("\n")
    return clean_text(soup.get_text())


def clean_text(text: str) -> str:
    """Tidy whitespace while keeping paragraph structure. Idempotent."""
    text = unicodedata.normalize("NFKC", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def normalize_for_hash(text: str) -> str:
    """The form used for duplicate detection: case-folded, all whitespace collapsed."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode()).hexdigest()
