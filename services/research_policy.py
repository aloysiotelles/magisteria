from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from services.catholic_taxonomy import fold_text


POLICY_VERSION = "2026.08.1"


@dataclass(frozen=True)
class DoctrineProfile:
    key: str
    title: str
    family: str
    aliases: tuple[str, ...]
    catechism_ranges: tuple[str, ...]
    aspects: tuple[str, ...]


@dataclass(frozen=True)
class SourceLane:
    key: str
    label: str
    query: str
    source_hints: tuple[str, ...]
    limit: int = 3
    required_when_available: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ResearchDirective:
    policy_version: str
    profile_key: str
    profile_title: str
    catechism_ranges: tuple[str, ...]
    coverage_items: tuple[str, ...]
    full_coverage_required: bool
    source_lanes: tuple[SourceLane, ...]
    source_integration: tuple[str, ...]
    final_checks: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["source_lanes"] = [lane.to_dict() for lane in self.source_lanes]
        return data

    def instruction(self) -> str:
        profile = ""
        if self.profile_title:
            ranges = ", ".join(self.catechism_ranges) or "as seções pertinentes"
            items = "; ".join(self.coverage_items) or "os elementos expressamente pedidos"
            scope = (
                "Todos estes itens são obrigatórios nesta resposta, com conteúdo próprio e equilibrado."
                if self.full_coverage_required
                else "Use estes itens conforme a pertinência da pergunta, sem substituir conteúdo específico por generalidades."
            )
            profile = (
                f"Perfil doutrinal identificado: {self.profile_title}. Pesquise e utilize o Catecismo em {ranges}. "
                f"Lista de cobertura: {items}. {scope} "
            )
        return (
            "DIRETRIZ GERAL DE PESQUISA E RESPOSTA: analise silenciosamente o tema, todos os itens e subitens, "
            "a profundidade, o público, as distinções necessárias e as fontes mais pertinentes. A primeira busca não "
            "é automaticamente suficiente: use as passagens recuperadas pelas buscas exata, equivalente, conceitual, "
            "estrutural e complementar; confira a cobertura antes de redigir. Responda com fidelidade católica, clareza "
            "catequética, profundidade proporcional e linguagem natural. Integre as fontes em uma única exposição: o "
            "Catecismo e o Magistério fornecem a síntese doutrinal segura; A Fé Explicada contribui com a apresentação "
            "catequética e prática; a Suma Teológica aprofunda princípios, causas e distinções. Nunca atribua a uma fonte "
            "o texto ou o grau de autoridade de outra. Quando pertinente, contemple definição, fundamento, bem protegido "
            "ou verdade ensinada, conteúdo positivo, condutas contrárias, distinções, aplicação concreta e síntese "
            "cristocêntrica. Seja completo sem reproduzir longos trechos, sem repetições e sem preenchimento genérico. "
            "Use referências inteligíveis, com nome da obra e localização confirmada pelos trechos; nunca invente número, "
            "autor, artigo, cânon ou citação. Não exponha chunks, busca vetorial, recuperação, falhas internas ou outras "
            "etapas técnicas. Antes de concluir, confira silenciosamente pedido, subitens, cobertura, fidelidade, "
            "distinções, referências, linguagem e ausência de repetições. "
            f"{profile}"
        )


COMMANDMENTS: dict[int, DoctrineProfile] = {
    1: DoctrineProfile("mandamento_1", "Primeiro mandamento", "mandamento", ("primeiro mandamento", "adorar a deus"), ("CIC 2083–2141",), ("fé, esperança e caridade", "adoração, oração e sacrifício", "promessas e votos", "dever social da religião", "superstição e idolatria", "adivinhação e magia", "irreligião, tentação de Deus, sacrilégio e simonia", "ateísmo e agnosticismo", "veneração das imagens sagradas")),
    2: DoctrineProfile("mandamento_2", "Segundo mandamento", "mandamento", ("segundo mandamento", "nome de deus em vao"), ("CIC 2142–2167",), ("santidade e respeito ao nome de Deus", "blasfêmia e uso indevido do nome divino", "juramentos e perjúrio", "nome cristão recebido no Batismo")),
    3: DoctrineProfile("mandamento_3", "Terceiro mandamento", "mandamento", ("terceiro mandamento", "guardar domingos", "santificar domingos"), ("CIC 2168–2195",), ("sábado na Antiga Aliança", "domingo e Ressurreição de Cristo", "Eucaristia e obrigação dominical", "descanso dominical", "obras de misericórdia e vida familiar, cultural, social e religiosa", "impedimentos sérios", "deveres das autoridades e empregadores")),
    4: DoctrineProfile("mandamento_4", "Quarto mandamento", "mandamento", ("quarto mandamento", "honrar pai e mae"), ("CIC 2196–2257",), ("família no plano de Deus", "deveres dos filhos", "deveres dos pais e educação da fé", "família e sociedade", "autoridade civil e deveres dos cidadãos", "limites da obediência", "resistência a ordens contrárias à lei moral", "relações de autoridade em outros âmbitos")),
    5: DoctrineProfile("mandamento_5", "Quinto mandamento", "mandamento", ("quinto mandamento", "nao matar"), ("CIC 2258–2330",), ("dignidade e sacralidade da vida", "legítima defesa", "homicídio voluntário", "aborto", "eutanásia", "suicídio", "integridade corporal, saúde e experimentação científica", "escândalo", "respeito aos mortos", "paz, cólera e ódio", "guerra, corrida armamentista e defesa dos inocentes")),
    6: DoctrineProfile("mandamento_6", "Sexto mandamento", "mandamento", ("sexto mandamento", "nao cometer adulterio"), ("CIC 2331–2400",), ("criação do homem e da mulher", "vocação e integração da castidade", "castidade segundo o estado de vida e amizade", "matrimônio, fidelidade, fecundidade e seus bens", "regulação da natalidade", "luxúria, masturbação, fornicação, pornografia, prostituição e estupro", "atos homossexuais e acolhimento respeitoso das pessoas", "adultério, divórcio, união livre e outras ofensas à dignidade matrimonial")),
    7: DoctrineProfile("mandamento_7", "Sétimo mandamento", "mandamento", ("setimo mandamento", "nao furtar"), ("CIC 2401–2463",), ("destino universal dos bens e propriedade privada", "furto, fraude e restituição", "contratos, promessas, jogos e apostas", "respeito pela criação e pelos animais", "doutrina social da Igreja", "atividade econômica, trabalho e salário justo", "greve e responsabilidades do Estado e da empresa", "justiça internacional", "amor preferencial pelos pobres e obras de misericórdia")),
    8: DoctrineProfile("mandamento_8", "Oitavo mandamento", "mandamento", ("oitavo mandamento", "falso testemunho"), ("CIC 2464–2513",), ("viver na verdade, testemunho e martírio", "falso testemunho e perjúrio", "juízo temerário, maledicência e calúnia", "mentira, sua gravidade e reparação", "reputação, discrição, segredo e sigilo profissional", "meios de comunicação e informação", "verdade, beleza e arte sacra")),
    9: DoctrineProfile("mandamento_9", "Nono mandamento", "mandamento", ("nono mandamento", "nao desejar a mulher"), ("CIC 2514–2533",), ("purificação do coração e concupiscência", "combate espiritual", "pudor", "pureza do olhar e da intenção", "disciplina dos sentimentos e da imaginação", "graça, oração e visão de Deus")),
    10: DoctrineProfile("mandamento_10", "Décimo mandamento", "mandamento", ("decimo mandamento", "nao cobicar"), ("CIC 2534–2557",), ("desordem dos desejos", "cobiça e avareza", "inveja", "desejo desordenado de riqueza", "pobreza de coração e abandono à Providência", "desejo da verdadeira felicidade", "ordenação dos bens terrenos ao Reino de Deus")),
}


SACRAMENTS: tuple[DoctrineProfile, ...] = (
    DoctrineProfile("batismo", "Batismo", "sacramento", ("batismo", "baptismo"), ("CIC 1213–1284",), ("nomes e prefigurações bíblicas", "Batismo de Cristo", "celebração, matéria, forma e ministros", "destinatários e necessidade", "Batismo de sangue e de desejo", "crianças não batizadas", "perdão dos pecados e nova criação", "incorporação à Igreja", "caráter sacramental")),
    DoctrineProfile("confirmacao", "Confirmação ou Crisma", "sacramento", ("confirmacao", "crisma"), ("CIC 1285–1321",), ("Pentecostes", "sinais, rito e unção", "ministro, destinatários e preparação", "fortalecimento da graça batismal", "vínculo com a Igreja e testemunho cristão", "caráter sacramental")),
    DoctrineProfile("eucaristia", "Eucaristia", "sacramento", ("eucaristia", "sagrada comunhao", "santissimo sacramento"), ("CIC 1322–1419",), ("fonte e ápice da vida cristã", "nomes e instituição", "memorial e sacrifício", "presença real e transubstanciação", "celebração e ministros", "participação e disposições para comungar", "frutos da Comunhão e unidade da Igreja", "penhor da glória futura", "adoração eucarística")),
    DoctrineProfile("penitencia", "Penitência e Reconciliação", "sacramento", ("penitencia", "reconciliacao", "confissao"), ("CIC 1422–1498",), ("conversão dos batizados e nomes do sacramento", "contrição, confissão e satisfação", "absolvição e ministro", "sigilo sacramental", "efeitos e indulgências", "celebração", "pecados graves e veniais", "frequência da confissão")),
    DoctrineProfile("uncao_enfermos", "Unção dos Enfermos", "sacramento", ("uncao dos enfermos",), ("CIC 1499–1532",), ("fundamento bíblico", "destinatários, momento e repetição", "ministro e celebração", "união com a Paixão de Cristo", "força, paz e coragem", "perdão dos pecados", "preparação para a vida eterna e viático")),
    DoctrineProfile("ordem", "Ordem", "sacramento", ("sacramento da ordem", "ordem sacerdotal"), ("CIC 1536–1600",), ("sacerdócio da Antiga Aliança e de Cristo", "sacerdócio comum e ministerial", "episcopado, presbiterado e diaconato", "celebração, ministro e destinatários", "caráter e efeitos", "serviço à Igreja")),
    DoctrineProfile("matrimonio", "Matrimônio", "sacramento", ("matrimonio", "sacramento do matrimonio"), ("CIC 1601–1666",), ("matrimônio na criação, sob o pecado e na Antiga Aliança", "Cristo e a sacramentalidade", "consentimento, ministros e celebração", "unidade, indissolubilidade e fidelidade", "fecundidade e abertura à vida", "Igreja doméstica", "casamentos mistos e disparidade de culto", "separação, nulidade e situações irregulares")),
)


CREDO_ARTICLES: dict[int, DoctrineProfile] = {
    1: DoctrineProfile("credo_1", "Primeiro artigo do Credo", "credo", ("primeiro artigo do credo",), ("CIC 198–421",), ("Deus uno, seu nome, verdade e amor", "Santíssima Trindade e onipotência", "criação, anjos e mundo visível", "ser humano", "queda e pecado original", "promessa da salvação")),
    2: DoctrineProfile("credo_2", "Segundo artigo do Credo", "credo", ("segundo artigo do credo",), ("CIC 422–455",), ("anúncio de Jesus Cristo", "nome de Jesus", "título Cristo", "Filho único de Deus", "Senhor")),
    3: DoctrineProfile("credo_3", "Terceiro artigo do Credo", "credo", ("terceiro artigo do credo",), ("CIC 456–570",), ("Encarnação e verdadeiro Deus e homem", "humanidade e divindade de Cristo", "maternidade divina, Imaculada Conceição e virgindade de Maria", "mistérios da infância, vida oculta e pública", "Batismo, tentações e Reino", "milagres, Transfiguração e subida a Jerusalém")),
    4: DoctrineProfile("credo_4", "Quarto artigo do Credo", "credo", ("quarto artigo do credo",), ("CIC 571–630",), ("mistério pascal e processo de Jesus", "responsabilidade pela morte", "sacrifício redentor e obediência de Cristo", "cruz, morte e sepultura")),
    5: DoctrineProfile("credo_5", "Quinto artigo do Credo", "credo", ("quinto artigo do credo",), ("CIC 631–658",), ("descida à mansão dos mortos e libertação dos justos", "realidade e corpo da Ressurreição", "ação da Trindade", "significado salvifico")),
    6: DoctrineProfile("credo_6", "Sexto artigo do Credo", "credo", ("sexto artigo do credo",), ("CIC 659–667",), ("Ascensão e glorificação", "entrada no santuário celeste", "intercessão", "reinado de Cristo")),
    7: DoctrineProfile("credo_7", "Sétimo artigo do Credo", "credo", ("setimo artigo do credo",), ("CIC 668–682",), ("reinado de Cristo", "Igreja e Reino", "última provação", "vinda gloriosa", "juízo final")),
    8: DoctrineProfile("credo_8", "Oitavo artigo do Credo", "credo", ("oitavo artigo do credo",), ("CIC 683–747",), ("missão conjunta do Filho e do Espírito", "nomes e símbolos do Espírito Santo", "Espírito na criação e Antiga Aliança", "profetas e Cristo", "Pentecostes e Igreja")),
    9: DoctrineProfile("credo_9", "Nono artigo do Credo", "credo", ("nono artigo do credo",), ("CIC 748–975",), ("nomes, imagens, origem e missão da Igreja", "Povo de Deus, Corpo de Cristo e Templo do Espírito", "Igreja una, santa, católica e apostólica", "hierarquia, leigos e vida consagrada", "comunhão dos santos", "Maria, Mãe de Cristo e da Igreja")),
    10: DoctrineProfile("credo_10", "Décimo artigo do Credo", "credo", ("decimo artigo do credo",), ("CIC 976–987",), ("Batismo para o perdão", "poder das chaves", "reconciliação após o Batismo", "missão da Igreja de perdoar os pecados")),
    11: DoctrineProfile("credo_11", "Décimo primeiro artigo do Credo", "credo", ("decimo primeiro artigo do credo",), ("CIC 988–1019",), ("Ressurreição de Cristo e dos fiéis", "significado da carne", "modo da ressurreição", "morrer em Cristo", "sentido cristão da morte")),
    12: DoctrineProfile("credo_12", "Décimo segundo artigo do Credo", "credo", ("decimo segundo artigo do credo",), ("CIC 1020–1065",), ("juízo particular", "céu", "purgatório", "inferno", "juízo final", "novos céus e nova terra", "Amém")),
}


PAI_NOSSO_SECTIONS: tuple[DoctrineProfile, ...] = (
    DoctrineProfile("pai_nosso_intro", "Introdução à Oração do Senhor", "pai_nosso", ("introducao ao pai nosso",), ("CIC 2759–2776",), ("Jesus ensina a rezar", "oração fundamental e resumo do Evangelho", "oração do Senhor e da Igreja", "lugar na liturgia")),
    DoctrineProfile("pai_nosso_pai", "Pai nosso que estais nos céus", "pai_nosso", ("pai nosso que estais nos ceus",), ("CIC 2777–2802",), ("confiança filial", "paternidade de Deus", "filiação em Cristo", "dimensão comunitária", "sentido de nos céus")),
    DoctrineProfile("pai_nosso_1", "Santificado seja o vosso nome", "pai_nosso", ("santificado seja",), ("CIC 2807–2815",), ()),
    DoctrineProfile("pai_nosso_2", "Venha a nós o vosso Reino", "pai_nosso", ("venha a nos",), ("CIC 2816–2821",), ()),
    DoctrineProfile("pai_nosso_3", "Seja feita a vossa vontade", "pai_nosso", ("seja feita a vossa vontade",), ("CIC 2822–2827",), ()),
    DoctrineProfile("pai_nosso_4", "O pão nosso de cada dia", "pai_nosso", ("pao nosso",), ("CIC 2828–2837",), ("Providência", "pão material e solidariedade", "fome no mundo", "Palavra de Deus", "Eucaristia")),
    DoctrineProfile("pai_nosso_5", "Perdoai-nos as nossas ofensas", "pai_nosso", ("perdoai-nos", "perdoai nos"), ("CIC 2838–2845",), ("misericórdia e reconhecimento do pecado", "perdão recebido", "necessidade de perdoar", "ação do Espírito no coração")),
    DoctrineProfile("pai_nosso_6", "Não nos deixeis cair em tentação", "pai_nosso", ("nao nos deixeis",), ("CIC 2846–2849",), ("provação e consentimento", "discernimento e vigilância", "perseverança e combate espiritual")),
    DoctrineProfile("pai_nosso_7", "Livrai-nos do mal", "pai_nosso", ("livrai-nos", "livrai nos"), ("CIC 2850–2854",), ("o Maligno e vitória de Cristo", "libertação do pecado", "oração pela humanidade", "esperança escatológica")),
    DoctrineProfile("pai_nosso_doxologia", "Doxologia e conclusão", "pai_nosso", ("vosso e o reino", "doxologia"), ("CIC 2855–2865",), ("Reino, poder e glória", "Amém", "síntese da Oração do Senhor")),
)


ORDINALS = {
    "primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5, "sexto": 6,
    "setimo": 7, "oitavo": 8, "nono": 9, "decimo": 10,
}


FULL_COVERAGE_PATTERN = re.compile(
    r"\b(?:todos?|todas?|cada\s+um|cada\s+uma|do\s+primeiro\s+ao\s+ultimo|do\s+primeiro\s+a\s+ultimo|"
    r"detalh|complet|integral|parte\s+por\s+parte|um\s+por\s+um|artigo\s+por\s+artigo|aprofund)\w*\b",
    re.IGNORECASE,
)


def full_coverage_requested(question: str) -> bool:
    return bool(FULL_COVERAGE_PATTERN.search(fold_text(question)))


def match_doctrine_profile(question: str) -> DoctrineProfile | None:
    folded = fold_text(question)
    commandment = re.search(
        r"\b(primeiro|segundo|terceiro|quarto|quinto|sexto|setimo|oitavo|nono|decimo|10|[1-9])(?:o)?\s+mandamento\b",
        folded,
    )
    if commandment:
        number = int(commandment.group(1)) if commandment.group(1).isdigit() else ORDINALS[commandment.group(1)]
        return COMMANDMENTS.get(number)
    article = re.search(
        r"\b(primeiro|segundo|terceiro|quarto|quinto|sexto|setimo|oitavo|nono|decimo)(?:\s+(primeiro|segundo))?\s+artigo\s+do\s+credo\b",
        folded,
    )
    if article:
        base = ORDINALS[article.group(1)]
        number = 10 + ORDINALS[article.group(2)] if article.group(2) else base
        return CREDO_ARTICLES.get(number)
    for profile in (*SACRAMENTS, *COMMANDMENTS.values()):
        if any(re.search(rf"\b{re.escape(alias)}\b", folded) for alias in profile.aliases):
            return profile
    return None


def policy_response_components(question: str) -> tuple[str, ...]:
    profile = match_doctrine_profile(question)
    if profile and full_coverage_requested(question):
        return profile.aspects
    return ()


def _profile_lane(profile: DoctrineProfile, depth: str = "explicativo") -> SourceLane:
    aspects = ", ".join(profile.aspects)
    ranges = ", ".join(profile.catechism_ranges)
    return SourceLane(
        key=f"catechism_{profile.key}",
        label=f"Catecismo — {profile.title}",
        query=f"{profile.title}. Catecismo da Igreja Católica, {ranges}. {aspects}",
        source_hints=("catecismo",),
        limit=5 if depth == "aprofundado" else 3,
    )


def _group_profiles(topic_key: str) -> tuple[DoctrineProfile, ...]:
    if topic_key == "dez_mandamentos":
        return tuple(COMMANDMENTS.values())
    if topic_key == "sacramentos":
        return SACRAMENTS
    if topic_key == "credo_apostolico":
        return tuple(CREDO_ARTICLES.values())
    if topic_key == "pai_nosso":
        return PAI_NOSSO_SECTIONS
    return ()


def build_research_directive(question: str, plan: Any) -> ResearchDirective:
    profile = match_doctrine_profile(question)
    group_profiles = _group_profiles(str(getattr(plan, "topic_key", "")))
    depth = str(getattr(plan, "depth", "explicativo"))
    lanes: list[SourceLane] = []
    ranges: list[str] = []
    coverage: list[str] = []

    if group_profiles:
        intro_ranges = {
            "dez_mandamentos": ("CIC 2052–2082",),
            "sacramentos": ("CIC 1113–1134", "CIC 1210–1211"),
            "credo_apostolico": ("CIC 185–197", "CIC 198–1065"),
            "pai_nosso": ("CIC 2759–2865", "CIC 2803–2806"),
        }.get(str(getattr(plan, "topic_key", "")), ())
        ranges.extend(intro_ranges)
        for item in group_profiles:
            ranges.extend(item.catechism_ranges)
            coverage.append(item.title)
            lanes.append(_profile_lane(item, depth))
        profile_title = str(getattr(plan, "display_title", ""))
        profile_key = str(getattr(plan, "topic_key", ""))
    elif profile:
        ranges.extend(profile.catechism_ranges)
        coverage.extend(profile.aspects)
        lanes.append(_profile_lane(profile, depth))
        profile_title = profile.title
        profile_key = profile.key
    else:
        profile_title = ""
        profile_key = ""
        source_types = " ".join(getattr(plan, "source_types", ()))
        category = str(getattr(plan, "category", ""))
        if "catecismo" in fold_text(source_types) or category in {
            "teologia_dogmatica", "cristologia", "pneumatologia", "eclesiologia", "mariologia",
            "sacramentos_liturgia", "moral_crista", "oracao_espiritualidade", "apologetica", "catequese_geral",
        }:
            lanes.append(SourceLane(
                "catechism_topic", "Catecismo — tema principal",
                f"Catecismo da Igreja Católica: {getattr(plan, 'theme', question)}. {', '.join(getattr(plan, 'dimensions', ()))}",
                ("catecismo",), 4 if depth == "aprofundado" else 2,
            ))

    category = str(getattr(plan, "category", ""))
    auxiliary_relevant = category in {
        "teologia_dogmatica", "cristologia", "pneumatologia", "eclesiologia", "mariologia",
        "sacramentos_liturgia", "moral_crista", "oracao_espiritualidade", "apologetica", "catequese_geral", "evangelhos",
    } or bool(re.search(r"\b(?:doutrin|teolog|moral|sacrament|apologet|cateques|catequese|fe|fé)\w*\b", question, re.IGNORECASE))
    if auxiliary_relevant:
        theme = str(getattr(plan, "theme", question))
        dimensions = ", ".join(getattr(plan, "dimensions", ()))
        lanes.extend((
            SourceLane("faith_explained", "A Fé Explicada", f"{theme}. {dimensions}", ("a fe explicada", "fe explicada"), 3),
            SourceLane("summa", "Suma Teológica", f"{theme}. princípios, causas, distinções, virtudes, vícios, objeções e respostas pertinentes", ("suma teologica", "suma"), 3),
        ))

    full_required = bool(group_profiles) or full_coverage_requested(question)
    return ResearchDirective(
        policy_version=POLICY_VERSION,
        profile_key=profile_key,
        profile_title=profile_title,
        catechism_ranges=tuple(dict.fromkeys(ranges)),
        coverage_items=tuple(dict.fromkeys(coverage)),
        full_coverage_required=full_required,
        source_lanes=tuple(dict.fromkeys(lanes)),
        source_integration=(
            "Catecismo e Magistério: síntese segura e grau de autoridade próprio",
            "A Fé Explicada: exposição catequética, exemplos e aplicações",
            "Suma Teológica: fundamentos, causas e distinções",
            "Catena Áurea: prioridade patrística somente para passagem concreta dos Evangelhos",
        ),
        final_checks=(
            "todos os itens e subitens pedidos foram tratados",
            "cada item recebeu conteúdo próprio e proporcional",
            "fontes obrigatórias pertinentes foram efetivamente integradas",
            "distinções doutrinais essenciais foram preservadas",
            "não há inferência, citação ou localização inventada",
            "a linguagem está clara, natural, pastoral e sem detalhes técnicos",
            "a resposta está completa sem repetições ou prolixidade",
        ),
    )
