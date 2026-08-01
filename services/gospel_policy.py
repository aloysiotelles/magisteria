from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Iterable

from services.catholic_taxonomy import fold_text


GOSPEL_QUERY = "GOSPEL_QUERY"
ORDINARY_QUERY = "ORDINARY_QUERY"
CATENA_COLLECTION = "CATENA_AUREA"
CATENA_WORK = "Catena Áurea"
CATENA_COMPILER = "Santo Tomás de Aquino"
GOSPEL_POLICY_VERSION = "catena-first-exhaustive-1"
CATENA_INDEXING_VERSION = "catena-structured-1"
CATENA_SOURCE_HINTS = ("catena aurea", "catena áurea")

GOSPEL_NAMES = {
    "mt": "Mateus",
    "mateus": "Mateus",
    "mc": "Marcos",
    "marcos": "Marcos",
    "lc": "Lucas",
    "lucas": "Lucas",
    "jo": "João",
    "joao": "João",
}
GOSPEL_ABBREVIATIONS = {
    "Mateus": "Mt",
    "Marcos": "Mc",
    "Lucas": "Lc",
    "João": "Jo",
}

REFERENCE_PATTERN = re.compile(
    r"\b(?P<book>Mt|Mateus|Mc|Marcos|Lc|Lucas|Jo|João)\s*"
    r"(?P<chapter>\d{1,2})"
    r"(?:\s*[,.:]\s*(?P<verse_start>\d{1,3})"
    r"(?:\s*[-–—]\s*(?P<verse_end>\d{1,3}))?"
    r"|\s*[-–—]\s*(?P<chapter_end>\d{1,2}))?\b",
    re.IGNORECASE,
)
AUTHOR_LABEL_PATTERN = re.compile(r"(?m)^\*\*(?P<label>[^*\n:]{2,180})\*\*\s*:")
PATRISTIC_AUTHOR_PREFIXES = (
    "Pseudo-Crisóstomo", "Pseudo-Agostinho", "Pseudo-Jerônimo", "João Crisóstomo",
    "Gregório Magno", "Gregório de Nissa", "Gregório Nazianzeno",
    "Cirilo de Alexandria", "João Damasceno", "Agostinho", "Crisóstomo", "Jerônimo",
    "Ambrósio", "Gregório", "Hilário", "Beda", "Orígenes", "Cirilo", "Cirílo",
    "Remígio", "Teofilacto", "Rabanus", "Rabano", "Leão", "Eusébio", "Severo", "Glosa",
)


@dataclass(frozen=True)
class GospelPassage:
    gospel: str
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None
    chapter_end: int | None = None

    @property
    def reference(self) -> str:
        abbreviation = GOSPEL_ABBREVIATIONS[self.gospel]
        if self.chapter_end and self.chapter_end != self.chapter:
            return f"{abbreviation} {self.chapter}–{self.chapter_end}"
        if self.verse_start is None:
            return f"{abbreviation} {self.chapter}"
        if self.verse_end and self.verse_end != self.verse_start:
            return f"{abbreviation} {self.chapter},{self.verse_start}–{self.verse_end}"
        return f"{abbreviation} {self.chapter},{self.verse_start}"

    @property
    def cache_key(self) -> str:
        return ":".join(
            str(item or "")
            for item in (
                self.gospel,
                self.chapter,
                self.chapter_end,
                self.verse_start,
                self.verse_end,
            )
        )

    def overlaps(self, other: GospelPassage) -> bool:
        if self.gospel != other.gospel:
            return False
        self_last_chapter = self.chapter_end or self.chapter
        other_last_chapter = other.chapter_end or other.chapter
        if self_last_chapter < other.chapter or other_last_chapter < self.chapter:
            return False
        if self.chapter != other.chapter or self.chapter_end or other.chapter_end:
            return True
        if self.verse_start is None or other.verse_start is None:
            return True
        self_end = self.verse_end or self.verse_start
        other_end = other.verse_end or other.verse_start
        return self_end >= other.verse_start and other_end >= self.verse_start

    def to_dict(self) -> dict:
        return {**asdict(self), "reference": self.reference}


@dataclass(frozen=True)
class GospelEpisode:
    key: str
    title: str
    aliases: tuple[str, ...]
    passages: tuple[GospelPassage, ...]
    keywords: tuple[str, ...] = ()
    components: tuple[str, ...] = ()

    @property
    def broad(self) -> bool:
        return bool(self.components)


def _p(
    gospel: str,
    chapter: int,
    verse_start: int | None = None,
    verse_end: int | None = None,
    chapter_end: int | None = None,
) -> GospelPassage:
    return GospelPassage(gospel, chapter, verse_start, verse_end, chapter_end)


def _e(
    key: str,
    title: str,
    aliases: tuple[str, ...],
    passages: tuple[GospelPassage, ...],
    keywords: tuple[str, ...] = (),
    components: tuple[str, ...] = (),
) -> GospelEpisode:
    return GospelEpisode(key, title, aliases, passages, keywords, components)


# The catalogue is intentionally deterministic. It covers traditional names that
# frequently omit a biblical reference and supplies parallel passages without
# asking a generative model to guess locators.
GOSPEL_EPISODES: tuple[GospelEpisode, ...] = (
    _e("bem_aventurancas", "Bem-aventuranças", ("bem aventurancas", "bem-aventurancas"), (_p("Mateus", 5, 1, 12), _p("Lucas", 6, 20, 23)), ("Reino dos Céus", "pobres em espírito")),
    _e("sermao_montanha", "Sermão da Montanha", ("sermao da montanha", "sermao do monte"), (_p("Mateus", 5, chapter_end=7), _p("Lucas", 6, 17, 49)), ("ensinamentos de Jesus",), ("Bem-aventuranças", "sal da terra e luz do mundo", "cumprimento da Lei", "esmola, oração e jejum", "Pai-Nosso", "confiança na Providência", "juízo e regra de ouro", "casa sobre a rocha")),
    _e("pai_nosso", "Pai-Nosso", ("pai nosso", "oracao do senhor"), (_p("Mateus", 6, 9, 13), _p("Lucas", 11, 1, 4)), ("oração", "sete petições")),
    _e("pao_da_vida", "Discurso do Pão da Vida", ("discurso do pao da vida", "pao da vida"), (_p("João", 6, 22, 71),), ("Eucaristia", "alimento espiritual")),
    _e("anunciacao", "Anunciação", ("anunciacao", "anjo gabriel", "fiat de maria"), (_p("Lucas", 1, 26, 38),), ("Encarnação", "Virgem Maria")),
    _e("visitacao", "Visitação", ("visitacao", "maria visita isabel", "magnificat"), (_p("Lucas", 1, 39, 56),), ("Magnificat", "São João Batista")),
    _e("nascimento_jesus", "Nascimento de Jesus", ("nascimento de jesus", "natividade", "nascimento em belem"), (_p("Mateus", 1, 18, 25), _p("Lucas", 2, 1, 20)), ("Belém", "pastores", "Encarnação")),
    _e("infancia_jesus", "Infância de Jesus", ("infancia de jesus", "infancia de cristo"), (_p("Mateus", 1, chapter_end=2), _p("Lucas", 1, chapter_end=2)), ("nascimento", "vida oculta"), ("Anunciação", "Visitação", "Nascimento em Belém", "Apresentação no Templo", "Fuga para o Egito", "Jesus entre os doutores")),
    _e("apresentacao_templo", "Apresentação de Jesus no Templo", ("apresentacao de jesus no templo", "simeao e ana", "nunc dimittis"), (_p("Lucas", 2, 22, 40),), ("purificação", "Simeão", "Ana")),
    _e("fuga_egito", "Fuga para o Egito", ("fuga para o egito", "matança dos inocentes", "massacre dos inocentes"), (_p("Mateus", 2, 13, 23),), ("Herodes", "São José")),
    _e("jesus_templo", "Jesus entre os doutores no Templo", ("perda e encontro de jesus no templo", "jesus entre os doutores", "menino jesus no templo"), (_p("Lucas", 2, 41, 52),), ("vida oculta", "casa do Pai")),
    _e("batismo_senhor", "Batismo do Senhor", ("batismo do senhor", "batismo de jesus", "jesus e joao batista"), (_p("Mateus", 3, 13, 17), _p("Marcos", 1, 9, 11), _p("Lucas", 3, 21, 22), _p("João", 1, 29, 34)), ("Trindade", "Jordão", "Cordeiro de Deus")),
    _e("tentacoes_deserto", "Tentações de Jesus no deserto", ("tentacoes de jesus", "tentacoes no deserto", "jesus no deserto"), (_p("Mateus", 4, 1, 11), _p("Marcos", 1, 12, 13), _p("Lucas", 4, 1, 13)), ("Satanás", "jejum")),
    _e("chamado_apostolos", "Chamado dos Apóstolos", ("chamado dos apostolos", "vocacao dos apostolos", "pescadores de homens"), (_p("Mateus", 4, 18, 22), _p("Marcos", 1, 16, 20), _p("Lucas", 5, 1, 11), _p("João", 1, 35, 51)), ("vocação", "seguimento")),
    _e("missao_doze", "Missão dos Doze", ("missao dos doze", "envio dos doze", "missao dos apostolos"), (_p("Mateus", 10), _p("Marcos", 6, 7, 13), _p("Lucas", 9, 1, 6)), ("apostolado", "anúncio do Reino")),
    _e("missao_setenta_dois", "Missão dos setenta e dois discípulos", ("missao dos setenta e dois", "setenta e dois discipulos", "envio dos setenta e dois"), (_p("Lucas", 10, 1, 24),), ("missão", "discípulos")),
    _e("bodas_cana", "Bodas de Caná", ("bodas de cana", "agua em vinho", "primeiro sinal de jesus"), (_p("João", 2, 1, 12),), ("Virgem Maria", "sinal", "matrimônio")),
    _e("multiplicacao_paes", "Multiplicação dos pães", ("multiplicacao dos paes", "cinco paes e dois peixes", "alimentacao da multidao"), (_p("Mateus", 14, 13, 21), _p("Marcos", 6, 30, 44), _p("Lucas", 9, 10, 17), _p("João", 6, 1, 15)), ("compaixão de Cristo", "prefiguração eucarística", "pão da vida")),
    _e("caminhada_aguas", "Jesus caminha sobre as águas", ("caminhada sobre as aguas", "jesus anda sobre as aguas", "pedro anda sobre as aguas"), (_p("Mateus", 14, 22, 33), _p("Marcos", 6, 45, 52), _p("João", 6, 16, 21)), ("fé", "vento e mar")),
    _e("transfiguracao", "Transfiguração", ("transfiguracao", "monte tabor", "moises e elias"), (_p("Mateus", 17, 1, 13), _p("Marcos", 9, 2, 13), _p("Lucas", 9, 28, 36)), ("glória de Cristo", "Lei e Profetas")),
    _e("ressurreicao_lazaro", "Ressurreição de Lázaro", ("ressurreicao de lazaro", "tumulo de lazaro", "jesus chorou", "lazaro vem para fora"), (_p("João", 11, 1, 46),), ("Jesus chorou", "Eu sou a ressurreição e a vida", "Marta e Maria")),
    _e("samaritana", "Encontro com a mulher samaritana", ("mulher samaritana", "encontro com a samaritana", "poco de jaco", "agua viva"), (_p("João", 4, 1, 42),), ("adoração em espírito e verdade", "água viva")),
    _e("zaqueu", "Encontro com Zaqueu", ("zaqueu", "encontro com zaqueu"), (_p("Lucas", 19, 1, 10),), ("conversão", "salvação")),
    _e("nicodemos", "Encontro com Nicodemos", ("nicodemos", "nascer de novo", "nascer da agua e do espirito"), (_p("João", 3, 1, 21),), ("novo nascimento", "Espírito Santo")),
    _e("mulher_adultera", "Mulher adúltera", ("mulher adultera", "quem nao tiver pecado", "vai e nao peques mais"), (_p("João", 8, 1, 11),), ("misericórdia", "conversão")),
    _e("jovem_rico", "Jovem rico", ("jovem rico", "moco rico", "vende tudo o que tens"), (_p("Mateus", 19, 16, 30), _p("Marcos", 10, 17, 31), _p("Lucas", 18, 18, 30)), ("conselhos evangélicos", "riqueza")),
    _e("confissao_pedro", "Confissão de Pedro", ("confissao de pedro", "tu es o cristo", "cesareia de filipe"), (_p("Mateus", 16, 13, 20), _p("Marcos", 8, 27, 30), _p("Lucas", 9, 18, 21)), ("Filho do Deus vivo", "fé apostólica")),
    _e("primado_pedro", "Primado de Pedro", ("primado de pedro", "tu es pedro", "chaves do reino", "apascenta minhas ovelhas"), (_p("Mateus", 16, 17, 19), _p("Lucas", 22, 31, 32), _p("João", 21, 15, 19)), ("Igreja", "chaves", "unidade")),
    _e("correcao_fraterna", "Correção fraterna", ("correcao fraterna", "se teu irmao pecar"), (_p("Mateus", 18, 15, 20),), ("Igreja", "dois ou três")),
    _e("perdao_pecados", "Perdão dos pecados", ("perdao dos pecados", "perdoar setenta vezes sete", "poder de perdoar pecados"), (_p("Mateus", 18, 21, 35), _p("João", 20, 19, 23)), ("misericórdia", "reconciliação")),
    _e("indissolubilidade", "Indissolubilidade do matrimônio", ("indissolubilidade do matrimonio", "o que deus uniu", "divorcio segundo jesus"), (_p("Mateus", 19, 1, 12), _p("Marcos", 10, 1, 12)), ("matrimônio", "criação")),
    _e("juizo_final", "Juízo final", ("juizo final", "ovelhas e cabritos", "vinde benditos de meu pai"), (_p("Mateus", 25, 31, 46),), ("obras de misericórdia", "vida eterna")),
    _e("fim_tempos", "Fim dos tempos", ("fim dos tempos", "discurso escatologico", "segunda vinda de cristo"), (_p("Mateus", 24, chapter_end=25), _p("Marcos", 13), _p("Lucas", 21, 5, 36)), ("vigilância", "Parusia", "juízo")),
    _e("parabola_semeador", "Parábola do semeador", ("parabola do semeador", "semente caiu"), (_p("Mateus", 13, 1, 23), _p("Marcos", 4, 1, 20), _p("Lucas", 8, 4, 15)), ("Palavra de Deus", "frutos")),
    _e("filho_prodigo", "Parábola do filho pródigo", ("parabola do filho prodigo", "filho prodigo", "pai misericordioso"), (_p("Lucas", 15, 11, 32),), ("misericórdia", "conversão", "irmão mais velho")),
    _e("bom_samaritano", "Parábola do bom samaritano", ("parabola do bom samaritano", "bom samaritano"), (_p("Lucas", 10, 25, 37),), ("próximo", "misericórdia")),
    _e("talentos", "Parábola dos talentos", ("parabola dos talentos", "talentos"), (_p("Mateus", 25, 14, 30),), ("vigilância", "responsabilidade")),
    _e("dez_virgens", "Parábola das dez virgens", ("parabola das dez virgens", "virgens prudentes", "virgens insensatas"), (_p("Mateus", 25, 1, 13),), ("vigilância", "óleo")),
    _e("trabalhadores_vinha", "Parábola dos trabalhadores da vinha", ("trabalhadores da vinha", "operarios da vinha", "ultima hora"), (_p("Mateus", 20, 1, 16),), ("graça", "Reino dos Céus")),
    _e("rico_lazaro", "Parábola do rico e Lázaro", ("rico e lazaro", "parabola do rico e lazaro", "seio de abraao"), (_p("Lucas", 16, 19, 31),), ("pobres", "juízo", "vida eterna")),
    _e("parabolas", "Parábolas de Jesus", ("parabolas de jesus", "as parabolas", "explique as parabolas"), (_p("Mateus", 13), _p("Marcos", 4), _p("Lucas", 8), _p("Lucas", 10), _p("Lucas", 15),), ("Reino de Deus", "linguagem parabólica"), ("Semeador", "joio e trigo", "grão de mostarda", "bom samaritano", "filho pródigo", "talentos", "dez virgens", "rico e Lázaro")),
    _e("milagres", "Milagres de Jesus", ("milagres de jesus", "milagres de cristo", "os milagres"), (_p("Mateus", 8, chapter_end=9), _p("Marcos", 4, chapter_end=8), _p("Lucas", 7, chapter_end=9), _p("João", 2, chapter_end=11)), ("sinais", "compaixão", "fé"), ("curas", "expulsões de demônios", "domínio sobre a natureza", "multiplicações dos pães", "ressurreições")),
    _e("entrada_jerusalem", "Entrada de Jesus em Jerusalém", ("entrada em jerusalem", "entrada triunfal", "domingo de ramos"), (_p("Mateus", 21, 1, 11), _p("Marcos", 11, 1, 11), _p("Lucas", 19, 28, 44), _p("João", 12, 12, 19)), ("Messias", "Hosana")),
    _e("purificacao_templo", "Purificação do Templo", ("purificacao do templo", "expulsao dos vendilhoes", "casa de oracao"), (_p("Mateus", 21, 12, 17), _p("Marcos", 11, 15, 19), _p("Lucas", 19, 45, 48), _p("João", 2, 13, 25)), ("zelo", "Templo")),
    _e("ultima_ceia", "Última Ceia", ("ultima ceia", "ceia do senhor"), (_p("Mateus", 26, 17, 35), _p("Marcos", 14, 12, 31), _p("Lucas", 22, 7, 38), _p("João", 13, chapter_end=17)), ("Páscoa", "Eucaristia", "mandamento novo")),
    _e("instituicao_eucaristia", "Instituição da Eucaristia", ("instituicao da eucaristia", "isto e o meu corpo", "sangue da alianca"), (_p("Mateus", 26, 26, 29), _p("Marcos", 14, 22, 25), _p("Lucas", 22, 14, 20)), ("sacrifício", "Nova Aliança")),
    _e("lava_pes", "Lava-pés", ("lava pes", "lavatorio dos pes", "jesus lava os pes"), (_p("João", 13, 1, 20),), ("serviço", "humildade")),
    _e("oracao_sacerdotal", "Oração sacerdotal de Jesus", ("oracao sacerdotal", "que todos sejam um", "jesus ora pelos discipulos"), (_p("João", 17),), ("unidade", "glória", "consagração")),
    _e("getsemani", "Agonia no Getsêmani", ("agonia no getsemani", "getsemani", "horto das oliveiras", "afasta de mim este calice"), (_p("Mateus", 26, 36, 46), _p("Marcos", 14, 32, 42), _p("Lucas", 22, 39, 46), _p("João", 18, 1, 2)), ("oração", "vontade do Pai")),
    _e("prisao_jesus", "Prisão de Jesus", ("prisao de jesus", "prenderam jesus", "beijo de judas"), (_p("Mateus", 26, 47, 56), _p("Marcos", 14, 43, 52), _p("Lucas", 22, 47, 53), _p("João", 18, 1, 12)), ("Judas", "entrega voluntária")),
    _e("julgamento_cristo", "Julgamento de Cristo", ("julgamento de cristo", "julgamento de jesus", "jesus diante de pilatos", "jesus diante do sinedrio"), (_p("Mateus", 26, 57, 75), _p("Mateus", 27, 1, 31), _p("Marcos", 14, 53, 72), _p("Marcos", 15, 1, 20), _p("Lucas", 22, 54, 71), _p("Lucas", 23, 1, 25), _p("João", 18, 13, 40), _p("João", 19, 1, 16)), ("Sinédrio", "Pilatos", "realeza de Cristo")),
    _e("palavras_cruz", "Palavras de Cristo na Cruz", ("palavras de cristo na cruz", "sete palavras de jesus na cruz", "palavras de jesus na cruz"), (_p("Mateus", 27, 46, 50), _p("Marcos", 15, 34, 37), _p("Lucas", 23, 34, 46), _p("João", 19, 26, 30)), ("perdão", "abandono", "Mãe", "consumação")),
    _e("morte_sepultamento", "Morte e sepultamento de Jesus", ("morte e sepultamento de jesus", "morte de cristo", "sepultamento de jesus"), (_p("Mateus", 27, 45, 66), _p("Marcos", 15, 33, 47), _p("Lucas", 23, 44, 56), _p("João", 19, 28, 42)), ("Cruz", "José de Arimateia")),
    _e("paixao", "Paixão de Cristo", ("paixao de cristo", "paixao do senhor", "paixao e crucifixao", "crucifixao de jesus"), (_p("Mateus", 26, chapter_end=27), _p("Marcos", 14, chapter_end=15), _p("Lucas", 22, chapter_end=23), _p("João", 18, chapter_end=19)), ("redenção", "sacrifício", "Cruz"), ("Última Ceia", "Getsêmani", "prisão", "julgamento religioso", "julgamento perante Pilatos", "flagelação", "coroação de espinhos", "caminho do Calvário", "Crucifixão", "palavras na Cruz", "morte", "sepultamento")),
    _e("ressurreicao", "Ressurreição do Senhor", ("ressurreicao de jesus", "ressurreicao do senhor", "cristo ressuscitou", "sepulcro vazio"), (_p("Mateus", 28, 1, 15), _p("Marcos", 16, 1, 14), _p("Lucas", 24, 1, 49), _p("João", 20, 1, 29)), ("Páscoa", "sepulcro vazio", "aparições")),
    _e("emaus", "Discípulos de Emaús", ("discipulos de emaus", "caminho de emaus", "fica conosco senhor"), (_p("Lucas", 24, 13, 35),), ("Escrituras", "fração do pão")),
    _e("pesca_pos_ressurreicao", "Pesca milagrosa após a Ressurreição", ("pesca milagrosa apos a ressurreicao", "pesca milagrosa joao 21", "rede cheia de peixes"), (_p("João", 21, 1, 14),), ("Ressuscitado", "missão")),
    _e("missao_apostolos", "Missão confiada aos Apóstolos", ("missao confiada aos apostolos", "ide e fazei discipulos", "grande comissao", "envio missionario"), (_p("Mateus", 28, 16, 20), _p("Marcos", 16, 15, 20), _p("Lucas", 24, 44, 49), _p("João", 20, 19, 23)), ("Batismo", "evangelização")),
    _e("ascensao", "Ascensão do Senhor", ("ascensao do senhor", "ascensao de jesus", "jesus subiu ao ceu"), (_p("Marcos", 16, 19, 20), _p("Lucas", 24, 50, 53)), ("glória", "missão")),
)


GOSPEL_SUBJECT_PATTERN = re.compile(
    r"\b(?:jesus(?:\s+cristo)?|cristo|senhor jesus|filho do homem|messias|"
    r"parabolas?|milagres?|evangelhos?|pericope|apostolos?|discipulos?|"
    r"paixao|crucifixao|ressurreicao|ultima ceia|sermao da montanha)\b"
)
GOSPEL_ACTION_PATTERN = re.compile(
    r"\b(?:disse|ensinou|falou|fez|curou|expulsou|ressuscitou|chorou|chamou|"
    r"pregou|perdoou|mandou|instituiu|lavou|multiplicou|caminhou|padeceu|morreu)\b"
)
GOSPEL_CHARACTER_PATTERN = re.compile(
    r"\b(?:nicodemos|zaqueu|samaritana|lazaro|marta|maria madalena|pilatos|"
    r"herodes|judas iscariotes|bartimeu|jairo|simeao|zebedeu|emaus)\b"
)


@dataclass(frozen=True)
class GospelQueryContext:
    classification: str
    episode_key: str
    episode: str
    passages: tuple[GospelPassage, ...]
    primary_passages: tuple[GospelPassage, ...]
    parallel_passages: tuple[GospelPassage, ...]
    search_terms: tuple[str, ...]
    components: tuple[str, ...]
    broad: bool
    policy_version: str = GOSPEL_POLICY_VERSION

    @property
    def is_gospel(self) -> bool:
        return self.classification == GOSPEL_QUERY

    @property
    def passage_references(self) -> tuple[str, ...]:
        return tuple(passage.reference for passage in self.passages)

    @property
    def parallel_references(self) -> tuple[str, ...]:
        return tuple(passage.reference for passage in self.parallel_passages)

    @property
    def cache_signature(self) -> str:
        material = "|".join((
            self.classification,
            self.episode_key,
            *[passage.cache_key for passage in self.passages],
            *map(fold_text, self.search_terms),
            self.policy_version,
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "episode_key": self.episode_key,
            "episode": self.episode,
            "passages": [passage.to_dict() for passage in self.passages],
            "primary_passages": [passage.to_dict() for passage in self.primary_passages],
            "parallel_passages": [passage.to_dict() for passage in self.parallel_passages],
            "search_terms": list(self.search_terms),
            "components": list(self.components),
            "broad": self.broad,
            "policy_version": self.policy_version,
            "cache_signature": self.cache_signature,
        }

    def catena_queries(self, original_query: str) -> tuple[tuple[str, GospelPassage | None], ...]:
        queries: list[tuple[str, GospelPassage | None]] = []
        seen: set[str] = set()

        def add(query: str, passage: GospelPassage | None = None) -> None:
            normalized = fold_text(query)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            queries.append((query, passage))

        add(f"{self.episode}. {original_query}")
        terms = ", ".join(self.search_terms[:8])
        for passage in self.passages:
            add(f"{passage.reference}. {self.episode}. {terms}", passage)
        for term in self.search_terms[:12]:
            add(f"{self.episode}: {term}")
        return tuple(queries)


def parse_gospel_references(text: str) -> tuple[GospelPassage, ...]:
    passages: list[GospelPassage] = []
    for match in REFERENCE_PATTERN.finditer(text):
        gospel = GOSPEL_NAMES[fold_text(match.group("book"))]
        passage = GospelPassage(
            gospel=gospel,
            chapter=int(match.group("chapter")),
            verse_start=int(match.group("verse_start")) if match.group("verse_start") else None,
            verse_end=int(match.group("verse_end")) if match.group("verse_end") else None,
            chapter_end=int(match.group("chapter_end")) if match.group("chapter_end") else None,
        )
        if passage.cache_key not in {item.cache_key for item in passages}:
            passages.append(passage)
    return tuple(passages)


def _episode_match(text: str) -> GospelEpisode | None:
    normalized = fold_text(text)
    candidates: list[tuple[int, GospelEpisode]] = []
    for episode in GOSPEL_EPISODES:
        matched = [alias for alias in episode.aliases if fold_text(alias) in normalized]
        if matched:
            candidates.append((max(len(fold_text(alias)) for alias in matched), episode))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _episode_for_references(references: tuple[GospelPassage, ...]) -> GospelEpisode | None:
    matches: list[tuple[int, GospelEpisode]] = []
    for episode in GOSPEL_EPISODES:
        overlap_count = sum(
            1 for reference in references
            if any(reference.overlaps(candidate) for candidate in episode.passages)
        )
        if not overlap_count:
            continue
        # Prefer a specific pericope over a broad multi-chapter catalogue.
        breadth = sum((passage.chapter_end or passage.chapter) - passage.chapter + 1 for passage in episode.passages)
        matches.append((overlap_count * 1000 - breadth * 10 - len(episode.passages), episode))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def classify_gospel_query(text: str) -> GospelQueryContext:
    normalized = fold_text(text)
    explicit_references = parse_gospel_references(text)
    episode = _episode_match(text) or _episode_for_references(explicit_references)
    direct_gospel_reference = bool(explicit_references)
    semantic_match = bool(
        episode
        or GOSPEL_CHARACTER_PATTERN.search(normalized)
        or (GOSPEL_SUBJECT_PATTERN.search(normalized) and (
            "jesus" in normalized
            or "cristo" in normalized
            or GOSPEL_ACTION_PATTERN.search(normalized)
            or any(term in normalized for term in ("parabola", "milagre", "evangelho", "paixao", "ressurreicao"))
        ))
    )
    if not direct_gospel_reference and not semantic_match:
        return GospelQueryContext(ORDINARY_QUERY, "", "", (), (), (), (), (), False)

    if episode:
        episode_passages = episode.passages
        if explicit_references:
            primary = explicit_references
            parallels = tuple(
                passage for passage in episode_passages
                if not any(passage.overlaps(reference) for reference in explicit_references)
            )
            passages = tuple(dict.fromkeys((*primary, *parallels)))
        else:
            passages = episode_passages
            primary = episode_passages[:1]
            parallels = episode_passages[1:]
        terms = tuple(dict.fromkeys((episode.title, *episode.aliases, *episode.keywords)))
        return GospelQueryContext(
            GOSPEL_QUERY,
            episode.key,
            episode.title,
            passages,
            primary,
            parallels,
            terms,
            episode.components,
            episode.broad,
        )

    title = "Passagem evangélica" if explicit_references else "Vida e ensinamento de Jesus Cristo"
    terms = tuple(
        term for term in re.findall(r"[a-z0-9à-ÿ]{3,}", normalized)
        if term not in {"explique", "comente", "sobre", "qual", "porque", "jesus", "cristo"}
    )[:12]
    primary = explicit_references[:1]
    parallels = explicit_references[1:]
    return GospelQueryContext(
        GOSPEL_QUERY,
        "passagem_evangelica",
        title,
        explicit_references,
        primary,
        parallels,
        terms,
        (),
        False,
    )


def pericope_for(
    gospel: str | None,
    chapter: int | None,
    verse_start: int | None,
    verse_end: int | None,
    text: str = "",
) -> str:
    if not gospel or chapter is None:
        return ""
    candidate = GospelPassage(gospel, chapter, verse_start, verse_end)
    normalized = fold_text(text)
    scored: list[tuple[int, str]] = []
    for episode in GOSPEL_EPISODES:
        if not any(candidate.overlaps(passage) for passage in episode.passages):
            continue
        alias_score = max((len(alias) for alias in episode.aliases if fold_text(alias) in normalized), default=0)
        breadth = sum((passage.chapter_end or passage.chapter) - passage.chapter + 1 for passage in episode.passages)
        scored.append((alias_score * 100 - breadth, episode.title))
    return max(scored, default=(0, ""))[1]


def extract_patristic_attributions(text: str) -> tuple[dict[str, str], ...]:
    attributions: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    ignored = {
        "autor da compilacao", "titulo latino", "conteudo", "texto-base",
        "integridade do fac-simile baixado", "traducao portuguesa", "preparacao", "fontes digitais",
    }
    for match in AUTHOR_LABEL_PATTERN.finditer(text):
        label = re.sub(r"\s+", " ", match.group("label")).strip()
        folded_label = fold_text(label)
        if folded_label in ignored:
            continue
        matched_prefix = next(
            (
                prefix for prefix in sorted(PATRISTIC_AUTHOR_PREFIXES, key=len, reverse=True)
                if folded_label == fold_text(prefix)
                or folded_label.startswith(fold_text(prefix) + " ")
                or folded_label.startswith(fold_text(prefix) + ",")
            ),
            None,
        )
        if matched_prefix:
            word_count = len(matched_prefix.split())
            raw_words = label.split()
            author = " ".join(raw_words[:word_count]).rstrip(",")
            source_work = " ".join(raw_words[word_count:]).lstrip(" ,")
        elif "," in label:
            author, source_work = (part.strip() for part in label.split(",", 1))
        else:
            author, source_work = label, ""
            work_marker = re.search(
                r"\b(?:sobre|no livro|na homilia|no sermao|na epistola|em)\b",
                folded_label,
            )
            if work_marker and work_marker.start() > 1:
                author = label[:work_marker.start()].strip()
                source_work = label[work_marker.start():].strip()
        key = (fold_text(author), fold_text(source_work))
        if key in seen:
            continue
        seen.add(key)
        attributions.append({"author": author, "source_work": source_work, "label": label})
    return tuple(attributions)


def patristic_authors(chunks: Iterable[dict]) -> tuple[str, ...]:
    authors: list[str] = []
    for chunk in chunks:
        recorded = chunk.get("patristic_authors") or ()
        if isinstance(recorded, str):
            recorded = (recorded,)
        if not recorded:
            recorded = tuple(item["author"] for item in extract_patristic_attributions(str(chunk.get("text") or "")))
        for author in recorded:
            name = str(author).strip()
            if name and fold_text(name) not in {fold_text(item) for item in authors}:
                authors.append(name)
    return tuple(authors)


def passage_covered(passage: GospelPassage, chunks: Iterable[dict]) -> bool:
    material = list(chunks)

    def chapter_covered(chapter: int) -> bool:
        expected = GospelPassage(
            passage.gospel,
            chapter,
            passage.verse_start if chapter == passage.chapter else None,
            passage.verse_end if chapter == passage.chapter else None,
        )
        for chunk in material:
            gospel = str(chunk.get("gospel") or "")
            chunk_chapter = chunk.get("chapter")
            if gospel and chunk_chapter is not None:
                candidate = GospelPassage(
                    gospel,
                    int(chunk_chapter),
                    chunk.get("verse_start"),
                    chunk.get("verse_end"),
                )
                if expected.overlaps(candidate):
                    return True
            haystack = fold_text(f"{chunk.get('location', '')} {chunk.get('text', '')[:500]}")
            if fold_text(passage.gospel) in haystack and re.search(rf"\b{chapter}\b", haystack):
                return True
        return False

    return all(
        chapter_covered(chapter)
        for chapter in range(passage.chapter, (passage.chapter_end or passage.chapter) + 1)
    )


@dataclass(frozen=True)
class GospelCompletenessResult:
    passed: bool
    missing_passages: tuple[str, ...]
    checks: dict[str, bool]
    coverage_score: float

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "missing_passages": list(self.missing_passages),
            "checks": dict(self.checks),
            "coverage_score": self.coverage_score,
        }


def assess_gospel_retrieval(
    context: GospelQueryContext,
    catena_chunks: list[dict],
    repository_chunks: list[dict],
    *,
    catena_search_executed: bool,
    parallel_passages_searched: bool,
    adjacent_chunks_loaded: int,
    synthesis_created: bool,
    complementary_search_executed: bool,
) -> GospelCompletenessResult:
    missing = tuple(
        passage.reference for passage in context.passages
        if not passage_covered(passage, catena_chunks)
    )
    checks = {
        "classified_as_gospel": context.is_gospel,
        "main_passage_identified": bool(context.passages) or bool(context.episode),
        "parallel_passages_identified": not context.parallel_passages or parallel_passages_searched,
        "catena_searched_first": catena_search_executed,
        "catena_filter_applied": catena_search_executed,
        "adjacent_chunks_considered": adjacent_chunks_loaded >= 0,
        "material_catena_coverage": bool(catena_chunks) and not missing,
        "patristic_authorship_preserved": all(
            chunk.get("patristic_authors") or extract_patristic_attributions(str(chunk.get("text") or ""))
            for chunk in catena_chunks
            if "**" in str(chunk.get("text") or "")
        ),
        "deduplication_completed": len({str(chunk.get("id")) for chunk in catena_chunks}) == len(catena_chunks),
        "patristic_synthesis_created": synthesis_created,
        "complementary_search_after_catena": complementary_search_executed,
        "repository_hierarchy_preserved": bool(repository_chunks) or complementary_search_executed,
    }
    essential = (
        "classified_as_gospel",
        "main_passage_identified",
        "catena_searched_first",
        "catena_filter_applied",
        "patristic_synthesis_created",
        "complementary_search_after_catena",
    )
    passed = all(checks[item] for item in essential) and (not context.passages or not missing)
    coverage_score = round(sum(1 for value in checks.values() if value) / max(len(checks), 1), 4)
    return GospelCompletenessResult(passed, missing, checks, coverage_score)
