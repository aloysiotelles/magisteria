from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


TAXONOMY_VERSION = "2026.07.2"


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
    closed_set: bool = True
    catalog_scope: str = ""


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

GOSPELS = ("Mateus", "Marcos", "Lucas", "João")
MAJOR_PROPHETS = ("Isaías", "Jeremias", "Lamentações", "Baruc", "Ezequiel", "Daniel")
MINOR_PROPHETS = (
    "Oseias", "Joel", "Amós", "Abdias", "Jonas", "Miqueias", "Naum", "Habacuc",
    "Sofonias", "Ageu", "Zacarias", "Malaquias",
)
PAULINE_LETTERS = (
    "Romanos", "1 Coríntios", "2 Coríntios", "Gálatas", "Efésios", "Filipenses",
    "Colossenses", "1 Tessalonicenses", "2 Tessalonicenses", "1 Timóteo", "2 Timóteo",
    "Tito", "Filêmon", "Hebreus (tradicionalmente agrupada com o corpus paulino)",
)
CATHOLIC_LETTERS = ("Tiago", "1 Pedro", "2 Pedro", "1 João", "2 João", "3 João", "Judas")
ECUMENICAL_COUNCILS = (
    "Niceia I (325)", "Constantinopla I (381)", "Éfeso (431)", "Calcedônia (451)",
    "Constantinopla II (553)", "Constantinopla III (680–681)", "Niceia II (787)",
    "Constantinopla IV (869–870)", "Latrão I (1123)", "Latrão II (1139)",
    "Latrão III (1179)", "Latrão IV (1215)", "Lyon I (1245)", "Lyon II (1274)",
    "Vienne (1311–1312)", "Constança (1414–1418)", "Florença (1431–1445)",
    "Latrão V (1512–1517)", "Trento (1545–1563)", "Vaticano I (1869–1870)",
    "Vaticano II (1962–1965)",
)
VATICAN_II_DOCUMENTS = (
    "Dei Verbum", "Lumen Gentium", "Sacrosanctum Concilium", "Gaudium et Spes",
    "Ad Gentes", "Apostolicam Actuositatem", "Christus Dominus", "Inter Mirifica",
    "Optatam Totius", "Orientalium Ecclesiarum", "Perfectae Caritatis",
    "Presbyterorum Ordinis", "Unitatis Redintegratio", "Dignitatis Humanae",
    "Gravissimum Educationis", "Nostra Aetate",
)
DOCTORS_OF_THE_CHURCH = (
    "Santo Ambrósio", "São Jerônimo", "Santo Agostinho", "São Gregório Magno",
    "Santo Atanásio", "São Basílio Magno", "São Gregório Nazianzeno", "São João Crisóstomo",
    "Santo Hilário de Poitiers", "São Cirilo de Jerusalém", "São Cirilo de Alexandria",
    "São Leão Magno", "São Pedro Crisólogo", "Santo Isidoro de Sevilha", "São Beda, o Venerável",
    "São João Damasceno", "São Pedro Damião", "Santo Anselmo", "São Bernardo de Claraval",
    "Santo Antônio de Pádua", "Santo Alberto Magno", "São Boaventura", "São Tomás de Aquino",
    "Santa Catarina de Sena", "Santa Teresa de Jesus", "São João da Cruz", "São Pedro Canísio",
    "São Roberto Belarmino", "São Lourenço de Brindisi", "São Francisco de Sales",
    "Santo Afonso Maria de Ligório", "Santa Teresinha do Menino Jesus", "Santo Efrém, o Sírio",
    "São João de Ávila", "Santa Hildegarda de Bingen", "São Gregório de Narek", "Santo Irineu de Lião",
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
        ("sete sacramentos", "sacramentos da igreja", "sacramentos catolicos", "cada sacramento", "sacramentos"),
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
        "mandamentos_igreja", "Os Cinco Mandamentos da Igreja", "moral_crista",
        ("cinco mandamentos da igreja", "mandamentos da igreja", "preceitos da igreja"),
        (
            "Participar da Missa inteira nos domingos e festas de guarda",
            "Confessar-se ao menos uma vez por ano",
            "Comungar ao menos pela Páscoa da Ressurreição",
            "Jejuar e abster-se de carne conforme manda a Santa Mãe Igreja",
            "Ajudar a Igreja em suas necessidades",
        ),
        ("formulação", "fundamento", "obrigação mínima", "sentido espiritual", "aplicação"),
        ("Catecismo", "Direito Canônico", "Magistério"),
        ("Domingo", "Penitência", "Eucaristia", "Sustento da missão da Igreja"),
    ),
    TopicSpec(
        "virtudes_teologais", "As Virtudes Teologais", "moral_crista",
        ("virtudes teologais", "tres virtudes teologais"),
        ("Fé", "Esperança", "Caridade"),
        ("definição", "fundamento bíblico", "objeto", "atos", "pecados opostos", "vida cristã"),
        ("Sagrada Escritura", "Catecismo", "Tradição moral"),
        ("Virtudes cardeais", "Dons do Espírito Santo", "Vida teologal"),
    ),
    TopicSpec(
        "virtudes_cardeais", "As Virtudes Cardeais", "moral_crista",
        ("virtudes cardeais", "quatro virtudes cardeais"),
        ("Prudência", "Justiça", "Fortaleza", "Temperança"),
        ("definição", "fundamento", "atos próprios", "vícios opostos", "formação do caráter"),
        ("Sagrada Escritura", "Catecismo", "Tradição moral"),
        ("Virtudes teologais", "Dons do Espírito Santo", "Consciência moral"),
    ),
    TopicSpec(
        "pecados_capitais", "Os Sete Pecados Capitais", "moral_crista",
        ("pecados capitais", "sete pecados capitais", "vicios capitais"),
        ("Soberba", "Avareza", "Inveja", "Ira", "Luxúria", "Gula", "Preguiça ou acídia"),
        ("definição", "dinâmica espiritual", "efeitos", "virtude oposta", "meios de combate"),
        ("Sagrada Escritura", "Catecismo", "Tradição moral"),
        ("Virtudes", "Conversão", "Exame de consciência"),
    ),
    TopicSpec(
        "obras_misericordia_corporais", "As Obras de Misericórdia Corporais", "moral_crista",
        ("obras de misericordia corporais", "sete obras corporais"),
        ("Dar de comer a quem tem fome", "Dar de beber a quem tem sede", "Vestir os nus", "Dar pousada aos peregrinos", "Assistir os enfermos", "Visitar os presos", "Enterrar os mortos"),
        ("formulação", "fundamento bíblico", "necessidade humana atendida", "exemplos atuais"),
        ("Sagrada Escritura", "Catecismo", "Tradição"),
        ("Obras de misericórdia espirituais", "Juízo final", "Caridade"),
    ),
    TopicSpec(
        "obras_misericordia_espirituais", "As Obras de Misericórdia Espirituais", "moral_crista",
        ("obras de misericordia espirituais", "sete obras espirituais"),
        ("Dar bom conselho", "Ensinar os ignorantes", "Corrigir os que erram", "Consolar os aflitos", "Perdoar as injúrias", "Sofrer com paciência as fraquezas do próximo", "Rogar a Deus pelos vivos e pelos mortos"),
        ("formulação", "fundamento bíblico", "necessidade espiritual atendida", "prudência pastoral", "exemplos atuais"),
        ("Sagrada Escritura", "Catecismo", "Tradição"),
        ("Obras de misericórdia corporais", "Correção fraterna", "Caridade"),
    ),
    TopicSpec(
        "obras_misericordia", "As Catorze Obras de Misericórdia", "moral_crista",
        ("obras de misericordia", "catorze obras de misericordia"),
        (
            "Dar de comer a quem tem fome", "Dar de beber a quem tem sede", "Vestir os nus",
            "Dar pousada aos peregrinos", "Assistir os enfermos", "Visitar os presos", "Enterrar os mortos",
            "Dar bom conselho", "Ensinar os ignorantes", "Corrigir os que erram", "Consolar os aflitos",
            "Perdoar as injúrias", "Sofrer com paciência as fraquezas do próximo",
            "Rogar a Deus pelos vivos e pelos mortos",
        ),
        ("formulação", "fundamento bíblico", "necessidade atendida", "prudência pastoral", "exemplos atuais"),
        ("Sagrada Escritura", "Catecismo", "Tradição"),
        ("Juízo final", "Caridade", "Doutrina Social da Igreja"),
    ),
    TopicSpec(
        "antigo_testamento", "Os 46 livros do Antigo Testamento", "sagrada_escritura",
        ("livros do antigo testamento", "antigo testamento", "46 livros"),
        OLD_TESTAMENT,
        ("grupo no cânon", "contexto", "conteúdo", "tema teológico", "relação com a história da salvação"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Tradição"),
        ("Pentateuco", "Livros históricos", "Sapienciais", "Profetas"),
    ),
    TopicSpec(
        "novo_testamento", "Os 27 livros do Novo Testamento", "sagrada_escritura",
        ("livros do novo testamento", "novo testamento", "27 livros"),
        NEW_TESTAMENT,
        ("grupo no cânon", "contexto", "conteúdo", "tema cristológico", "vida da Igreja"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Tradição"),
        ("Evangelhos", "Atos", "Cartas apostólicas", "Apocalipse"),
    ),
    TopicSpec(
        "evangelhos", "Os Quatro Evangelhos", "sagrada_escritura",
        ("quatro evangelhos", "os evangelhos", "evangelistas"),
        GOSPELS,
        ("autor e comunidade", "destinatários", "estrutura", "traços próprios", "cristologia", "símbolo tradicional"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Tradição"),
        ("Evangelhos sinóticos", "Cânon", "Vida de Cristo"),
    ),
    TopicSpec(
        "profetas_maiores", "Os Profetas Maiores", "sagrada_escritura",
        ("profetas maiores",), MAJOR_PROPHETS,
        ("contexto", "estrutura do livro", "mensagem", "profecias messiânicas", "recepção cristã"),
        ("Sagrada Escritura", "Catecismo", "Tradição"), ("Profetas menores", "Profecia", "Messias"),
    ),
    TopicSpec(
        "profetas_menores", "Os Doze Profetas Menores", "sagrada_escritura",
        ("profetas menores", "doze profetas"), MINOR_PROPHETS,
        ("contexto", "mensagem", "estrutura", "chamado à conversão", "esperança messiânica"),
        ("Sagrada Escritura", "Catecismo", "Tradição"), ("Profetas maiores", "Profecia", "Aliança"),
    ),
    TopicSpec(
        "cartas_paulinas", "As Cartas Paulinas", "sagrada_escritura",
        ("cartas paulinas", "epistolas paulinas", "cartas de sao paulo"), PAULINE_LETTERS,
        ("destinatários", "contexto", "tema central", "estrutura", "questões pastorais", "cristologia"),
        ("Sagrada Escritura", "Catecismo", "Tradição"), ("São Paulo", "Atos dos Apóstolos", "Cartas católicas"),
    ),
    TopicSpec(
        "cartas_catolicas", "As Cartas Católicas", "sagrada_escritura",
        ("cartas catolicas", "epistolas catolicas", "cartas gerais"), CATHOLIC_LETTERS,
        ("autor atribuído", "destinatários", "contexto", "tema central", "vida eclesial"),
        ("Sagrada Escritura", "Catecismo", "Tradição"), ("Cartas paulinas", "Cânon", "Igreja apostólica"),
    ),
    TopicSpec(
        "concilios_ecumenicos", "Os 21 Concílios Ecumênicos", "historia_tradicao",
        ("concilios ecumenicos", "21 concilios", "vinte e um concilios"), ECUMENICAL_COUNCILS,
        ("data e lugar", "contexto", "questão central", "definições e decisões", "recepção histórica"),
        ("Documentos conciliares", "Catecismo", "Magistério", "História da Igreja"),
        ("Concílios antigos", "Concílio de Trento", "Vaticano I", "Vaticano II"),
    ),
    TopicSpec(
        "doutores_igreja", "Os Doutores da Igreja", "historia_tradicao",
        ("doutores da igreja", "doutores e doutoras da igreja"), DOCTORS_OF_THE_CHURCH,
        ("época", "obra", "contribuição doutrinal", "espiritualidade", "proclamação como Doutor"),
        ("Magistério", "Obras patrísticas", "Tradição", "Documentos pontifícios"),
        ("Padres da Igreja", "Teologia patrística", "História da doutrina"),
    ),
    TopicSpec(
        "conselhos_evangelicos", "Os Conselhos Evangélicos", "oracao_espiritualidade",
        ("conselhos evangelicos", "tres conselhos evangelicos"),
        ("Castidade consagrada", "Pobreza evangélica", "Obediência"),
        ("fundamento evangélico", "sentido cristológico", "voto", "vida consagrada", "testemunho"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Direito Canônico"),
        ("Vida consagrada", "Estados de vida", "Seguimento de Cristo"),
    ),
    TopicSpec(
        "estados_vida", "Os Estados de Vida na Igreja", "eclesiologia",
        ("estados de vida", "estados de vida na igreja"),
        ("Ministério ordenado", "Vida consagrada", "Fiéis leigos"),
        ("vocação", "missão", "forma de vida", "relação com os demais estados", "santidade"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Direito Canônico"),
        ("Vocação universal à santidade", "Conselhos evangélicos", "Ministérios ordenados"),
    ),
    TopicSpec(
        "partes_missa", "As Partes da Missa", "sacramentos_liturgia",
        ("partes da missa", "estrutura da missa", "ritos da missa"),
        ("Ritos iniciais", "Liturgia da Palavra", "Liturgia Eucarística", "Ritos finais"),
        ("elementos", "finalidade", "gestos", "participação dos fiéis", "unidade da celebração"),
        ("Missal Romano", "Instrução Geral do Missal Romano", "Catecismo", "Concílio Vaticano II"),
        ("Eucaristia", "Orações Eucarísticas", "Ano litúrgico"),
    ),
    TopicSpec(
        "tempos_liturgicos", "Os Tempos Litúrgicos", "sacramentos_liturgia",
        ("tempos liturgicos", "ano liturgico"),
        ("Advento", "Tempo do Natal", "Tempo Comum", "Quaresma", "Tríduo Pascal", "Tempo Pascal"),
        ("duração", "mistério celebrado", "espiritualidade", "leituras", "cor litúrgica"),
        ("Missal Romano", "Calendário Romano", "Catecismo", "Concílio Vaticano II"),
        ("Cores litúrgicas", "Solenidades", "Liturgia das Horas"),
    ),
    TopicSpec(
        "cores_liturgicas", "As Cores Litúrgicas", "sacramentos_liturgia",
        ("cores liturgicas",),
        ("Branco", "Vermelho", "Verde", "Roxo ou violeta", "Rosa", "Preto"),
        ("simbolismo", "tempos e celebrações", "faculdade de uso", "variações legítimas"),
        ("Instrução Geral do Missal Romano", "Missal Romano", "Normas litúrgicas"),
        ("Tempos litúrgicos", "Paramentos", "Celebração da Missa"),
    ),
    TopicSpec(
        "ministerios_ordenados", "Os Graus do Sacramento da Ordem", "sacramentos_liturgia",
        ("ministerios ordenados", "graus da ordem", "sacramento da ordem"),
        ("Episcopado", "Presbiterado", "Diaconado"),
        ("graça sacramental", "função", "ministério", "ordenação", "relação entre os graus"),
        ("Sagrada Escritura", "Catecismo", "Concílio Vaticano II", "Direito Canônico"),
        ("Sucessão apostólica", "Bispos", "Presbíteros", "Diáconos"),
    ),
    TopicSpec(
        "indulgencias", "As Indulgências", "moral_crista",
        ("tipos de indulgencia", "indulgencias", "indulgencia"),
        ("Indulgência parcial", "Indulgência plenária"),
        ("definição", "pena temporal", "condições", "aplicação aos defuntos", "abusos a evitar"),
        ("Catecismo", "Código de Direito Canônico", "Penitenciaria Apostólica", "Magistério"),
        ("Purgatório", "Sacramento da Penitência", "Comunhão dos santos"),
    ),
    TopicSpec(
        "formas_oracao", "As Formas de Oração Cristã", "oracao_espiritualidade",
        ("especies de oracao", "formas de oracao", "tipos de oracao"),
        ("Bênção e adoração", "Petição", "Intercessão", "Ação de graças", "Louvor"),
        ("definição", "fundamento bíblico", "atitude espiritual", "exemplos", "vida litúrgica"),
        ("Sagrada Escritura", "Catecismo", "Liturgia", "Tradição espiritual"),
        ("Pai-Nosso", "Liturgia das Horas", "Oração mental e vocal"),
    ),
    TopicSpec(
        "documentos_vaticano_ii", "Os 16 Documentos do Concílio Vaticano II", "historia_tradicao",
        ("documentos do vaticano ii", "documentos conciliares do vaticano ii", "16 documentos do vaticano ii"),
        VATICAN_II_DOCUMENTS,
        ("tipo documental", "tema", "estrutura", "ensinamento central", "recepção e aplicação"),
        ("Documentos conciliares", "Magistério", "Catecismo"),
        ("Constituições", "Decretos", "Declarações", "Recepção do Vaticano II"),
    ),
    TopicSpec(
        "catalogos_documentais", "Catálogos históricos e documentais da Igreja", "historia_tradicao",
        (
            "padres apostolicos", "padres da igreja", "simbolos de fe", "oracoes eucaristicas",
            "sacramentais", "ritos sacramentais", "tipos de pecado", "generos literarios biblicos",
            "enciclicas", "exortacoes apostolicas", "constituicoes apostolicas", "documentos da cnbb",
            "etapas da historia da igreja", "concilios regionais", "patriarcados", "ordens religiosas",
            "escolas teologicas", "heresias antigas", "heresias modernas", "perseguicoes aos cristaos",
            "ordens monasticas", "devocoes marianas", "aparicoes reconhecidas", "papas",
            "sumos pontifices", "ministerios liturgicos", "ministerios instituidos",
        ),
        (),
        ("definição do escopo", "critério de inclusão", "ordem histórica ou temática", "itens documentados", "limites do catálogo"),
        ("Sagrada Escritura", "Catecismo", "Magistério", "documentos históricos e disciplinares do acervo"),
        ("História da Igreja", "Magistério", "Tradição", "Disciplina e devoção"),
        closed_set=False,
        catalog_scope=(
            "Este tema não possui uma enumeração universal, imutável e única. A resposta deve declarar o critério "
            "de inclusão e cobrir integralmente os itens identificados nos documentos recuperados, sem transformar "
            "um catálogo histórico ou disciplinar em lista dogmática fechada."
        ),
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
