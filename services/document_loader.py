from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

try:
    import pymupdf
except ImportError:  # Mantém compatibilidade até a instalação das dependências.
    pymupdf = None


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@dataclass(frozen=True)
class DocumentSection:
    source: str
    location: str
    text: str


def discover_documents(directory: Path) -> list[Path]:
    return sorted(
        (path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda path: str(path).lower(),
    )


def load_document(path: Path, base_directory: Path) -> list[DocumentSection]:
    source = path.relative_to(base_directory).as_posix()
    extension = path.suffix.lower()
    if extension == ".pdf":
        return _load_pdf(path, source)
    if extension == ".docx":
        return _load_docx(path, source)
    if extension == ".txt":
        return _load_txt(path, source)
    return []


def _load_pdf(path: Path, source: str) -> list[DocumentSection]:
    if pymupdf is not None:
        sections = []
        with pymupdf.open(path) as document:
            for number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    sections.append(DocumentSection(source, f"página {number}", text))
        return sections

    reader = PdfReader(str(path))
    sections = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(DocumentSection(source, f"página {number}", text))
    return sections


def _load_docx(path: Path, source: str) -> list[DocumentSection]:
    document = Document(str(path))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    text = "\n".join(paragraphs)
    return [DocumentSection(source, "documento", text)] if text else []


def _load_txt(path: Path, source: str) -> list[DocumentSection]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding).strip()
            return [DocumentSection(source, "documento", text)] if text else []
        except UnicodeDecodeError:
            continue
    return []
