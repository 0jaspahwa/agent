"""A tiny PDF writer (standard library only) for making amendment documents for tests and the H9 rehearsal.
Text only, Helvetica, A4, one or more pages. Not used by the app itself."""

LINES_PER_PAGE = 48


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def text_pdf(lines):
    """Bytes of a PDF showing the given lines of text (no text at all if lines is empty)."""
    pages = [lines[i:i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)] or [[]]
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for page_lines in pages:
        stream = "BT /F1 11 Tf 56 790 Td 15 TL " + " ".join(f"({_escape(l)}) '" for l in page_lines) + " ET" if page_lines else ""
        objects.append(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
        content = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {content} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
