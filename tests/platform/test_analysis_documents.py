from __future__ import annotations

from io import BytesIO
import zlib
from zipfile import ZipFile

import pytest

from qym_platform.services.document_extractor import (
    MAX_DOCX_DOCUMENT_XML_BYTES,
    MAX_PDF_DECOMPRESSED_BYTES,
    MAX_REFERENCE_DOCUMENT_CHARS,
    MAX_REFERENCE_UPLOAD_BYTES,
    DocumentExtractionError,
    UnsupportedDocumentError,
    extract_document_text,
)


def test_extract_plain_text_normalizes_and_sanitizes_filename() -> None:
    document = extract_document_text(
        "../requirements.md",
        b"# Requirements\r\n\r\n\r\n\r\nResponses must cite sources.\r\n",
    )

    assert document.name == "requirements.md"
    assert document.content == "# Requirements\n\n\nResponses must cite sources."
    assert document.characters == len(document.content)
    assert document.truncated is False


def test_extract_docx_reads_paragraph_text() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>First requirement</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second requirement</w:t></w:r></w:p>
              </w:body>
            </w:document>""",
        )

    document = extract_document_text("rubric.docx", output.getvalue())

    assert "First requirement" in document.content
    assert "Second requirement" in document.content
    assert document.content.index("First requirement") < document.content.index(
        "Second requirement"
    )


def test_extract_docx_rejects_unsafe_expansion_before_reading_member() -> None:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml", b"x" * (MAX_DOCX_DOCUMENT_XML_BYTES + 1)
        )

    with pytest.raises(DocumentExtractionError, match="exceeds the extraction limit"):
        extract_document_text("oversized.docx", output.getvalue())


def test_extract_docx_rejects_unsafe_compression_ratio() -> None:
    output = BytesIO()
    with ZipFile(output, "w", compression=8) as archive:
        archive.writestr("word/document.xml", b"x" * 100_000)

    with pytest.raises(DocumentExtractionError, match="unsafe compression ratio"):
        extract_document_text("compressed.docx", output.getvalue())


def test_extract_pdf_reads_page_text() -> None:
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Length 57 >>\nstream\nBT /F1 12 Tf 72 720 Td (Reference requirement text) Tj ET\nendstream\nendobj\n",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )

    document = extract_document_text("requirements.pdf", bytes(pdf))

    assert document.content == "Reference requirement text"


def test_extract_pdf_rejects_expanded_content_stream() -> None:
    expanded = b"q " * (MAX_PDF_DECOMPRESSED_BYTES // 2 + 1)
    compressed = zlib.compress(expanded)
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        (
            f"4 0 obj\n<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n".encode()
            + compressed
            + b"\nendstream\nendobj\n"
        ),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )

    with pytest.raises(DocumentExtractionError, match="exceeds the extraction limit"):
        extract_document_text("bomb.pdf", bytes(pdf))


def test_extract_html_omits_script_and_style_content() -> None:
    document = extract_document_text(
        "guide.html",
        b"<style>.secret { color: red; }</style><h1>Guide</h1>"
        b"<script>ignore()</script><p>Use facts.</p>",
    )

    assert "Guide" in document.content
    assert "Use facts." in document.content
    assert "secret" not in document.content
    assert "ignore" not in document.content


def test_extract_document_enforces_type_size_and_prompt_limits() -> None:
    with pytest.raises(UnsupportedDocumentError, match="Unsupported document type"):
        extract_document_text("archive.zip", b"not a supported document")

    with pytest.raises(DocumentExtractionError, match="10 MB"):
        extract_document_text("large.txt", b"x" * (MAX_REFERENCE_UPLOAD_BYTES + 1))

    document = extract_document_text(
        "long.txt",
        b"x" * (MAX_REFERENCE_DOCUMENT_CHARS + 20),
    )
    assert document.truncated is True
    assert document.characters == MAX_REFERENCE_DOCUMENT_CHARS
    assert len(document.content) == MAX_REFERENCE_DOCUMENT_CHARS
