"""Safe text extraction for analyzer reference-document uploads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


MAX_REFERENCE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_DOCUMENT_CHARS = 40_000

SUPPORTED_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".docx",
    ".html",
    ".htm",
    ".json",
    ".log",
    ".markdown",
    ".md",
    ".pdf",
    ".rst",
    ".text",
    ".txt",
    ".yaml",
    ".yml",
}


class DocumentExtractionError(ValueError):
    """Raised when an uploaded document cannot be converted to prompt text."""


class UnsupportedDocumentError(DocumentExtractionError):
    """Raised when an uploaded document has an unsupported extension."""


@dataclass(frozen=True)
class ExtractedDocument:
    """Text and metadata returned after document extraction."""

    name: str
    content: str
    characters: int
    truncated: bool


class _VisibleHtmlTextParser(HTMLParser):
    """Extract visible prose from an HTML document without external packages."""

    _BLOCK_TAGS = {
        "article",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "p",
        "section",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentExtractionError("The document text encoding could not be read.")


def _extract_html(data: bytes) -> str:
    parser = _VisibleHtmlTextParser()
    try:
        parser.feed(_decode_text(data))
    except Exception as exc:
        raise DocumentExtractionError("The HTML document could not be read.") from exc
    return "".join(parser.parts)


def _extract_docx(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise DocumentExtractionError("The DOCX file is invalid or damaged.") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocumentExtractionError("The DOCX document content could not be read.") from exc

    parts: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in {"br", "cr"}:
            parts.append("\n")
        elif tag == "p":
            parts.append("\n")
    return "".join(parts)


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is installed in production
        raise DocumentExtractionError("PDF extraction support is not installed.") from exc

    try:
        reader = PdfReader(BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise DocumentExtractionError(
            "The PDF could not be read. Scanned PDFs need OCR before upload."
        ) from exc


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return re.sub(r"\n{4,}", "\n\n\n", normalized).strip()


def extract_document_text(filename: str, data: bytes) -> ExtractedDocument:
    """Extract bounded prompt text from a supported uploaded document."""
    safe_name = Path(filename or "document").name[:255] or "document"
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise UnsupportedDocumentError(
            f"Unsupported document type '{extension or 'unknown'}'. Supported types: {supported}."
        )
    if len(data) > MAX_REFERENCE_UPLOAD_BYTES:
        raise DocumentExtractionError("The document exceeds the 10 MB upload limit.")
    if not data:
        raise DocumentExtractionError("The uploaded document is empty.")

    if extension == ".pdf":
        text = _extract_pdf(data)
    elif extension == ".docx":
        text = _extract_docx(data)
    elif extension in {".html", ".htm"}:
        text = _extract_html(data)
    else:
        text = _decode_text(data)

    text = _normalize_text(text)
    if not text:
        raise DocumentExtractionError(
            "No readable text was found in the document. Scanned files need OCR before upload."
        )

    truncated = len(text) > MAX_REFERENCE_DOCUMENT_CHARS
    if truncated:
        text = text[:MAX_REFERENCE_DOCUMENT_CHARS].rstrip()
    return ExtractedDocument(
        name=safe_name,
        content=text,
        characters=len(text),
        truncated=truncated,
    )
