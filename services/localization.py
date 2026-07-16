from __future__ import annotations

from typing import Literal


LanguageCode = Literal["pt-BR", "en", "es"]
DEFAULT_LANGUAGE: LanguageCode = "pt-BR"
SUPPORTED_LANGUAGES = frozenset({"pt-BR", "en", "es"})

LANGUAGE_NAMES: dict[LanguageCode, str] = {
    "pt-BR": "português brasileiro",
    "en": "inglês internacional",
    "es": "espanhol internacional",
}

ANSWER_MESSAGES: dict[str, dict[LanguageCode, str]] = {
    "no_documents": {
        "pt-BR": "Não encontrei conteúdo correspondente na base documental.",
        "en": "I could not find corresponding content in the document database.",
        "es": "No encontré contenido correspondiente en la base documental.",
    },
    "low_confidence": {
        "pt-BR": (
            "Encontrei conteúdos relacionados, embora a correspondência não seja totalmente específica. "
            "A resposta abaixo apresenta os pontos mais próximos encontrados na base."
        ),
        "en": (
            "I found related content, although the match is not entirely specific. "
            "The answer below presents the closest points found in the database."
        ),
        "es": (
            "Encontré contenidos relacionados, aunque la coincidencia no es totalmente específica. "
            "La respuesta a continuación presenta los puntos más cercanos encontrados en la base."
        ),
    },
    "broad_topic": {
        "pt-BR": "Encontrei diversos conteúdos relacionados. Como o tema é amplo, apresentarei uma visão geral.",
        "en": "I found several related contents. Since the topic is broad, I will present an overview.",
        "es": "Encontré diversos contenidos relacionados. Como el tema es amplio, presentaré una visión general.",
    },
    "technical_failure": {
        "pt-BR": "Não foi possível concluir a pesquisa devido a uma falha técnica. Tente novamente.",
        "en": "The search could not be completed because of a technical failure. Please try again.",
        "es": "No fue posible concluir la búsqueda debido a una falla técnica. Inténtelo de nuevo.",
    },
}


def normalize_language(value: str | None) -> LanguageCode:
    normalized = (value or "").strip()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


def answer_message(key: str, language: str | None = None) -> str:
    return ANSWER_MESSAGES[key][normalize_language(language)]


def answer_language_instruction(language: str | None = None) -> str:
    selected = normalize_language(language)
    if selected == "pt-BR":
        return "Escreva a resposta final exclusivamente em português brasileiro contemporâneo."
    if selected == "en":
        return (
            "Write the final answer exclusively in clear, natural international English. "
            "Translate Catholic terminology accurately and do not leave explanatory prose in Portuguese."
        )
    return (
        "Escriba la respuesta final exclusivamente en español internacional claro y natural. "
        "Traduzca con precisión la terminología católica y no deje prosa explicativa en portugués."
    )


def presentation_language_instruction(language: str | None = None) -> str:
    selected = normalize_language(language)
    if selected == "pt-BR":
        return "Todo o conteúdo textual deve ser escrito em português brasileiro."
    if selected == "en":
        return "All textual content must be written in natural international English."
    return "Todo el contenido textual debe estar escrito en español internacional natural."


def localized_writing_standard(standard: str, language: str | None = None) -> str:
    selected = normalize_language(language)
    replacement = {
        "pt-BR": "em português brasileiro contemporâneo",
        "en": "em inglês internacional contemporâneo e natural",
        "es": "em espanhol internacional contemporâneo e natural",
    }[selected]
    return standard.replace("em português brasileiro contemporâneo", replacement)
