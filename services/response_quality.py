from __future__ import annotations

from dataclasses import dataclass
import re

from services.catholic_taxonomy import fold_text
from services.gospel_policy import extract_patristic_attributions, patristic_authors
from services.response_planning import ResponsePlan


@dataclass(frozen=True)
class CoverageResult:
    passed: bool
    missing_components: tuple[str, ...]
    shallow_components: tuple[str, ...]
    invalid_citations: tuple[str, ...]
    citation_count: int

    @property
    def failure_count(self) -> int:
        return len(self.missing_components) + len(self.shallow_components) + len(self.invalid_citations)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "missing_components": list(self.missing_components),
            "shallow_components": list(self.shallow_components),
            "invalid_citations": list(self.invalid_citations),
            "citation_count": self.citation_count,
            "failure_count": self.failure_count,
        }


class CoverageValidator:
    CITATION_PATTERN = re.compile(r"\[F(\d{1,3})\]")

    @staticmethod
    def _component_terms(component: str) -> tuple[str, ...]:
        ignored = {"deus", "santo", "santa", "divina", "divino", "primeiro", "segundo"}
        terms = tuple(
            term for term in re.findall(r"[a-z0-9à-ÿ]{3,}", fold_text(component))
            if term not in ignored
        )
        return terms[-3:] or terms

    def validate_retrieval(self, plan: ResponsePlan, chunks: list[dict]) -> CoverageResult:
        if not plan.active_components:
            return CoverageResult(True, (), (), (), 0)
        available = {
            str(component)
            for chunk in chunks
            for component in (chunk.get("components") or (chunk.get("component"),))
            if component
        }
        missing = tuple(component for component in plan.active_components if component not in available)
        return CoverageResult(not missing, missing, (), (), 0)

    def validate_answer(self, plan: ResponsePlan, answer: str, source_count: int) -> CoverageResult:
        # Preserva quebras de linha para distinguir uma enumeração nominal de
        # subseções realmente desenvolvidas.
        folded_answer = "\n".join(fold_text(line) for line in answer.splitlines())
        missing: list[str] = []
        shallow: list[str] = []
        component_occurrences: dict[str, list[int]] = {}
        all_positions: list[tuple[int, str]] = []
        for component in plan.active_components:
            positions: set[int] = set()
            for term in self._component_terms(component):
                positions.update(match.start() for match in re.finditer(rf"\b{re.escape(term)}\b", folded_answer))
            component_occurrences[component] = sorted(positions)
            all_positions.extend((position, component) for position in positions)
        all_positions.sort()

        for component in plan.active_components:
            positions = component_occurrences.get(component, [])
            if not positions:
                missing.append(component)
                continue
            substantive = False
            for position in positions:
                line_start = folded_answer.rfind("\n", 0, position) + 1
                line_end = folded_answer.find("\n", position)
                if line_end < 0:
                    line_end = len(folded_answer)
                line = folded_answer[line_start:line_end]
                names_on_line = sum(
                    1 for other in plan.active_components
                    if any(term in line for term in self._component_terms(other))
                )
                if names_on_line >= 3:
                    # Uma enumeração inicial prova presença nominal, não explicação.
                    continue
                next_component = min((
                    other_position for other_position, other in all_positions
                    if other_position > position and other != component
                ), default=len(folded_answer))
                segment = folded_answer[position:min(next_component, position + 1200)]
                if len(segment.strip()) >= plan.minimum_component_characters:
                    substantive = True
                    break
            if not substantive:
                shallow.append(component)
        citations = [int(value) for value in self.CITATION_PATTERN.findall(answer)]
        invalid = tuple(f"F{value}" for value in citations if value < 1 or value > source_count)
        if (plan.composite or plan.is_gospel) and source_count and not citations:
            invalid = (*invalid, "ausentes")
        passed = not missing and not shallow and not invalid
        return CoverageResult(passed, tuple(missing), tuple(shallow), invalid, len(citations))

    def used_source_indexes(self, answer: str, source_count: int) -> tuple[int, ...]:
        indexes = {
            int(value) for value in self.CITATION_PATTERN.findall(answer)
            if 1 <= int(value) <= source_count
        }
        return tuple(sorted(indexes))


class CitationValidator:
    """Rejects only impossible source markers; exact locators remain document-derived."""

    def validate(self, answer: str, source_count: int) -> tuple[str, ...]:
        citations = [int(value) for value in CoverageValidator.CITATION_PATTERN.findall(answer)]
        return tuple(f"F{value}" for value in citations if value < 1 or value > source_count)


class PatristicAttributionValidator:
    """Detect named patristic claims that are absent from recovered Catena labels."""

    KNOWN_AUTHORS = (
        "agostinho", "joao crisostomo", "crisostomo", "jeronimo", "ambrosio",
        "gregorio magno", "gregorio de nissa", "gregorio nazianzeno", "hilario",
        "beda", "origenes", "cirilo de alexandria", "joao damasceno", "remigio",
        "teofilacto", "pseudo-crisostomo", "rabano", "leao", "eusebio",
    )
    CLAIM_PATTERN = re.compile(
        r"\b(?:segundo|conforme|para|como ensina|como afirma|na leitura de)\s+"
        r"(?:sao|santo|santa)?\s*(?P<author>[a-z -]{3,45})",
        re.IGNORECASE,
    )

    @staticmethod
    def _equivalent(claimed: str, available: str) -> bool:
        claimed = fold_text(claimed).strip(" ,.;:")
        available = fold_text(available).strip(" ,.;:")
        claimed = re.sub(r"^(?:sao|santo|santa)\s+", "", claimed)
        available = re.sub(r"^(?:sao|santo|santa)\s+", "", available)
        return bool(claimed and available and (claimed in available or available in claimed))

    def validate(self, answer: str, chunks: list[dict]) -> tuple[str, ...]:
        available = list(patristic_authors(chunks))
        if not available:
            available = [
                item["author"]
                for chunk in chunks
                for item in extract_patristic_attributions(str(chunk.get("text") or ""))
            ]
        folded_answer = fold_text(answer)
        invalid: list[str] = []
        for known in self.KNOWN_AUTHORS:
            if known not in folded_answer:
                continue
            claim_context = bool(re.search(
                rf"\b(?:segundo|conforme|para|afirma|ensina|interpreta)\b[^.!?]{{0,55}}\b{re.escape(known)}\b|"
                rf"\b{re.escape(known)}\b[^.!?]{{0,35}}\b(?:afirma|ensina|interpreta|observa)\b",
                folded_answer,
            ))
            if claim_context and not any(self._equivalent(known, author) for author in available):
                invalid.append(known)
        return tuple(dict.fromkeys(invalid))


class DoctrinalConsistencyValidator:
    """Supplies deterministic review criteria for authority and certainty language."""

    @staticmethod
    def instruction() -> str:
        return (
            "Diferencie doutrina definida, ensinamento comum, disciplina, devoção, opinião teológica e "
            "revelação privada. Não apresente autor particular como definição dogmática. Use 'a Igreja ensina' "
            "somente quando a evidência magisterial recuperada sustentar essa formulação e declare limitações "
            "quando não houver referência exata."
        )
