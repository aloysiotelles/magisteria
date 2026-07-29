from __future__ import annotations

from dataclasses import dataclass
import re

from services.catholic_taxonomy import fold_text
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
        folded_answer = fold_text(answer)
        missing: list[str] = []
        shallow: list[str] = []
        for component in plan.active_components:
            terms = self._component_terms(component)
            matches = [term for term in terms if re.search(rf"\b{re.escape(term)}\b", folded_answer)]
            if not matches:
                missing.append(component)
                continue
            first = min((folded_answer.find(term) for term in matches if folded_answer.find(term) >= 0), default=-1)
            if first >= 0:
                window = folded_answer[first:first + plan.minimum_component_characters]
                if len(window) < min(plan.minimum_component_characters, 80):
                    shallow.append(component)
        citations = [int(value) for value in self.CITATION_PATTERN.findall(answer)]
        invalid = tuple(f"F{value}" for value in citations if value < 1 or value > source_count)
        if plan.composite and source_count and not citations:
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
