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
        "pt-BR": "À luz da doutrina católica, este tema deve ser tratado com prudência e sem atribuir referências específicas não confirmadas.",
        "en": "In light of Catholic doctrine, this subject should be treated prudently and without attributing unconfirmed specific references.",
        "es": "A la luz de la doctrina católica, este tema debe tratarse con prudencia y sin atribuir referencias específicas no confirmadas.",
    },
    "low_confidence": {
        "pt-BR": (
            "Segundo as fontes consultadas, é possível apresentar com segurança os aspectos centrais do tema. "
            "Os pontos que exigem maior precisão serão formulados com a devida prudência."
        ),
        "en": (
            "According to the sources consulted, the central aspects of the subject can be presented safely. "
            "Points requiring greater precision will be stated with due prudence."
        ),
        "es": (
            "Según las fuentes consultadas, los aspectos centrales del tema pueden presentarse con seguridad. "
            "Los puntos que requieran mayor precisión se formularán con la debida prudencia."
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
