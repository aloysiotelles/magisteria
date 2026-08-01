from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable

from services.catholic_taxonomy import fold_text
from services.gospel_policy import (
    AUTHOR_LABEL_PATTERN,
    CATENA_COLLECTION,
    CATENA_COMPILER,
    CATENA_SOURCE_HINTS,
    CATENA_WORK,
    GOSPEL_ABBREVIATIONS,
    extract_patristic_attributions,
    pericope_for,
)


GOSPEL_HEADING_PATTERN = re.compile(
    r"^#\s+Evangelho\s+segundo\s+S[aã]o\s+(Mateus|Marcos|Lucas|Jo[aã]o)\s*$",
    re.IGNORECASE,
)
CHAPTER_HEADING_PATTERN = re.compile(r"^##\s+Cap[ií]tulo\s+(\d{1,2})\s*$", re.IGNORECASE)
LESSON_HEADING_PATTERN = re.compile(r"^###\s+Li[cç][aã]o\s+(\d{1,3})\s*$", re.IGNORECASE)
VERSE_NUMBER_PATTERN = re.compile(r"(?<![\w\[])\b(\d{1,3})\b(?=\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚ])")


@dataclass(frozen=True)
class CatenaIndexedChunk:
    text: str
    location: str
    metadata: dict


def is_catena_source(source: str, text: str = "") -> bool:
    normalized_source = fold_text(source)
    return any(fold_text(hint) in normalized_source for hint in CATENA_SOURCE_HINTS) or (
        "# catena aurea" in fold_text(text[:500])
    )


def _quote_text(unit: str) -> str:
    lines: list[str] = []
    started = False
    for line in unit.splitlines():
        if line.lstrip().startswith(">"):
            started = True
            lines.append(line.lstrip()[1:].strip())
            continue
        if started and line.strip():
            break
    return " ".join(lines)


def _verse_range(unit: str, lesson: int | None) -> tuple[int | None, int | None]:
    quote = _quote_text(unit)
    numbers = [int(value) for value in VERSE_NUMBER_PATTERN.findall(quote)]
    if not numbers:
        return (1, None) if lesson == 1 and quote else (None, None)
    first_number = min(numbers)
    inferred_start = 1 if lesson == 1 else max(first_number - 1, 1)
    return inferred_start, max(numbers)


def _author_segments(unit: str) -> list[tuple[str, tuple[dict[str, str], ...]]]:
    matches = list(AUTHOR_LABEL_PATTERN.finditer(unit))
    if not matches:
        return [(unit, ())]
    segments: list[tuple[str, tuple[dict[str, str], ...]]] = []
    introduction = unit[:matches[0].start()].strip()
    if introduction:
        segments.append((introduction, ()))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(unit)
        segment = unit[match.start():end].strip()
        if segment:
            segments.append((segment, extract_patristic_attributions(segment)))
    return segments


def _context_prefix(gospel: str | None, chapter: int | None, lesson: int | None) -> str:
    pieces = [CATENA_WORK]
    if gospel:
        pieces.append(f"Evangelho segundo São {gospel}")
    if chapter is not None:
        pieces.append(f"Capítulo {chapter}")
    if lesson is not None:
        pieces.append(f"Lição {lesson}")
    return " | ".join(pieces)


def _location(gospel: str | None, chapter: int | None, lesson: int | None) -> str:
    if gospel and chapter is not None:
        abbreviation = GOSPEL_ABBREVIATIONS[gospel]
        suffix = f", lição {lesson}" if lesson is not None else ""
        return f"{abbreviation} {chapter}{suffix}"
    return "nota editorial, dedicatória ou prólogo"


def split_catena_document(
    text: str,
    source: str,
    split_text: Callable[[str], list[str]],
) -> list[CatenaIndexedChunk]:
    """Split the Catena by Gospel/chapter/lesson and then by explicit attribution.

    Every continuation of a long patristic excerpt inherits the attribution from
    the exact bold label that introduced it. No author is inferred from proximity.
    """
    units: list[tuple[str | None, int | None, int | None, str]] = []
    current_lines: list[str] = []
    gospel: str | None = None
    chapter: int | None = None
    lesson: int | None = None

    def flush() -> None:
        nonlocal current_lines
        body = "\n".join(current_lines).strip()
        if body:
            units.append((gospel, chapter, lesson, body))
        current_lines = []

    for line in text.splitlines():
        gospel_match = GOSPEL_HEADING_PATTERN.match(line.strip())
        chapter_match = CHAPTER_HEADING_PATTERN.match(line.strip())
        lesson_match = LESSON_HEADING_PATTERN.match(line.strip())
        if gospel_match:
            flush()
            gospel = gospel_match.group(1).replace("Joao", "João")
            chapter = None
            lesson = None
        elif chapter_match:
            flush()
            chapter = int(chapter_match.group(1))
            lesson = None
        elif lesson_match:
            flush()
            lesson = int(lesson_match.group(1))
        current_lines.append(line)
    flush()

    document_id = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
    indexed: list[CatenaIndexedChunk] = []
    for unit_gospel, unit_chapter, unit_lesson, unit in units:
        verse_start, verse_end = _verse_range(unit, unit_lesson)
        common_pericope = pericope_for(
            unit_gospel,
            unit_chapter,
            verse_start,
            verse_end,
            unit,
        )
        prefix = _context_prefix(unit_gospel, unit_chapter, unit_lesson)
        for segment, attributions in _author_segments(unit):
            authors = tuple(item["author"] for item in attributions)
            source_works = tuple(item["source_work"] for item in attributions if item["source_work"])
            for piece in split_text(segment):
                searchable_text = f"[{prefix}]\n{piece}" if prefix else piece
                metadata = {
                    "collection": CATENA_COLLECTION,
                    "work": CATENA_WORK,
                    "compiler": CATENA_COMPILER,
                    "gospel": unit_gospel or "",
                    "chapter": unit_chapter,
                    "verse_start": verse_start,
                    "verse_end": verse_end,
                    "pericope": common_pericope,
                    "patristic_author": authors[0] if len(authors) == 1 else "",
                    "patristic_authors": authors,
                    "source_work": source_works[0] if len(source_works) == 1 else "",
                    "attributions": attributions,
                    "language": "português",
                    "document_id": document_id,
                    "lesson": unit_lesson,
                    "verse_range_inferred": bool(verse_start is not None),
                }
                indexed.append(
                    CatenaIndexedChunk(
                        text=searchable_text,
                        location=_location(unit_gospel, unit_chapter, unit_lesson),
                        metadata=metadata,
                    )
                )
    return indexed


def metadata_for_existing_chunk(source: str, location: str, text: str) -> dict:
    """Best-effort compatibility for a legacy Catena chunk before reindexing."""
    if not is_catena_source(source, text):
        return {}
    gospel_match = re.search(r"Evangelho segundo São (Mateus|Marcos|Lucas|João)", text, re.IGNORECASE)
    chapter_match = re.search(r"Capítulo\s+(\d{1,2})", text, re.IGNORECASE)
    lesson_match = re.search(r"Lição\s+(\d{1,3})", text, re.IGNORECASE)
    gospel = gospel_match.group(1).title() if gospel_match else ""
    if gospel == "João" or fold_text(gospel) == "joao":
        gospel = "João"
    chapter = int(chapter_match.group(1)) if chapter_match else None
    lesson = int(lesson_match.group(1)) if lesson_match else None
    verse_start, verse_end = _verse_range(text, lesson)
    attributions = extract_patristic_attributions(text)
    authors = tuple(item["author"] for item in attributions)
    return {
        "collection": CATENA_COLLECTION,
        "work": CATENA_WORK,
        "compiler": CATENA_COMPILER,
        "gospel": gospel,
        "chapter": chapter,
        "verse_start": verse_start,
        "verse_end": verse_end,
        "pericope": pericope_for(gospel, chapter, verse_start, verse_end, text),
        "patristic_author": authors[0] if len(authors) == 1 else "",
        "patristic_authors": authors,
        "source_work": "",
        "attributions": attributions,
        "language": "português",
        "document_id": hashlib.sha256(source.encode("utf-8")).hexdigest()[:20],
        "lesson": lesson,
        "verse_range_inferred": bool(verse_start is not None),
        "legacy_backfill": True,
        "original_location": location,
    }
