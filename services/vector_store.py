from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
import heapq
import logging
from collections.abc import Callable

from services.document_loader import discover_documents, load_document


logger = logging.getLogger(__name__)


TOKEN_PATTERN = re.compile(r"[a-z0-9à-ÿ]{2,}", re.IGNORECASE)
VECTOR_SIZE = 1536
QUERY_STOPWORDS = {
    "que", "como", "qual", "quais", "uma", "uns", "das", "dos", "para", "por", "com",
    "sem", "sobre", "segundo", "partir", "ensina", "ensinam", "igreja", "documento", "documentos",
}
SOURCE_HINTS = {
    "catecismo": ("catecismo",),
    "biblia": ("biblia",),
    "missal": ("missal",),
    "suma": ("suma teologica",),
    "doutrina social": ("doutrina social",),
    "d sistema": ("simbolos definicoes",),
}
ORDERED_SOURCES = (
    ("Catecismo da Igreja Católica", ("catecismo",), 5),
    ("Compêndio dos símbolos, definições e declarações", ("simbolos", "definicoes"), 2),
    ("Compêndio da Doutrina Social da Igreja", ("doutrina-social", "doutrina social"), 2),
    ("Suma Teológica", ("suma teologica", "suma-teologica", "suma"), 2),
    ("Bíblia Ave Maria — citações bíblicas", ("biblia ave maria", "biblia"), 4),
    ("Compêndio Vaticano II", ("compendio vaticano ii", "vaticano ii"), 3),
)
BIBLE_QUERY_EXPANSIONS = {
    "caridade": {"amor", "amar", "amou"},
    "sacramento": {"batismo", "eucaristia", "ceia"},
    "sacramentos": {"batismo", "eucaristia", "ceia"},
    "perdao": {"perdoar", "misericordia"},
    "esperanca": {"esperar", "ressurreicao"},
}
BIBLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:Gn|Ex|Êx|Lv|Nm|Dt|Js|Jz|Rt|1Sm|2Sm|1Rs|2Rs|1Cr|2Cr|Esd|Ne|Tb|Jt|Est|"
    r"1Mc|2Mc|Jó|Sl|Pr|Ecl|Ct|Sb|Eclo|Is|Jr|Lm|Br|Ez|Dn|Os|Jl|Am|Ab|Jn|Mq|Na|Hab|"
    r"Sf|Ag|Zc|Ml|Mt|Mc|Lc|Jo|At|Rm|1Cor|2Cor|Gl|Ef|Fl|Cl|1Ts|2Ts|1Tm|2Tm|Tt|Fm|"
    r"Hb|Tg|1Pd|2Pd|1Jo|2Jo|3Jo|Jd|Ap)[ \t]*\d{1,3}[ \t]*,[ \t]*\d{1,3}(?:[-–.]\d{1,3})*",
    re.IGNORECASE,
)


@dataclass
class Chunk:
    id: str
    source: str
    location: str
    text: str
    vector: dict[str, float]


class LocalVectorStore:
    """Índice vetorial local, determinístico e sem downloads externos."""

    def __init__(self, documents_dir: Path, index_file: Path, chunk_size: int, overlap: int):
        self.documents_dir = documents_dir
        self.index_file = index_file
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.data = self._load_index()
        self._rebuild_runtime_cache()

    def _empty_index(self) -> dict:
        return {"version": 2, "updated_at": None, "documents": [], "files": {}, "chunks": [], "errors": []}

    def _load_index(self) -> dict:
        if not self.index_file.exists():
            return self._empty_index()
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.exception("Não foi possível carregar o índice local: %s", exc)
            return self._empty_index()

    def _rebuild_runtime_cache(self) -> None:
        """Prepara metadados pequenos usados em todas as consultas."""
        sources = {chunk.get("source", "") for chunk in self.data.get("chunks", [])}
        self._normalized_sources = {source: self._normalize(source) for source in sources}
        self._source_rules = [
            (label, tuple(self._normalize(hint) for hint in hints), quota)
            for label, hints, quota in ORDERED_SOURCES
        ]
        self._source_buckets = {}
        for source, normalized in self._normalized_sources.items():
            bucket = len(self._source_rules)
            for index, (_, hints, _) in enumerate(self._source_rules):
                if any(hint in normalized for hint in hints):
                    bucket = index
                    break
            self._source_buckets[source] = bucket
        self._vatican_sections = self._load_vatican_sections()

    def _load_vatican_sections(self) -> list[tuple[int, str]]:
        """Relaciona páginas do compêndio aos documentos conciliares internos."""
        try:
            import pymupdf

            path = next(
                path for path in self.documents_dir.rglob("*.pdf")
                if "compendio vaticano ii" in self._normalize(path.name)
            )
            with pymupdf.open(path) as document:
                return [
                    (page, self._format_conciliar_title(title))
                    for level, title, page in document.get_toc(simple=True)
                    if level == 1 and title.strip()
                ]
        except (ImportError, OSError, StopIteration, ValueError):
            return []

    @staticmethod
    def _format_conciliar_title(title: str) -> str:
        words = title.strip().title().split()
        return " ".join(
            word.lower() if index and word.lower() in {"a", "da", "de", "do", "e", "em"} else word
            for index, word in enumerate(words)
        )

    def index_documents(
        self, progress_callback: Callable[[int, int, str], None] | None = None
    ) -> dict:
        chunks: list[dict] = []
        documents = discover_documents(self.documents_dir)
        errors: list[dict[str, str]] = []
        previous_files = self.data.get("files", {})
        document_names = [path.relative_to(self.documents_dir).as_posix() for path in documents]
        changed = self.data.get("version") != 2 or set(previous_files) != set(document_names)
        previous_chunks: dict[str, list[dict]] = {}
        for chunk in self.data.get("chunks", []):
            previous_chunks.setdefault(chunk.get("source", ""), []).append(chunk)
        current_files: dict[str, dict[str, int]] = {}

        if progress_callback:
            progress_callback(0, len(documents), "Preparando documentos")

        for position, path in enumerate(documents, start=1):
            source = path.relative_to(self.documents_dir).as_posix()
            stat = path.stat()
            fingerprint = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

            if previous_files.get(source) == fingerprint:
                chunks.extend(previous_chunks.get(source, []))
                current_files[source] = fingerprint
                if progress_callback:
                    progress_callback(position, len(documents), f"Reutilizado: {path.name}")
                continue

            changed = True

            if progress_callback:
                progress_callback(position - 1, len(documents), f"Lendo {position} de {len(documents)}: {path.name}")
            try:
                for section in load_document(path, self.documents_dir):
                    for number, text in enumerate(self._split_text(section.text), start=1):
                        chunk_id = hashlib.sha256(
                            f"{section.source}|{section.location}|{number}|{text}".encode("utf-8")
                        ).hexdigest()[:20]
                        chunks.append(
                            asdict(Chunk(
                                id=chunk_id,
                                source=section.source,
                                location=section.location,
                                text=text,
                                vector=self._vectorize(text),
                            ))
                        )
                current_files[source] = fingerprint
            except Exception as exc:  # Um arquivo inválido não impede a indexação dos demais.
                errors.append({"arquivo": path.name, "erro": str(exc)})
            finally:
                if progress_callback:
                    progress_callback(position, len(documents), path.name)

        updated_at = datetime.now(timezone.utc).isoformat()
        self.data = {
            "version": 2,
            "updated_at": updated_at,
            "documents": document_names,
            "files": current_files,
            "chunks": chunks,
            "errors": errors,
        }
        self._rebuild_runtime_cache()
        if not changed and not errors:
            return self.status()
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.index_file)
        return self.status()

    def search(
        self,
        query: str,
        limit: int = 6,
        minimum_score: float = 0.08,
        source_filter: tuple[str, ...] | None = None,
        excluded_sources: tuple[str, ...] = (),
    ) -> list[dict]:
        query_vector = self._vectorize(query)
        if not query_vector:
            return []
        normalized_query = self._normalize(query)
        query_terms = {
            token for token in TOKEN_PATTERN.findall(normalized_query)
            if token not in QUERY_STOPWORDS and len(token) > 2
        }
        query_term_slots = {self._feature_slot(term) for term in query_terms}
        preferred_sources = source_filter or self._preferred_sources(normalized_query)
        if preferred_sources:
            source_hint_terms = {
                token for hint in preferred_sources for token in TOKEN_PATTERN.findall(hint)
            }
            query_terms -= source_hint_terms
        ranked = []
        for chunk in self.data.get("chunks", []):
            source_normalized = self._normalize(chunk.get("source", ""))
            if preferred_sources and not any(hint in source_normalized for hint in preferred_sources):
                continue
            if excluded_sources and any(hint in source_normalized for hint in excluded_sources):
                continue

            vector_score = self._cosine(query_vector, chunk.get("vector", {}))
            chunk_slots = chunk.get("vector", {})
            coverage = sum(slot in chunk_slots for slot in query_term_slots) / max(len(query_term_slots), 1)
            relevance = (vector_score * 0.68) + (coverage * 0.32)
            source_bonus = 0.18 if preferred_sources else self._source_name_bonus(query_terms, source_normalized)
            score = relevance + source_bonus
            if relevance >= minimum_score:
                ranked.append({**chunk, "score": round(score, 4)})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return self._diversify(ranked, limit, bool(preferred_sources))

    def search_ordered(self, query: str, limit: int = 14, minimum_score: float = 0.08) -> list[dict]:
        """Consulta todas as coleções em uma varredura e monta a ordem editorial."""
        query_vector = self._vectorize(query)
        if not query_vector:
            return []

        normalized_query = self._normalize(query)
        query_terms = {
            token for token in TOKEN_PATTERN.findall(normalized_query)
            if token not in QUERY_STOPWORDS and len(token) > 2
        }
        query_term_slots = {self._feature_slot(term) for term in query_terms}
        source_rules = self._source_rules
        buckets: list[list[dict]] = [[] for _ in range(len(source_rules) + 1)]
        bible_query_terms = set(query_terms)
        for term in query_terms:
            bible_query_terms.update(BIBLE_QUERY_EXPANSIONS.get(term, set()))
        bible_term_slots = {self._feature_slot(term) for term in bible_query_terms}

        for chunk in self.data.get("chunks", []):
            source = chunk.get("source", "")
            source_normalized = self._normalized_sources.get(source, "")
            bucket_index = self._source_buckets.get(source, len(source_rules))

            vector_score = self._cosine(query_vector, chunk.get("vector", {}))
            chunk_slots = chunk.get("vector", {})
            coverage = sum(slot in chunk_slots for slot in query_term_slots) / max(len(query_term_slots), 1)
            if bucket_index == 4:
                coverage = sum(slot in chunk_slots for slot in bible_term_slots) / max(len(query_terms), 1)
            relevance = (vector_score * 0.68) + (coverage * 0.32)
            if relevance < minimum_score:
                continue
            source_bonus = 0.18 if bucket_index < len(source_rules) else self._source_name_bonus(
                query_terms, source_normalized
            )
            score = relevance + source_bonus
            if bucket_index == 4:
                verse_markers = len(re.findall(r"(?:^|\n)\s*\d{1,3}\s+", chunk.get("text", "")))
                if verse_markers >= 2 and coverage > 0:
                    score += 0.2
                if any(
                    marker in chunk.get("text", "").lower()
                    for marker in ("introdução", "características", "interpretação", "plano da obra")
                ):
                    score -= 0.1
            buckets[bucket_index].append({**chunk, "score": round(score, 4)})

        bucket_limits = [quota for _, _, quota in source_rules] + [limit]
        buckets = [
            heapq.nlargest(bucket_limits[index], bucket, key=lambda item: item["score"])
            for index, bucket in enumerate(buckets)
        ]

        selected: list[dict] = []
        for order, ((label, _, quota), bucket) in enumerate(zip(source_rules, buckets), start=1):
            selected.extend(
                {**result, "ordem": order, "categoria": label}
                for result in bucket[:quota]
            )

        remaining = max(limit - len(selected), 0)
        selected.extend(
            {**result, "ordem": len(source_rules) + 1, "categoria": "Demais documentos"}
            for result in buckets[-1][:remaining]
        )
        selected = self._enrich_bible_locations(selected[:limit])
        return self._enrich_reference_metadata(selected)

    def _enrich_reference_metadata(self, results: list[dict]) -> list[dict]:
        selected_pages = {
            (item["source"], match.group())
            for item in results
            if (match := re.search(r"\d+", item.get("location", "")))
        }
        page_texts: dict[tuple[str, str], list[str]] = {key: [] for key in selected_pages}
        for chunk in self.data.get("chunks", []):
            page_number_match = re.search(r"\d+", chunk.get("location", ""))
            if not page_number_match:
                continue
            key = (chunk.get("source", ""), page_number_match.group())
            if key in page_texts:
                page_texts[key].append(chunk.get("text", ""))

        for item in results:
            source_normalized = self._normalize(item["source"])
            page_match = re.search(r"\d+", item.get("location", ""))
            key = (item["source"], page_match.group()) if page_match else None
            page_text = "\n".join(page_texts.get(key, [])) or item.get("text", "")
            references: list[str] = []

            if "catecismo" in source_normalized:
                references = re.findall(r"(?:^|\n)\s*(\d{1,4})\.\s", page_text)
            elif "simbolos" in source_normalized:
                range_match = re.search(r"\*(\d{3,4})\s*[-–]\s*(\d{3,4})", page_text)
                if range_match:
                    references = [f"{range_match.group(1)}–{range_match.group(2)}"]
                else:
                    references = re.findall(r"\*(\d{3,4})", page_text)
            elif "doutrina-social" in source_normalized or "doutrina social" in source_normalized:
                references = re.findall(r"(?:^|\n)\s*(\d{1,3})\s+(?=[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ])", page_text)
            elif "compendio vaticano ii" in source_normalized or "vaticano ii" in source_normalized:
                paragraph_numbers = re.findall(
                    r"(?:^|\n|\s)(\d{1,3})\.\s+(?=[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ«])",
                    item.get("text", ""),
                )
                if not paragraph_numbers:
                    paragraph_numbers = re.findall(
                        r"(?:^|\n)(\d{1,3})\.\s+(?=[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ«])",
                        page_text,
                    )[:1]
                page_number = int(page_match.group()) if page_match else 0
                eligible = [section for section in self._vatican_sections if section[0] <= page_number]
                internal_document = eligible[-1][1] if eligible else "Concílio Vaticano II"
                references = [
                    f"{internal_document}, n. {number}"
                    for number in dict.fromkeys(paragraph_numbers)
                ]
            elif "biblia" in source_normalized:
                references = []
                for match in BIBLE_REFERENCE_PATTERN.finditer(page_text):
                    reference = re.sub(r"([A-Za-zÀ-ÿ])(?=\d)", r"\1 ", match.group(0), count=1)
                    reference = re.sub(r"[ \t]*,[ \t]*", ",", reference)
                    references.append(reference)

            item["referencias"] = list(dict.fromkeys(references))[:12]
        return results

    def _enrich_bible_locations(self, results: list[dict]) -> list[dict]:
        bible_results = [item for item in results if item.get("ordem") == 5]
        if not bible_results:
            return results
        try:
            import pymupdf

            bible_path = next(
                path for path in self.documents_dir.rglob("*.pdf")
                if "biblia ave maria" in self._normalize(path.name)
            )
            with pymupdf.open(bible_path) as document:
                sections = [
                    (page, title.lstrip("| ").strip())
                    for _, title, page in document.get_toc(simple=True)
                    if title.lstrip().startswith("|")
                ]
            for item in bible_results:
                match = re.search(r"(\d+)", item.get("location", ""))
                if not match or not sections:
                    continue
                page_number = int(match.group(1))
                _, book = min(sections, key=lambda section: abs(section[0] - page_number))
                item["location"] = f"{book}, página {page_number}"
        except (OSError, StopIteration, ValueError):
            pass
        return results

    def status(self) -> dict:
        return {
            "documentos": len(self.data.get("documents", [])),
            "trechos": len(self.data.get("chunks", [])),
            "ultima_atualizacao": self.data.get("updated_at"),
            "erros": self.data.get("errors", []),
        }

    def document_names(self) -> list[str]:
        return sorted(self.data.get("documents", []), key=str.casefold)

    @classmethod
    def _preferred_sources(cls, normalized_query: str) -> tuple[str, ...]:
        matches = []
        for query_hint, source_hints in SOURCE_HINTS.items():
            if query_hint in normalized_query:
                matches.extend(source_hints)
        return tuple(matches)

    @staticmethod
    def _source_name_bonus(query_terms: set[str], normalized_source: str) -> float:
        source_terms = set(TOKEN_PATTERN.findall(normalized_source)) - QUERY_STOPWORDS
        matches = len(query_terms & source_terms)
        return min(matches * 0.06, 0.18)

    @staticmethod
    def _diversify(ranked: list[dict], limit: int, source_is_explicit: bool) -> list[dict]:
        selected = []
        per_source: Counter[str] = Counter()
        per_source_limit = limit if source_is_explicit else max(2, (limit + 1) // 2)
        for item in ranked:
            source = item["source"]
            if per_source[source] >= per_source_limit:
                continue
            selected.append(item)
            per_source[source] += 1
            if len(selected) == limit:
                break
        return selected

    def _split_text(self, text: str) -> list[str]:
        clean = re.sub(r"[ \t]+", " ", text)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        if len(clean) <= self.chunk_size:
            return [clean] if clean else []

        chunks = []
        start = 0
        while start < len(clean):
            end = min(start + self.chunk_size, len(clean))
            if end < len(clean):
                boundary = max(clean.rfind(". ", start, end), clean.rfind("\n", start, end))
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1
            chunk = clean[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(end - self.overlap, start + 1)
        return chunks

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.lower())
        return "".join(character for character in normalized if not unicodedata.combining(character))

    @classmethod
    def _vectorize(cls, text: str) -> dict[str, float]:
        tokens = TOKEN_PATTERN.findall(cls._normalize(text))
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        counts: Counter[str] = Counter()
        for feature in features:
            slot = int(cls._feature_slot(feature))
            counts[str(slot)] += 1
        norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
        return {slot: value / norm for slot, value in counts.items()}

    @staticmethod
    def _feature_slot(feature: str) -> str:
        slot = int(hashlib.blake2b(feature.encode("utf-8"), digest_size=4).hexdigest(), 16) % VECTOR_SIZE
        return str(slot)

    @staticmethod
    def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(slot, 0.0) for slot, value in left.items())
