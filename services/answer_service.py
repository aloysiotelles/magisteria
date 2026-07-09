from __future__ import annotations

from pathlib import Path
import re

from openai import AsyncOpenAI


ABSOLUTE_RULE = (
    "Responda somente com base nos trechos fornecidos. Se os trechos não forem suficientes, "
    "diga que não encontrou essa informação nos documentos cadastrados. "
    "Quando a evidência estiver fraca ou parecer insuficiente, dê preferência a aprofundar a resposta com base em A Fé Explicada, "
    "se houver trechos dessa obra entre os cadastrados, antes de concluir que a base não contém resposta."
)
NOT_FOUND_MESSAGE = "Não encontrei essa informação nos documentos cadastrados."


class AnswerService:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None

    async def answer(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
    ) -> str:
        if not chunks:
            return NOT_FOUND_MESSAGE
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        response = await self.client.responses.create(**self._request_arguments(question, chunks, history or [], style_chunks or []))
        answer = (response.output_text or "").strip()
        return answer or NOT_FOUND_MESSAGE

    async def stream_answer(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
    ):
        if not chunks:
            yield NOT_FOUND_MESSAGE
            return
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        base_arguments = self._request_arguments(question, chunks, history or [], style_chunks or [])
        previous_response_id = None

        for continuation in range(3):
            arguments = dict(base_arguments)
            if previous_response_id:
                arguments.update(
                    previous_response_id=previous_response_id,
                    input=(
                        "Continue exatamente do ponto em que a resposta foi interrompida. "
                        "Não repita o texto anterior e conclua todas as seções de forma breve."
                    ),
                )

            stream = await self.client.responses.create(**arguments, stream=True)
            incomplete = False
            async for event in stream:
                if event.type == "response.created":
                    previous_response_id = event.response.id
                elif event.type == "response.output_text.delta":
                    yield event.delta
                elif event.type == "response.incomplete":
                    incomplete = True
                    previous_response_id = event.response.id

            if not incomplete:
                return
            if not previous_response_id:
                raise RuntimeError("A resposta foi interrompida sem identificador para continuação.")

        raise RuntimeError("A resposta permaneceu incompleta após as tentativas de continuação.")

    def _request_arguments(self, question: str, chunks: list[dict], history: list[dict], style_chunks: list[dict] | None = None) -> dict:
        context = "\n\n".join(
            f"[ORDEM {chunk.get('ordem', 1)} — {chunk.get('categoria', 'Documento')} — "
            f"TRECHO {number} — {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        conversation = "\n\n".join(
            f"USUÁRIO: {turn.get('pergunta', '')}\nMAGISTERIA: {turn.get('resposta', '')}"
            for turn in history[-3:]
        ) or "Sem conversa anterior."
        style_context = "\n\n".join(
            f"[AMOSTRA DE ESTILO {number} - {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(style_chunks or [], start=1)
        ) or "Sem amostras especificas de homilias para esta pergunta."
        return {
            "model": self.model,
            "instructions": (
                "Você é o assistente documental do MAGISTERIA. "
                f"REGRA ABSOLUTA: {ABSOLUTE_RULE} "
                "Não use memória, conhecimento geral, inferências externas ou pesquisa na internet. "
                "Não mencione fontes que não estejam nos trechos. "
                "Escreva em português brasileiro, com tom acolhedor, sereno e próximo, sem parecer mecânico. "
                "Quando houver AMOSTRAS DE ESTILO DAS HOMILIAS, aproxime o ritmo, a clareza pastoral, o apelo espiritual "
                "e a forma exortativa dessas homilias. Use essas amostras apenas como modelo de escrita; não retire delas "
                "afirmações factuais para responder se elas não estiverem também apoiadas nos TRECHOS CADASTRADOS. "
                "Comece diretamente pela resposta. Explique termos religiosos com simplicidade quando necessário. "
                "Prefira parágrafos curtos e use uma lista apenas quando ela realmente facilitar a compreensão. "
                "Use texto simples, sem Markdown, asteriscos ou títulos com cerquilhas. "
                "Use a ordem dos trechos como hierarquia de autoridade para elaborar a resposta, mas entregue uma única "
                "síntese consolidada. Não divida a resposta por documento, não anuncie nomes de obras, não escreva frases "
                "como 'segundo o Catecismo' e não repita a mesma ideia porque ela apareceu em fontes diferentes. "
                "Produza um texto fluido e tão didático quanto possível: apresente primeiro a ideia central, desenvolva os "
                "conceitos em sequência lógica, explique palavras técnicas em linguagem simples e conclua com uma síntese "
                "prática. Use transições naturais entre os parágrafos. "
                "Integre citações bíblicas ao texto somente quando os trechos da Bíblia Ave Maria fornecerem a referência "
                "e o texto de versículos pertinentes; introduções e comentários bíblicos não são citações. Transcreva "
                "apenas o que estiver no trecho e use o nome do livro indicado na localização; nunca complete uma citação "
                "de memória. "
                "Não informe nem liste as fontes no corpo da resposta, pois a interface as apresentará separadamente ao final. "
                "O histórico serve apenas para compreender perguntas de continuidade: toda afirmação da nova resposta "
                "continua obrigada a estar apoiada nos TRECHOS CADASTRADOS desta solicitação."
            ),
            "input": (
                f"HISTÓRICO DA CONVERSA:\n{conversation}\n\n"
                f"PERGUNTA ATUAL:\n{question}\n\nTRECHOS CADASTRADOS EM ORDEM EDITORIAL:\n{context}"
                f"\n\nAMOSTRAS DE ESTILO DAS HOMILIAS:\n{style_context}"
            ),
            "max_output_tokens": 2400,
        }


def format_sources(chunks: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for chunk in chunks:
        item = grouped.setdefault(
            chunk["source"],
            {
                "arquivo": chunk["source"],
                "categoria": chunk.get("categoria", "Documento"),
                "referencias": [],
                "locais": [],
                "relevancia": chunk["score"],
            },
        )
        item["referencias"].extend(chunk.get("referencias", []))
        item["locais"].append(chunk["location"])
        item["relevancia"] = max(item["relevancia"], chunk["score"])

    sources = []
    for item in grouped.values():
        references = list(dict.fromkeys(item.pop("referencias")))
        locations = list(dict.fromkeys(item.pop("locais")))
        normalized = item["arquivo"].lower()
        if references and "bíblia" in normalized:
            local = "; ".join(references[:8])
        elif references and "vaticano ii" in normalized:
            local = "; ".join(references[:12])
        elif references and any(name in normalized for name in ("catecismo", "compendio")):
            local = "§§ " + ", ".join(_compact_references(references))
        elif "bíblia" in normalized:
            local = "Referência de capítulo e versículo não identificada no trecho"
        else:
            local = "; ".join(locations)
        sources.append({**item, "local": local, "tem_referencias": bool(references)})
    return sources


def _compact_references(references: list[str]) -> list[str]:
    numeric = sorted({int(value) for value in references if value.isdigit()})
    compacted: list[str] = []
    if numeric:
        start = previous = numeric[0]
        for value in numeric[1:] + [None]:
            if value is not None and value == previous + 1:
                previous = value
                continue
            compacted.append(str(start) if start == previous else f"{start}–{previous}")
            if value is not None:
                start = previous = value
    compacted.extend(value for value in references if not value.isdigit())
    return list(dict.fromkeys(compacted))


def format_abnt_references(chunks: list[dict]) -> str:
    lines = []
    sources = format_sources(chunks)
    best_relevance = max((source.get("relevancia", 0) for source in sources), default=0)
    for source in sources:
        if not _should_include_abnt_source(source, best_relevance):
            continue
        filename = source["arquivo"]
        normalized = filename.lower()
        locator = source["local"].replace("página ", "p. ")
        if "catecismo" in normalized:
            entry = f"IGREJA CATÓLICA. Catecismo da Igreja Católica. [S. l.: s. n.], [s. d.]. {locator}."
        elif "simbolos" in normalized:
            entry = (
                "IGREJA CATÓLICA. Compêndio dos símbolos, definições e declarações de fé e moral. "
                f"[S. l.: s. n.], [s. d.]. {locator}."
            )
        elif "doutrina-social" in normalized or "doutrina social" in normalized:
            entry = (
                "PONTIFÍCIO CONSELHO JUSTIÇA E PAZ. Compêndio da Doutrina Social da Igreja. "
                f"[S. l.: s. n.], [s. d.]. {locator}."
            )
        elif "bíblia" in normalized:
            entry = f"BÍBLIA. Português. Bíblia Ave Maria: edição de estudo. [S. l.: s. n.], [s. d.]. {locator}."
        elif "vaticano ii" in normalized:
            entry = (
                "CONCÍLIO VATICANO II. Documentos do Concílio Vaticano II. "
                f"[S. l.: s. n.], [s. d.]. {locator}."
            )
        elif "a fe explicada" in normalized or "fe explicada" in normalized:
            entry = f"TRESE, Leo J. A Fé Explicada. [S. l.: s. n.], [s. d.]. {locator}."
        elif "suma teológica" in normalized:
            entry = f"TOMÁS DE AQUINO. Suma Teológica. [S. l.: s. n.], [s. d.]. {locator}."
        else:
            title = re.sub(r"[-_]+", " ", Path(filename).stem).strip()
            entry = f"{title.upper()}. [S. l.: s. n.], [s. d.]. {locator}."
        lines.append(entry)
    return "\n".join(lines)


def _should_include_abnt_source(source: dict, best_relevance: float) -> bool:
    """Evita citar documentos que apareceram apenas como achado fraco na busca."""
    if source.get("tem_referencias"):
        return True
    relevance = source.get("relevancia", 0)
    return relevance >= max(0.2, best_relevance * 0.55)
