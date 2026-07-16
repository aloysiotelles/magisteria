from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import re
import unicodedata


TOKEN_PATTERN = re.compile(r"[a-z0-9à-ÿ]+", re.IGNORECASE)
SPACE_PATTERN = re.compile(r"\s+")
REFERENCE_PATTERN = re.compile(
    r"(?:\bcic\s*\d{1,4}\b|\b(?:gn|ex|êx|lv|nm|dt|js|jz|rt|sm|rs|cr|esd|ne|tb|jt|"
    r"est|mc|jó|sl|pr|ecl|ct|sb|eclo|is|jr|lm|br|ez|dn|os|jl|am|ab|jn|mq|na|hab|"
    r"sf|ag|zc|ml|mt|mc|lc|jo|at|rm|cor|gl|ef|fl|cl|ts|tm|tt|fm|hb|tg|pd|jd|ap)\s*"
    r"\d{1,3}\s*[,.:]\s*\d{1,3}\b)",
    re.IGNORECASE,
)
DOCUMENT_REFERENCE_PATTERN = re.compile(
    r"\b(catecismo|compêndio|encíclica|concílio|vaticano|missal|cânon|código)\b",
    re.IGNORECASE,
)
QUESTION_OPENERS = {
    "como", "onde", "por que", "porque", "qual", "quais", "quando", "quem", "o que",
}
COMMAND_OPENERS = {
    "analise", "compare", "defina", "diferencie", "explique", "faça", "mostre", "resuma",
    "sintetize", "apresente", "descreva", "enumere", "elabore",
}
STOPWORDS = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e", "em", "na",
    "nas", "no", "nos", "o", "os", "para", "por", "que", "sem", "sobre", "um", "uma",
}


class QueryType(StrEnum):
    TERM = "TERM"
    PHRASE = "PHRASE"
    QUESTION = "QUESTION"
    REFERENCE = "REFERENCE"
    COMMAND = "COMMAND"


SAFE_ORTHOGRAPHIC_VARIANTS = {
    "batismo": {"baptismo"},
    "baptismo": {"batismo"},
    "onipotencia": {"omnipotencia"},
    "omnipotencia": {"onipotencia"},
    "santa-se": {"santa se"},
    "santa se": {"santa-se"},
    "matrimonio": {"matrimonio"},
}


@dataclass(frozen=True)
class QueryAnalysis:
    original: str
    normalized: str
    folded: str
    query_type: QueryType
    lexical_terms: tuple[str, ...]
    variants: tuple[str, ...]
    expanded_queries: tuple[str, ...]

    @property
    def thematic(self) -> bool:
        return self.query_type in {QueryType.TERM, QueryType.PHRASE}

    def to_dict(self) -> dict:
        data = asdict(self)
        data["query_type"] = self.query_type.value
        data["thematic"] = self.thematic
        return data


def normalize_preserving_accents(text: str) -> str:
    return SPACE_PATTERN.sub(" ", unicodedata.normalize("NFC", text)).strip()


def fold_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", normalize_preserving_accents(text).casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _safe_morphological_variants(term: str) -> set[str]:
    variants = {term}
    if len(term) < 2 or any(character.isdigit() for character in term):
        return variants
    if term.endswith("ao") and len(term) > 3:
        variants.add(term[:-2] + "oes")
    elif term.endswith("oes") and len(term) > 4:
        variants.add(term[:-3] + "ao")
    elif term.endswith("m") and len(term) > 3:
        variants.add(term[:-1] + "ns")
    elif term.endswith("ns") and len(term) > 4:
        variants.add(term[:-2] + "m")
    elif term.endswith("l") and len(term) > 3:
        variants.add(term[:-1] + "is")
    elif term.endswith("is") and len(term) > 4:
        variants.add(term[:-2] + "l")
    elif term.endswith(("r", "z")) and len(term) > 3:
        variants.add(term + "es")
    elif term.endswith("es") and len(term) > 4 and term[-3] in {"r", "z"}:
        variants.add(term[:-2])
    elif term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    elif term[-1] in "aeiou" and len(term) > 2:
        variants.add(term + "s")
    variants.update(SAFE_ORTHOGRAPHIC_VARIANTS.get(term, set()))
    return variants


def _classify(normalized: str, folded: str, terms: tuple[str, ...]) -> QueryType:
    if REFERENCE_PATTERN.search(normalized):
        return QueryType.REFERENCE
    if terms and not re.search(r"\s", normalized):
        return QueryType.TERM
    if DOCUMENT_REFERENCE_PATTERN.search(normalized) and len(terms) > 1:
        return QueryType.REFERENCE
    first_words = " ".join(folded.split()[:2])
    first_word = folded.split()[0] if folded.split() else ""
    if first_word in COMMAND_OPENERS:
        return QueryType.COMMAND
    if normalized.endswith("?") or first_word in QUESTION_OPENERS or first_words in QUESTION_OPENERS:
        return QueryType.QUESTION
    if len(terms) == 1:
        return QueryType.TERM
    return QueryType.PHRASE


def analyze_query(text: str, expansion_limit: int = 6) -> QueryAnalysis:
    original = text
    normalized = normalize_preserving_accents(text)
    folded = fold_text(normalized)
    all_tokens = tuple(TOKEN_PATTERN.findall(folded))
    lexical_terms = tuple(token for token in all_tokens if token not in STOPWORDS)
    query_type = _classify(normalized, folded, lexical_terms)

    variants: set[str] = set(lexical_terms)
    for term in lexical_terms:
        variants.update(_safe_morphological_variants(term))

    expanded = [normalized]
    if query_type in {QueryType.TERM, QueryType.PHRASE} and normalized:
        expanded.extend(
            (
                f"conceito católico de {normalized}",
                f"doutrina da Igreja Católica sobre {normalized}",
                f"definição de {normalized}",
                f"ensinamento católico sobre {normalized}",
                f"aspectos de {normalized}",
            )
        )
    expanded_queries = tuple(dict.fromkeys(expanded))[:max(expansion_limit, 1)]
    return QueryAnalysis(
        original=original,
        normalized=normalized,
        folded=folded,
        query_type=query_type,
        lexical_terms=lexical_terms,
        variants=tuple(sorted(variants)),
        expanded_queries=expanded_queries,
    )
