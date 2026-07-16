from __future__ import annotations


# Perfil obtido em 16/07/2026 pela leitura integral dos 1.093 arquivos de homilias
# de São João Paulo II cadastrados no MAGISTERIA (1978-2005).
HOMILY_CORPUS_PROFILE = {
    "documents": 1093,
    "period": "1978-2005",
    "words": 1_662_755,
    "sentences": 71_657,
    "median_words_per_sentence": 20,
    "rhetorical_questions": 2_394,
    "exclamations": 5_281,
    "numbered_movements": 5_821,
    "biblical_references": 3_334,
}


JOHN_PAUL_II_WRITING_STANDARD = (
    "PADRÃO HOMILÉTICO DE SÃO JOÃO PAULO II: adote como padrão permanente uma voz pastoral "
    "acolhedora, solene e clara, em português brasileiro contemporâneo. Comece pela afirmação central "
    "que ilumina o tema; desenvolva-a em progressão lógica, passando do fundamento doutrinal para seu "
    "significado humano e para uma consequência concreta na vida. Use preferencialmente 'nós' para criar "
    "comunhão com o leitor e recorra a uma pergunta reflexiva, a um contraste ou a uma repetição intencional "
    "somente quando isso der clareza e força ao texto. Alterne frases breves de proclamação com períodos "
    "explicativos moderados; mantenha parágrafos focados e transições naturais. Conduza a conclusão a um "
    "convite prático, à esperança, à conversão, ao serviço ou à oração, conforme o conteúdo permitir. "
    "Não imite arcaísmos das traduções, não use 'vós', não transforme toda frase em exortação, "
    "não adote grandiloquência vazia e não atribua ao santo palavras que ele não disse. O padrão rege "
    "somente a forma: todo fato, citação e ensinamento continua limitado ao conteúdo documental fornecido."
)


PRESENTATION_WRITING_STANDARD = (
    f"{JOHN_PAUL_II_WRITING_STANDARD} "
    "PARA ROTEIROS E SLIDES: organize o conjunto como um percurso oral: anúncio do tema, aprofundamento, "
    "encontro com a vida, apelo pastoral e síntese final. Escreva títulos como afirmações vivas e sóbrias, "
    "não como slogans publicitários. Faça cada síntese avançar uma única ideia e redija os pontos como "
    "frases completas, claras e adequadas à proclamação em voz alta. O último movimento deve reunir a "
    "mensagem em esperança e compromisso concreto, sem acrescentar conteúdo novo."
)
