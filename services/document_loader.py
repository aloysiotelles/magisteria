from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import unicodedata

from docx import Document
from pypdf import PdfReader

try:
    import pymupdf
except ImportError:  # Mantem compatibilidade se a dependencia rapida nao estiver instalada.
    pymupdf = None


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in value if not unicodedata.combining(character))


def _excluded(path: Path) -> bool:
    configured = os.getenv("EXCLUDED_DOCUMENTS", "")
    patterns = [_normalized(item.strip()) for item in configured.split(",") if item.strip()]
    filename = _normalized(path.name)
    return any(pattern in filename for pattern in patterns)


@dataclass(frozen=True)
class DocumentSection:
    source: str
    location: str
    text: str


def discover_documents(directory: Path) -> list[Path]:
    candidates = [
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not _excluded(path)
    ]
    markdown_sources = {
        (path.parent, path.stem)
        for path in candidates
        if path.suffix.lower() in {".md", ".markdown"}
    }
    return sorted(
        (
            path for path in candidates
            if path.suffix.lower() in {".md", ".markdown"}
            or (path.parent, path.stem) not in markdown_sources
        ),
        key=lambda path: str(path).lower(),
    )


def load_document(path: Path, base_directory: Path) -> Iterator[DocumentSection]:
    """Le o documento progressivamente para limitar o uso de memoria."""
    source = path.relative_to(base_directory).as_posix()
    extension = path.suffix.lower()
    if extension == ".pdf":
        yield from _load_pdf(path, source)
    elif extension == ".docx":
        yield from _load_docx(path, source)
    elif extension == ".txt":
        yield from _load_txt(path, source)
    elif extension in {".md", ".markdown"}:
        yield from _load_markdown(path, source)


def _load_pdf(path: Path, source: str) -> Iterator[DocumentSection]:
    if pymupdf is not None:
        with pymupdf.open(path) as document:
            for number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    yield DocumentSection(source, f"página {number}", text)
        return

    reader = PdfReader(str(path))
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            yield DocumentSection(source, f"página {number}", text)


def _load_docx(path: Path, source: str) -> Iterator[DocumentSection]:
    document = Document(str(path))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    text = "\n".join(paragraphs)
    if text:
        yield DocumentSection(source, "documento", text)


def _load_txt(path: Path, source: str) -> Iterator[DocumentSection]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding).strip()
            if text:
                yield DocumentSection(source, "documento", text)
            return
        except UnicodeDecodeError:
            continue


def _load_markdown(path: Path, source: str) -> Iterator[DocumentSection]:
    text = path.read_text(encoding="utf-8").strip()
    if text:
        yield DocumentSection(source, "documento", text)
