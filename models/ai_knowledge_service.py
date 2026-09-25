# -*- coding: utf-8 -*-
"""
Knowledge Base helpers for Otomater AI (Phase 4).

Kept dependency-free where possible (stdlib only) so a fresh Odoo install
can ingest .txt/.md/.csv files and website URLs with zero extra packages.
PDF/DOCX/XLSX extraction uses optional third-party libraries if they
happen to be installed (PyPDF2, python-docx, openpyxl) and raises a clear,
actionable error if they're not - it never fails silently or half-extracts.

Similarity search is plain Python (no numpy/pgvector dependency) so it
works portably on any Odoo install. This is fine for a knowledge base of
up to a few thousand chunks; for larger corpora, swapping in pgvector
(PostgreSQL extension) for the cosine-similarity search is the natural
next optimization - noted in the README, not implemented here to avoid
requiring a Postgres extension most self-hosted Odoo installs won't have
enabled.
"""

import re
import urllib.request

from odoo.exceptions import UserError

_WHITESPACE_RE = re.compile(r"\s+")


def extract_text_from_binary(filename, data_bytes):
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()

    if ext in ("txt", "md", "csv", "log", "json"):
        return data_bytes.decode("utf-8", errors="ignore")

    if ext == "pdf":
        try:
            import io

            from PyPDF2 import PdfReader
        except ImportError as exc:
            raise UserError(
                "Reading PDF files requires the 'PyPDF2' Python package. "
                "Install it with: pip install PyPDF2 --break-system-packages"
            ) from exc
        reader = PdfReader(io.BytesIO(data_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    if ext == "docx":
        try:
            import io

            import docx
        except ImportError as exc:
            raise UserError(
                "Reading DOCX files requires the 'python-docx' Python package. "
                "Install it with: pip install python-docx --break-system-packages"
            ) from exc
        document = docx.Document(io.BytesIO(data_bytes))
        return "\n".join(p.text for p in document.paragraphs)

    if ext in ("xlsx", "xls"):
        try:
            import io

            import openpyxl
        except ImportError as exc:
            raise UserError(
                "Reading Excel files requires the 'openpyxl' Python package. "
                "Install it with: pip install openpyxl --break-system-packages"
            ) from exc
        workbook = openpyxl.load_workbook(io.BytesIO(data_bytes), data_only=True)
        lines = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(", ".join(cells))
        return "\n".join(lines)

    # Best-effort fallback for unrecognized extensions.
    try:
        return data_bytes.decode("utf-8", errors="ignore")
    except Exception as exc:
        raise UserError(
            "Don't know how to extract text from '.%s' files." % (ext or "?")
        ) from exc


def extract_text_from_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": "OtomaterAI/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            raw = response.read()
    except Exception as exc:
        raise UserError("Could not fetch '%s': %s" % (url, exc)) from exc

    html = raw.decode("utf-8", errors="ignore")
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        # No BeautifulSoup available - fall back to a crude regex strip.
        text = re.sub(r"(?is)<script.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?</style>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)

    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def chunk_text(text, chunk_size=1200, overlap=150):
    """Fixed-size character chunking with overlap. Simple and predictable -
    good enough for semantic search over policy docs/FAQs/manuals."""
    text = _WHITESPACE_RE.sub(" ", text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = end - overlap if end - overlap > start else end
    return chunks


def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
