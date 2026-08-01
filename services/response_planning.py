from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import re

from services.catholic_taxonomy import TAXONOMY_VERSION, TopicSpec, classify_category, fold_text, match_topic
from services.gospel_policy import GospelQueryContext, classify_gospel_query
from services.query_analysis import QueryType, analyze_query


RESPONSE_STRATEGY_VERSION = "catena-gospel-priority-1"


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
    "crianca": "linguagem simples, concreta e breve, com exemplos seguros do cotidiano de uma criança",
    "adolescente": "linguagem direta e próxima, sem infantilização, relacionada aos desafios reais de adolescentes e jovens",
    "catequizando": "linguagem catequética acessível e explicação de termos técnicos",
    "adulto_iniciacao": "linguagem acessível a adulto em iniciação cristã",
    "catequista": "conteúdo didático, organizado e útil para transmitir a fé, com distinções doutrinais explicadas",
    "agente_pastoral": "linguagem pastoral clara, com aplicações prudentes",
    "estudante_teologia": "linguagem teológica aprofundada, com conceitos, distinções e referências, sem perder a fluidez",
    "clerigo": "linguagem teológico-pastoral precisa e concisa",
    "pesquisador": "linguagem técnica, referências precisas e distinção de graus de autoridade",
    "adulto_leigo": "linguagem clara, madura e pastoral, acessível a um adulto católico sem formação teológica especializada",
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
    closed_set: bool
    catalog_scope: str
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
    gospel: GospelQueryContext
    taxonomy_version: str = TAXONOMY_VERSION
    strategy_version: str = RESPONSE_STRATEGY_VERSION

    @property
    def composite(self) -> bool:
        return IntentKind.COMPOSITE.value in self.intents

    @property
    def is_gospel(self) -> bool:
        return self.gospel.is_gospel

    @property
    def profile_instruction(self) -> str:
        return PROFILE_INSTRUCTIONS.get(self.user_profile, PROFILE_INSTRUCTIONS["adulto_leigo"])

    @property
    def semantic_signature(self) -> str:
        base = "|".join((
            self.topic_key,
            self.category,
            self.depth,
            self.language,
            "fechado" if self.closed_set else "catalogo",
            fold_text(self.catalog_scope),
            *map(fold_text, self.components),
            self.gospel.cache_signature,
        ))
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["composite"] = self.composite
        data["profile_instruction"] = self.profile_instruction
        data["semantic_signature"] = self.semantic_signature
        data["query_classification"] = self.gospel.classification
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


def _intent_set(
    question: str,
    spec: TopicSpec | None,
    composite: bool,
    gospel: GospelQueryContext,
) -> tuple[str, ...]:
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
    if gospel.is_gospel:
        intents.append(IntentKind.BIBLICAL.value)
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
    gospel = classify_gospel_query(question)
    spec = match_topic(question)
    asks_summary = bool(SUMMARY_PATTERN.search(question))
    composite = bool(gospel.broad or (spec and (spec.components or not spec.closed_set)) or (
        ENUMERATIVE_PATTERN.search(question) and len(question.split()) > 2
    ))
    asks_deep = bool(DEEP_PATTERN.search(question))
    if asks_summary:
        depth = DepthLevel.SUMMARY
    elif asks_deep or composite:
        depth = DepthLevel.DEEP
    else:
        depth = DepthLevel.EXPLANATORY

    theme = gospel.episode if gospel.is_gospel else spec.title if spec else _fallback_theme(question)
    category = "evangelhos" if gospel.is_gospel else classify_category(question, spec)
    components = gospel.components if gospel.broad else spec.components if spec and composite else ()
    if depth == DepthLevel.SUMMARY:
        max_context_tokens, max_output_tokens, minimum_chars = 4200, 1200, 70
    elif depth == DepthLevel.DEEP:
        component_count = len(components)
        max_context_tokens = min(30000, max(12000, 5000 + component_count * 300))
        max_output_tokens = min(32000, max(6000, 2500 + component_count * 240))
        minimum_chars = 160 if component_count > 30 else 220
    else:
        max_context_tokens, max_output_tokens, minimum_chars = 6200, 2000, 120

    if gospel.is_gospel:
        if depth == DepthLevel.SUMMARY:
            max_context_tokens, max_output_tokens = 6500, 1600
        elif depth == DepthLevel.DEEP:
            max_context_tokens = min(30000, max(16000, max_context_tokens))
            max_output_tokens = min(32000, max(7000, max_output_tokens))
        else:
            max_context_tokens, max_output_tokens = 12000, 3500

    # A lista canônica inteira permanece ativa. Se o provedor atingir um limite
    # técnico, o serviço continua internamente antes de entregar a resposta.
    active_components = components
    topic_key = (
        f"gospel_{gospel.episode_key}"
        if gospel.is_gospel
        else spec.key if spec else re.sub(r"[^a-z0-9]+", "_", fold_text(theme)).strip("_")[:100]
    )
    title = gospel.episode if gospel.is_gospel else spec.title if spec else theme[:120]
    profile = user_profile if user_profile in PROFILE_INSTRUCTIONS else "adulto_leigo"
    return ResponsePlan(
        theme=theme,
        topic_key=topic_key or "consulta_catolica",
        display_title=title,
        category=category,
        intents=_intent_set(question, spec, composite, gospel),
        depth=depth.value,
        components=components,
        active_components=active_components,
        dimensions=(
            ("sentido literal", "contexto narrativo", "cristologia", "sentido moral", "sentido espiritual", "Igreja", "sacramentos", "escatologia")
            if gospel.is_gospel
            else spec.dimensions if spec else _generic_dimensions(category)
        ),
        source_types=(
            ("Sagrada Escritura", "Catena Áurea", "Catecismo", "Magistério", "Padres e Doutores", "Liturgia")
            if gospel.is_gospel
            else spec.source_types if spec else ("Sagrada Escritura", "Catecismo", "Magistério", "fontes do acervo")
        ),
        closed_set=spec.closed_set if spec else False,
        catalog_scope=spec.catalog_scope if spec else "",
        introduction_required=True,
        conclusion_required=depth != DepthLevel.SUMMARY,
        continuation_required=False,
        continuation_message="",
        user_profile=profile,
        language=language,
        max_context_tokens=max_context_tokens,
        max_output_tokens=max_output_tokens,
        minimum_component_characters=minimum_chars,
        suggestions=spec.related[:5] if spec and not gospel.is_gospel else (),
        gospel=gospel,
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
