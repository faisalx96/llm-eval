"""Safe text extraction for analyzer reference-document uploads."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from multiprocessing import get_context
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


MAX_REFERENCE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_DOCUMENT_CHARS = 40_000
# DOCX files are ZIP archives. Bound the expanded XML separately from the
# compressed upload limit so a tiny archive cannot consume unbounded memory.
MAX_DOCX_DOCUMENT_XML_BYTES = 4 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100
MAX_PDF_PAGES = 100
MAX_PDF_DECOMPRESSED_BYTES = 4 * 1024 * 1024
MAX_PDF_EXTRACTION_SECONDS = 5
MAX_PDF_WORKER_MEMORY_BYTES = 256 * 1024 * 1024

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
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_DOCUMENT_XML_BYTES:
                raise DocumentExtractionError(
                    "The DOCX document content exceeds the extraction limit."
                )
            if (
                info.file_size
                and (
                    not info.compress_size
                    or info.file_size / info.compress_size
                    > MAX_DOCX_COMPRESSION_RATIO
                )
            ):
                raise DocumentExtractionError(
                    "The DOCX document content has an unsafe compression ratio."
                )
            with archive.open(info) as member:
                xml = member.read(MAX_DOCX_DOCUMENT_XML_BYTES + 1)
            if len(xml) > MAX_DOCX_DOCUMENT_XML_BYTES:
                raise DocumentExtractionError(
                    "The DOCX document content exceeds the extraction limit."
                )
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


def _pdf_stream_objects(page: object) -> list[object]:
    """Return the page content streams without asking pypdf to decode them."""
    try:
        contents = page.raw_get("/Contents")
    except KeyError:
        return []
    contents = contents.get_object()
    if isinstance(contents, list):
        return [stream.get_object() for stream in contents]
    return [contents]


def _safe_flate_decode(data: bytes, limit: int) -> bytes:
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(data, limit + 1)
    if len(decoded) > limit or decoder.unconsumed_tail:
        raise DocumentExtractionError("The PDF content exceeds the extraction limit.")
    decoded += decoder.flush(limit - len(decoded) + 1)
    if len(decoded) > limit:
        raise DocumentExtractionError("The PDF content exceeds the extraction limit.")
    return decoded


def _prepare_pdf_page_content(page: object, remaining: int) -> int:
    """Bound page-content expansion before pypdf text extraction decodes it."""
    from pypdf.generic import DecodedStreamObject, EncodedStreamObject

    consumed = 0
    for stream in _pdf_stream_objects(page):
        if not isinstance(stream, EncodedStreamObject):
            raw = getattr(stream, "_data", b"")
            if len(raw) > remaining - consumed:
                raise DocumentExtractionError(
                    "The PDF content exceeds the extraction limit."
                )
            consumed += len(raw)
            continue
        filters = stream.get("/Filter")
        filter_names = (
            [str(filter_name) for filter_name in filters]
            if isinstance(filters, list)
            else [str(filters)]
        )
        if filter_names not in (["/FlateDecode"], ["/Fl"]):
            raise DocumentExtractionError(
                "The PDF uses an unsupported compressed content stream."
            )
        decoded = _safe_flate_decode(stream._data, remaining - consumed)
        decoded_stream = DecodedStreamObject()
        decoded_stream.set_data(decoded)
        stream.decoded_self = decoded_stream
        consumed += len(decoded)
    return consumed


def _extract_pdf_in_worker(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is installed in production
        raise DocumentExtractionError("PDF extraction support is not installed.") from exc

    try:
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise DocumentExtractionError(
                f"The PDF exceeds the {MAX_PDF_PAGES}-page extraction limit."
            )
        parts: list[str] = []
        decompressed_bytes = 0
        extracted_chars = 0
        for page in reader.pages:
            decompressed_bytes += _prepare_pdf_page_content(
                page, MAX_PDF_DECOMPRESSED_BYTES - decompressed_bytes
            )
            page_text = page.extract_text() or ""
            remaining_chars = MAX_REFERENCE_DOCUMENT_CHARS + 1 - extracted_chars
            if remaining_chars <= 0:
                break
            parts.append(page_text[:remaining_chars])
            extracted_chars += len(parts[-1])
            if extracted_chars > MAX_REFERENCE_DOCUMENT_CHARS:
                break
        return "\n\n".join(parts)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError(
            "The PDF could not be read. Scanned PDFs need OCR before upload."
        ) from exc


def _pdf_extraction_worker(connection: object, data: bytes) -> None:
    """Parse untrusted PDF data outside the request worker's resource budget."""
    try:
        try:
            import resource

            _, address_space_hard_limit = resource.getrlimit(resource.RLIMIT_AS)
            if (
                address_space_hard_limit != resource.RLIM_INFINITY
                and address_space_hard_limit < MAX_PDF_WORKER_MEMORY_BYTES
            ):
                raise ValueError("The OS memory limit is below the PDF worker limit")
            resource.setrlimit(
                resource.RLIMIT_AS,
                (MAX_PDF_WORKER_MEMORY_BYTES, address_space_hard_limit),
            )
            _, cpu_hard_limit = resource.getrlimit(resource.RLIMIT_CPU)
            if (
                cpu_hard_limit != resource.RLIM_INFINITY
                and cpu_hard_limit < MAX_PDF_EXTRACTION_SECONDS
            ):
                raise ValueError("The OS CPU limit is below the PDF worker limit")
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (MAX_PDF_EXTRACTION_SECONDS, cpu_hard_limit),
            )
        except (AttributeError, ImportError, OSError, ValueError) as exc:
            raise DocumentExtractionError(
                "PDF extraction requires OS memory and CPU resource limits."
            ) from exc
        connection.send(("ok", _extract_pdf_in_worker(data)))
    except Exception as exc:  # noqa: BLE001 - returned as a safe upload error
        connection.send(("error", str(exc)))
    finally:
        connection.close()


def _extract_pdf(data: bytes) -> str:
    """Extract PDF text in a bounded child process to contain parser expansion."""
    context = get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(target=_pdf_extraction_worker, args=(child_connection, data))
    process.start()
    child_connection.close()
    try:
        if not parent_connection.poll(MAX_PDF_EXTRACTION_SECONDS):
            process.terminate()
            process.join()
            raise DocumentExtractionError("PDF extraction exceeded the time limit.")
        try:
            status, payload = parent_connection.recv()
        except EOFError as exc:
            raise DocumentExtractionError(
                "PDF extraction exceeded the resource limit."
            ) from exc
    finally:
        parent_connection.close()
        if process.is_alive():
            process.terminate()
        process.join()
    if status != "ok":
        raise DocumentExtractionError(str(payload) or "The PDF could not be read.")
    return str(payload)


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
