from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import re

from services.catholic_taxonomy import TAXONOMY_VERSION, TopicSpec, classify_category, fold_text, match_topic
from services.query_analysis import QueryType, analyze_query


RESPONSE_STRATEGY_VERSION = "layered-rag-1"


class DepthLevel(StrEnum):
    SUMMARY = "resumido"
    EXPLANATORY = "explicativo"
    DEEP = "aprofundado"


class IntentKind(StrEnum):
    SIMPLE = "simples"
    CONCEPTUAL = "conceitual"
    HISTORICAL = "historica"
    BIBLICAL = "biblica"
    PASTORAL = "pastoral"
    COMPARATIVE = "comparativa"
    MORAL = "moral"
    LITURGICAL = "liturgica"
    APOLOGETIC = "apologetica"
    COMPOSITE = "composta"
    ENUMERATIVE = "enumerativa"
    DEEPENING = "aprofundamento"
    DEFINITION_AND_COMPONENTS = "definicao_e_componentes"


PROFILE_INSTRUCTIONS = {
    "crianca": "linguagem concreta, frases curtas e exemplos seguros para uma criança",
    "adolescente": "linguagem clara para adolescente, sem infantilização",
    "catequizando": "linguagem catequética acessível e explicação de termos técnicos",
    "adulto_iniciacao": "linguagem acessível a adulto em iniciação cristã",
    "catequista": "linguagem clara com utilidade catequética e distinções doutrinais",
    "agente_pastoral": "linguagem pastoral clara, com aplicações prudentes",
    "estudante_teologia": "linguagem acadêmica moderada e distinções técnicas explícitas",
    "clerigo": "linguagem teológico-pastoral precisa e concisa",
    "pesquisador": "linguagem técnica, referências precisas e distinção de graus de autoridade",
    "adulto_leigo": "linguagem acessível a um adulto leigo, explicando termos técnicos",
}


@dataclass(frozen=True)
class ResponsePlan:
    theme: str
    topic_key: str
    display_title: str
    category: str
    intents: tuple[str, ...]
    depth: str
    components: tuple[str, ...]
    active_components: tuple[str, ...]
    dimensions: tuple[str, ...]
    source_types: tuple[str, ...]
    introduction_required: bool
    conclusion_required: bool
    continuation_required: bool
    continuation_message: str
    user_profile: str
    language: str
    max_context_tokens: int
    max_output_tokens: int
    minimum_component_characters: int
    suggestions: tuple[str, ...]
    taxonomy_version: str = TAXONOMY_VERSION
    strategy_version: str = RESPONSE_STRATEGY_VERSION

    @property
    def composite(self) -> bool:
        return IntentKind.COMPOSITE.value in self.intents

    @property
    def profile_instruction(self) -> str:
        return PROFILE_INSTRUCTIONS.get(self.user_profile, PROFILE_INSTRUCTIONS["adulto_leigo"])

    @property
    def semantic_signature(self) -> str:
        base = "|".join((self.topic_key, self.category, *map(fold_text, self.components)))
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["composite"] = self.composite
        data["profile_instruction"] = self.profile_instruction
        data["semantic_signature"] = self.semantic_signature
        return data


SUMMARY_PATTERN = re.compile(r"\b(resumo|resuma|resumido|sintese|síntese|breve|curt[oa]|introducao|introdução)\b", re.IGNORECASE)
DEEP_PATTERN = re.compile(r"\b(aprofund|detalh|complet|em profundidade|estudo|analise|análise|parte por parte|um por um|artigo por artigo)\b", re.IGNORECASE)
ENUMERATIVE_PATTERN = re.compile(r"\b(cada|todos?|quais sao|quais são|liste|enumere|tipos|graus|etapas|partes|divisoes|divisões|componentes)\b", re.IGNORECASE)
COMPARISON_PATTERN = re.compile(r"\b(compare|comparacao|comparação|diferenca|diferença|versus|entre .+ e )\b", re.IGNORECASE)
PASTORAL_PATTERN = re.compile(r"\b(pastoral|catequese|homilia|pregacao|pregação|aplicacao pratica|aplicação prática)\b", re.IGNORECASE)
HISTORY_PATTERN = re.compile(r"\b(historia|história|origem|desenvolvimento|concilio|concílio|seculo|século)\b", re.IGNORECASE)
BIBLICAL_PATTERN = re.compile(r"\b(biblia|bíblia|biblic[oa]|bíblic[oa]|escritura|evangelho|versiculo|versículo)\b", re.IGNORECASE)
LITURGY_PATTERN = re.compile(r"\b(liturgia|liturgic[oa]|litúrgic[oa]|missa|rito|celebracao|celebração|ano liturgico|ano litúrgico)\b", re.IGNORECASE)
MORAL_PATTERN = re.compile(r"\b(moral|pecado|virtude|mandamento|consciencia|consciência|bioetica|bioética)\b", re.IGNORECASE)
APOLOGETIC_PATTERN = re.compile(r"\b(apologet|por que os catolicos|por que os católicos|protestante|objecao|objeção)\b", re.IGNORECASE)


def _fallback_theme(question: str) -> str:
    analysis = analyze_query(question)
    theme = getattr(analysis, "central_topic", "") or analysis.normalized
    theme = re.sub(r"^(?:explique|defina|descreva|apresente|quais são|quais sao|o que é|o que e)\s+", "", theme, flags=re.IGNORECASE)
    return theme.strip(" .?!,;:") or "Consulta católica"


def _intent_set(question: str, spec: TopicSpec | None, composite: bool) -> tuple[str, ...]:
    intents: list[str] = []
    analysis = analyze_query(question)
    if analysis.query_type in {QueryType.TERM, QueryType.PHRASE, QueryType.QUESTION}:
        intents.append(IntentKind.CONCEPTUAL.value)
    for pattern, intent in (
        (HISTORY_PATTERN, IntentKind.HISTORICAL), (BIBLICAL_PATTERN, IntentKind.BIBLICAL),
        (PASTORAL_PATTERN, IntentKind.PASTORAL), (COMPARISON_PATTERN, IntentKind.COMPARATIVE),
        (MORAL_PATTERN, IntentKind.MORAL), (LITURGY_PATTERN, IntentKind.LITURGICAL),
        (APOLOGETIC_PATTERN, IntentKind.APOLOGETIC),
    ):
        if pattern.search(question):
            intents.append(intent.value)
    if ENUMERATIVE_PATTERN.search(question) or (spec and spec.components):
        intents.append(IntentKind.ENUMERATIVE.value)
    if DEEP_PATTERN.search(question):
        intents.append(IntentKind.DEEPENING.value)
    if composite:
        intents.extend((IntentKind.COMPOSITE.value, IntentKind.DEFINITION_AND_COMPONENTS.value))
    if not intents:
        intents.append(IntentKind.SIMPLE.value)
    return tuple(dict.fromkeys(intents))


def _generic_dimensions(category: str) -> tuple[str, ...]:
    if category == "direito_canonico":
        return ("definição", "norma aplicável", "sujeitos", "condições", "efeitos", "limites", "ressalva para casos concretos")
    if category == "historia_tradicao":
        return ("contexto", "acontecimentos", "personagens", "desenvolvimento", "consequências doutrinais e pastorais")
    if category == "apologetica":
        return ("questão central", "fundamento bíblico", "Tradição", "Magistério", "objeções frequentes", "resposta respeitosa")
    return ("definição", "fundamento bíblico", "ensinamento da Igreja", "significado", "distinções", "aplicação")


def build_response_plan(
    question: str,
    language: str = "pt-BR",
    user_profile: str = "adulto_leigo",
) -> ResponsePlan:
    spec = match_topic(question)
    folded = fold_text(question)
    explicit_components = bool(ENUMERATIVE_PATTERN.search(question) or DEEP_PATTERN.search(question))
    implicit_complete = bool(spec and spec.components and re.search(
        r"\b(explique|compreender|entender|estudar|quero saber|quais|o que sao|o que são|apresente)\b",
        folded,
    ))
    asks_summary = bool(SUMMARY_PATTERN.search(question))
    composite = bool((spec and spec.components and (explicit_components or implicit_complete or asks_summary)) or (
        ENUMERATIVE_PATTERN.search(question) and len(question.split()) > 2
    ))
    asks_deep = bool(DEEP_PATTERN.search(question))
    if asks_summary:
        depth = DepthLevel.SUMMARY
    elif asks_deep or composite:
        depth = DepthLevel.DEEP
    else:
        depth = DepthLevel.EXPLANATORY

    theme = spec.title if spec else _fallback_theme(question)
    category = classify_category(question, spec)
    components = spec.components if spec and composite else ()
    if depth == DepthLevel.SUMMARY:
        max_context_tokens, max_output_tokens, minimum_chars = 4200, 1200, 70
    elif depth == DepthLevel.DEEP:
        max_context_tokens, max_output_tokens, minimum_chars = 10500, 5000, 220
    else:
        max_context_tokens, max_output_tokens, minimum_chars = 6200, 2000, 120

    # Very large canonical sets are deliberately serialized into substantive
    # parts. The full component list remains in the plan for continuation.
    active_limit = len(components)
    continuation_message = ""
    if len(components) > 20:
        active_limit = 5 if depth == DepthLevel.DEEP else 8
        continuation_message = (
            f"Esta explicação foi planejada em partes para cobrir {len(components)} componentes sem superficialidade. "
            f"Nesta resposta serão tratados a visão geral e os primeiros {active_limit}; os demais permanecem registrados para continuação."
        )
    active_components = components[:active_limit]
    topic_key = spec.key if spec else re.sub(r"[^a-z0-9]+", "_", fold_text(theme)).strip("_")[:100]
    title = spec.title if spec else theme[:120]
    profile = user_profile if user_profile in PROFILE_INSTRUCTIONS else "adulto_leigo"
    return ResponsePlan(
        theme=theme,
        topic_key=topic_key or "consulta_catolica",
        display_title=title,
        category=category,
        intents=_intent_set(question, spec, composite),
        depth=depth.value,
        components=components,
        active_components=active_components,
        dimensions=spec.dimensions if spec else _generic_dimensions(category),
        source_types=spec.source_types if spec else ("Sagrada Escritura", "Catecismo", "Magistério", "fontes do acervo"),
        introduction_required=True,
        conclusion_required=depth != DepthLevel.SUMMARY,
        continuation_required=len(active_components) < len(components),
        continuation_message=continuation_message,
        user_profile=profile,
        language=language,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        minimum_component_characters=minimum_chars,
        suggestions=spec.related[:5] if spec else (),
    )


class QueryIntentClassifier:
    @staticmethod
    def classify(question: str) -> tuple[str, ...]:
        plan = build_response_plan(question)
        return plan.intents


class QueryDecomposer:
    @staticmethod
    def decompose(question: str) -> tuple[str, ...]:
        return build_response_plan(question).components


class ResponsePlanner:
    @staticmethod
    def build(question: str, language: str = "pt-BR", user_profile: str = "adulto_leigo") -> ResponsePlan:
        return build_response_plan(question, language, user_profile)
