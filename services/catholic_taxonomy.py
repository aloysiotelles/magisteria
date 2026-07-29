from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


TAXONOMY_VERSION = "2026.07.1"


def fold_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").casefold())
    folded = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", folded).strip()


@dataclass(frozen=True)
class TopicSpec:
    key: str
    title: str
    category: str
    aliases: tuple[str, ...]
    components: tuple[str, ...]
    dimensions: tuple[str, ...]
    source_types: tuple[str, ...]
    related: tuple[str, ...]
    long_form_group: str = ""


OLD_TESTAMENT = (
    "Gênesis", "Êxodo", "Levítico", "Números", "Deuteronômio",
    "Josué", "Juízes", "Rute", "1 Samuel", "2 Samuel", "1 Reis", "2 Reis",
    "1 Crônicas", "2 Crônicas", "Esdras", "Neemias", "Tobias", "Judite", "Ester",
    "1 Macabeus", "2 Macabeus", "Jó", "Salmos", "Provérbios", "Eclesiastes",
    "Cântico dos Cânticos", "Sabedoria", "Eclesiástico", "Isaías", "Jeremias",
    "Lamentações", "Baruc", "Ezequiel", "Daniel", "Oseias", "Joel", "Amós",
    "Abdias", "Jonas", "Miqueias", "Naum", "Habacuc", "Sofonias", "Ageu",
    "Zacarias", "Malaquias",
)
NEW_TESTAMENT = (
    "Mateus", "Marcos", "Lucas", "João", "Atos dos Apóstolos", "Romanos",
    "1 Coríntios", "2 Coríntios", "Gálatas", "Efésios", "Filipenses", "Colossenses",
    "1 Tessalonicenses", "2 Tessalonicenses", "1 Timóteo", "2 Timóteo", "Tito",
    "Filêmon", "Hebreus", "Tiago", "1 Pedro", "2 Pedro", "1 João", "2 João",
    "3 João", "Judas", "Apocalipse",
)


COMMON_DOCTRINAL_DIMENSIONS = (
    "definição", "fundamento bíblico", "formulação doutrinal", "significado teológico",
    "relação com Cristo e a Igreja", "aplicação espiritual e pastoral", "referências",
)


TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec(
        "trindade", "Santíssima Trindade", "teologia_dogmatica",
        ("santissima trindade", "trindade", "deus uno e trino"),
        ("Unidade da natureza divina", "Distinção das Pessoas", "Deus Pai", "Deus Filho", "Deus Espírito Santo", "Relações trinitárias", "Missões divinas"),
        ("definição", "unidade e trindade", "fundamento bíblico", "relações", "missões", "vida cristã"),
        ("Sagrada Escritura", "Concílios", "Catecismo", "Magistério"),
        ("Nomes e missão do Espírito Santo", "Credo Niceno-Constantinopolitano", "Encarnação"),
    ),
    TopicSpec(
        "sacramentos", "Os sete sacramentos", "sacramentos_liturgia",
        ("sete sacramentos", "sacramentos da igreja", "sacramentos catolicos", "sacramentos", "sacramento"),
        ("Batismo", "Confirmação", "Eucaristia", "Penitência e Reconciliação", "Unção dos Enfermos", "Ordem", "Matrimônio"),
        ("definição", "instituição por Cristo", "fundamento bíblico", "matéria e forma", "ministro e sujeito", "efeitos", "celebração", "significado espiritual"),
        ("Sagrada Escritura", "Catecismo", "Concílios", "textos litúrgicos", "Direito Canônico"),
        ("Sacramentos da iniciação cristã", "Matéria e forma dos sacramentos", "Caráter sacramental", "Validade e liceidade", "Sacramentos e sacramentais"),
    ),
    TopicSpec(
        "dez_mandamentos", "Os Dez Mandamentos", "moral_crista",
        ("dez mandamentos", "decalogo", "mandamentos da lei de deus"),
        (
            "1º — Amar a Deus sobre todas as coisas", "2º — Não tomar seu santo nome em vão",
            "3º — Guardar domingos e festas", "4º — Honrar pai e mãe", "5º — Não matar",
            "6º — Não pecar contra a castidade", "7º — Não furtar",
            "8º — Não levantar falso testemunho", "9º — Não desejar a mulher do próximo",
            "10º — Não cobiçar as coisas alheias",
        ),
        ("formulação", "significado", "fundamento bíblico", "bem protegido", "deveres e proibições", "virtudes", "aplicações contemporâneas", "síntese pastoral"),
        ("Sagrada Escritura", "Catecismo", "Magistério moral"),
        ("Bem-aventuranças", "Virtudes cardeais", "Virtudes teologais", "Formação da consciência"),
    ),
    TopicSpec(
        "dogmas_marianos", "Dogmas marianos", "mariologia",
        ("dogmas marianos", "dogmas de maria", "dogmas sobre maria"),
        ("Maternidade divina", "Virgindade perpétua", "Imaculada Conceição", "Assunção"),
        ("definição dogmática", "fundamento bíblico e tradicional", "desenvolvimento histórico", "formulação magisterial", "significado cristológico e eclesial", "distinções necessárias"),
        ("Sagrada Escritura", "Concílios", "definições dogmáticas", "Catecismo", "documentos pontifícios"),
        ("Maria na Sagrada Escritura", "Maria na liturgia", "Adoração e veneração", "Aparições e revelações privadas"),
    ),
    TopicSpec(
        "biblia_catolica", "A Bíblia Católica e seus 73 livros", "sagrada_escritura",
        ("biblia catolica", "sagrada escritura", "73 livros", "livros da biblia", "cada livro da biblia"),
        OLD_TESTAMENT + NEW_TESTAMENT,
        ("posição no cânon", "grupo literário", "contexto e composição", "tema central", "estrutura", "importância teológica", "relação com Cristo e a história da salvação"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Tradição"),
        ("Formação do cânon", "Antigo e Novo Testamento", "Sentidos da Escritura", "Escritura, Tradição e Magistério"),
        long_form_group="Pentateuco",
    ),
    TopicSpec(
        "credo_apostolico", "Artigos do Credo Apostólico", "teologia_dogmatica",
        ("credo apostolico", "artigos do credo", "simbolo dos apostolos"),
        ("Creio em Deus Pai", "Creio em Jesus Cristo", "Concebido pelo Espírito Santo", "Paixão e sepultamento", "Descida à mansão dos mortos e Ressurreição", "Ascensão", "Juízo", "Espírito Santo", "Igreja e comunhão dos santos", "Remissão dos pecados", "Ressurreição da carne", "Vida eterna"),
        COMMON_DOCTRINAL_DIMENSIONS,
        ("Sagrada Escritura", "Símbolos da fé", "Catecismo", "Concílios"),
        ("Credo Niceno-Constantinopolitano", "Santíssima Trindade", "Mistério pascal"),
    ),
    TopicSpec(
        "dons_espirito_santo", "Sete dons do Espírito Santo", "pneumatologia",
        ("sete dons do espirito santo", "dons do espirito santo"),
        ("Sabedoria", "Entendimento", "Conselho", "Fortaleza", "Ciência", "Piedade", "Temor de Deus"),
        COMMON_DOCTRINAL_DIMENSIONS,
        ("Sagrada Escritura", "Catecismo", "Tradição"),
        ("Frutos do Espírito Santo", "Carismas", "Pentecostes"),
    ),
    TopicSpec(
        "frutos_espirito_santo", "Frutos do Espírito Santo", "pneumatologia",
        ("frutos do espirito santo",),
        ("Caridade", "Alegria", "Paz", "Paciência", "Longanimidade", "Bondade", "Benignidade", "Mansidão", "Fidelidade", "Modéstia", "Continência", "Castidade"),
        ("definição", "fundamento bíblico", "significado espiritual", "manifestação na vida cristã"),
        ("Sagrada Escritura", "Catecismo", "Tradição"),
        ("Dons do Espírito Santo", "Virtudes", "Discernimento espiritual"),
    ),
    TopicSpec(
        "bem_aventurancas", "As Bem-aventuranças", "moral_crista",
        ("bem aventurancas", "bem-aventurancas"),
        ("Pobres em espírito", "Aflitos", "Mansos", "Fome e sede de justiça", "Misericordiosos", "Puros de coração", "Promotores da paz", "Perseguidos por causa da justiça"),
        ("formulação bíblica", "significado", "promessa", "relação com Cristo", "vida moral"),
        ("Sagrada Escritura", "Catecismo", "Magistério"),
        ("Sermão da Montanha", "Virtudes", "Pai-Nosso"),
    ),
    TopicSpec(
        "pai_nosso", "Petições do Pai-Nosso", "oracao_espiritualidade",
        ("pai nosso", "peticoes do pai nosso", "oração do senhor"),
        ("Santificado seja o vosso nome", "Venha a nós o vosso Reino", "Seja feita a vossa vontade", "O pão nosso de cada dia", "Perdoai-nos as nossas ofensas", "Não nos deixeis cair em tentação", "Livrai-nos do mal"),
        ("texto bíblico", "significado teológico", "atitude espiritual", "aplicação à oração"),
        ("Sagrada Escritura", "Catecismo", "Tradição litúrgica"),
        ("Oração de Jesus", "Formas de oração", "Liturgia das Horas"),
    ),
    TopicSpec(
        "misterios_rosario", "Mistérios do Rosário", "mariologia",
        ("misterios do rosario", "santo rosario", "rosario"),
        ("Mistérios gozosos", "Mistérios luminosos", "Mistérios dolorosos", "Mistérios gloriosos"),
        ("acontecimentos contemplados", "fundamento bíblico", "relação com Cristo", "fruto espiritual"),
        ("Sagrada Escritura", "documentos pontifícios", "Tradição"),
        ("Ave-Maria", "Maria na Escritura", "Vida de Cristo"),
    ),
    TopicSpec(
        "notas_igreja", "As quatro notas da Igreja", "eclesiologia",
        ("quatro notas da igreja", "igreja una santa catolica apostolica"),
        ("Una", "Santa", "Católica", "Apostólica"),
        COMMON_DOCTRINAL_DIMENSIONS,
        ("Sagrada Escritura", "Credo", "Concílios", "Catecismo"),
        ("Natureza e missão da Igreja", "Sucessão apostólica", "Ecumenismo"),
    ),
    TopicSpec(
        "novissimos", "Novíssimos", "escatologia",
        ("novissimos", "ultimas coisas", "escatologia catolica"),
        ("Morte", "Juízo particular", "Céu", "Purgatório", "Inferno", "Ressurreição da carne", "Juízo final", "Vida eterna"),
        COMMON_DOCTRINAL_DIMENSIONS,
        ("Sagrada Escritura", "Catecismo", "Concílios"),
        ("Comunhão dos santos", "Esperança cristã", "Oração pelos mortos"),
    ),
    TopicSpec(
        "virtudes", "Virtudes cristãs", "moral_crista",
        ("virtudes cardeais e teologais", "virtudes cristas", "virtudes"),
        ("Prudência", "Justiça", "Fortaleza", "Temperança", "Fé", "Esperança", "Caridade"),
        ("definição", "fundamento", "atos próprios", "vícios opostos", "crescimento espiritual"),
        ("Sagrada Escritura", "Catecismo", "Tradição moral"),
        ("Dons do Espírito Santo", "Consciência moral", "Bem-aventuranças"),
    ),
)


CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("teologia_dogmatica", ("trindade", "credo", "dogma", "revelacao", "graca", "salvacao", "criacao")),
    ("cristologia", ("jesus", "cristo", "encarnacao", "ressurreicao", "paixao", "ascensao", "parabola", "milagre")),
    ("pneumatologia", ("espirito santo", "pentecostes", "carisma", "dons", "frutos")),
    ("eclesiologia", ("igreja", "papa", "bispo", "diacono", "magisterio", "concilio", "sinodo", "ecumenismo")),
    ("mariologia", ("maria", "nossa senhora", "rosario", "assuncao", "imaculada")),
    ("sacramentos_liturgia", ("sacramento", "missa", "liturgia", "eucaristia", "batismo", "matrimonio", "ano liturgico")),
    ("moral_crista", ("moral", "pecado", "mandamento", "virtude", "consciencia", "bioetica", "doutrina social")),
    ("oracao_espiritualidade", ("oracao", "espiritualidade", "lectio", "contemplacao", "discernimento")),
    ("sagrada_escritura", ("biblia", "escritura", "evangelho", "antigo testamento", "novo testamento", "canon")),
    ("historia_tradicao", ("historia da igreja", "padres da igreja", "reforma", "trento", "vaticano ii")),
    ("direito_canonico", ("direito canonico", "canon", "nulidade", "excomunhao", "curia", "diocese")),
    ("apologetica", ("apologetica", "protestante", "ateismo", "agnosticismo", "fe e ciencia", "por que os catolicos")),
)


def match_topic(text: str) -> TopicSpec | None:
    folded = fold_text(text)
    matches: list[tuple[int, TopicSpec]] = []
    for spec in TOPICS:
        for alias in spec.aliases:
            alias_folded = fold_text(alias)
            if re.search(rf"\b{re.escape(alias_folded)}\b", folded):
                matches.append((len(alias_folded), spec))
                break
    return max(matches, key=lambda item: item[0])[1] if matches else None


def classify_category(text: str, spec: TopicSpec | None = None) -> str:
    if spec:
        return spec.category
    folded = fold_text(text)
    for category, patterns in CATEGORY_PATTERNS:
        if any(pattern in folded for pattern in patterns):
            return category
    return "catequese_geral"


class CatholicTopicTaxonomy:
    version = TAXONOMY_VERSION

    @staticmethod
    def match(text: str) -> TopicSpec | None:
        return match_topic(text)

    @staticmethod
    def category(text: str, spec: TopicSpec | None = None) -> str:
        return classify_category(text, spec)
