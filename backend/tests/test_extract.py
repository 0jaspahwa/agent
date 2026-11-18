"""H2: amendment text from PDF, DOCX, text, Markdown or typing."""
import io
import zipfile

import pytest

from amendments.extract import ExtractError, extract_text, typed_text
from amendments.simple_pdf import text_pdf

TEXT = ["Corvo Engineering Pvt Ltd: Procurement Policy Amendment A-9", "Effective: 1 December 2026",
        "1. Clause 5.4 (Spot PO). The spot limit is at or below INR 1,50,000 (was below 2,00,000)."]


def docx(paragraphs):
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>' +
           "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs) + "</w:body></w:document>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_pdf_text_is_extracted():
    text = extract_text("A-9.pdf", text_pdf(TEXT))
    assert "Effective: 1 December 2026" in text and "at or below INR 1,50,000" in text


def test_a_multi_page_pdf_keeps_every_page():
    lines = [f"line {n}" for n in range(120)]
    text = extract_text("long.pdf", text_pdf(lines))
    assert "line 0" in text and "line 119" in text


def test_a_pdf_without_text_asks_for_the_text_to_be_pasted():
    with pytest.raises(ExtractError, match="no extractable text.*Paste"):
        extract_text("scan.pdf", text_pdf([]))


def test_a_broken_pdf_is_refused_plainly():
    with pytest.raises(ExtractError, match="could not be read"):
        extract_text("broken.pdf", b"%PDF-1.4 this is not really a pdf")


def test_docx_text_is_extracted_in_paragraph_order():
    assert extract_text("A-9.docx", docx(TEXT)).splitlines() == TEXT


@pytest.mark.parametrize("name, data", [
    ("A-9.txt", "\n".join(TEXT).encode()),
    ("A-9.md", ("# " + "\n".join(TEXT)).encode("utf-8-sig")),
    ("A-9", "\r\n".join(TEXT).encode("cp1252")),
])
def test_plain_text_and_markdown(name, data):
    text = extract_text(name, data)
    assert "Effective: 1 December 2026" in text and "\r" not in text


@pytest.mark.parametrize("name, data, message", [
    ("old.doc", b"\xd0\xcf\x11\xe0 legacy word", "Save it as PDF, DOCX"),
    ("bad.docx", b"PK not a zip", "not a readable Word"),
    ("empty.txt", b"   \n ", "empty"),
])
def test_unreadable_documents_are_refused_with_a_plain_message(name, data, message):
    with pytest.raises(ExtractError, match=message):
        extract_text(name, data)


def test_typed_text_is_always_accepted_unless_empty():
    assert typed_text("  Spot limit 1.5 lakh from 1 Dec.\r\n") == "Spot limit 1.5 lakh from 1 Dec."
    with pytest.raises(ExtractError):
        typed_text("   ")
