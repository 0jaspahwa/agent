"""H2: the text of an amendment, read deterministically (no LLM) from an upload or from typed text.

PDF (pypdf), DOCX (the document XML, standard library only), plain text and Markdown. A PDF without
extractable text (a scan) is refused with a request to paste the text; pasting always works.
"""
import io
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ExtractError(ValueError):
    pass


def _decode(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _pdf(data):
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise ExtractError(f"This PDF could not be read ({exc}). Paste the amendment text instead.") from exc
    if len(re.sub(r"\s", "", text)) < 20:
        raise ExtractError("This PDF has no extractable text (it may be a scan). Paste the amendment text instead.")
    return text


def _docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ExtractError("This is not a readable Word (.docx) file. Paste the amendment text instead.") from exc
    paragraphs = []
    for p in root.iter(f"{W}p"):
        parts = []
        for node in p.iter():
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def extract_text(filename, data):
    """The amendment text from an uploaded file. Raises ExtractError with a plain message."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        text = _pdf(data)
    elif name.endswith(".docx") or data[:2] == b"PK":
        text = _docx(data)
    elif name.endswith((".doc", ".rtf", ".odt", ".pages")):
        raise ExtractError("This file type cannot be read. Save it as PDF, DOCX or plain text, or paste the text.")
    else:
        text = _decode(data)
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ExtractError("The document is empty. Paste the amendment text instead.")
    return text


def typed_text(text):
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise ExtractError("Type or paste the amendment text.")
    return text
