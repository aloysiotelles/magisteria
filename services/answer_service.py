from __future__ import annotations

from pathlib import Path
import json
import re

from openai import AsyncOpenAI

from services.editorial_style import JOHN_PAUL_II_WRITING_STANDARD
from services.localization import (
    answer_language_instruction,
    answer_message,
    localized_writing_standard,
    normalize_language,
)
from services.query_analysis import QueryType, analyze_query
from services.response_planning import ResponsePlan, build_response_plan
from services.response_quality import CoverageValidator, DoctrinalConsistencyValidator


ABSOLUTE_RULE = (
    "Responda somente com base nos trechos fornecidos. Se eles sustentarem apenas parte do pedido, "
    "declare a limitação e responda somente essa parte. A mensagem de ausência documental é reservada "
    "ao pipeline de recuperação quando nenhum trecho foi localizado; não a use quando recebeu trechos relacionados. "
    "Quando a evidência estiver fraca ou parecer insuficiente, dê preferência a aprofundar a resposta com base em A Fé Explicada, "
    "se houver trechos dessa obra entre os cadastrados, antes de concluir que a base não contém resposta."
)
NO_DOCUMENTS_MESSAGE = answer_message("no_documents")
NOT_FOUND_MESSAGE = NO_DOCUMENTS_MESSAGE
LOW_CONFIDENCE_MESSAGE = answer_message("low_confidence")
BROAD_TOPIC_MESSAGE = answer_message("broad_topic")
TECHNICAL_FAILURE_MESSAGE = answer_message("technical_failure")


class AnswerService:
    def __init__(self, api_key: str, model: str, review_model: str | None = None):
        self.api_key = api_key
        self.model = model
        self.review_model = review_model or model
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.coverage_validator = CoverageValidator()

    async def answer(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
        language: str = "pt-BR",
        plan: ResponsePlan | None = None,
    ) -> str:
        result = await self.answer_with_review(question, chunks, history, style_chunks, language, plan)
        return result["resposta"]

    async def translate_query_to_portuguese(self, query: str, source_language: str) -> str:
        """Converte somente a consulta de recuperação; nunca traduz documentos da base."""
        selected = normalize_language(source_language)
        cleaned = query.strip()
        if selected == "pt-BR" or not cleaned:
            return cleaned
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")
        response = await self.client.responses.create(
            model=self.model,
            instructions=(
                "Traduza a consulta do usuário para português brasileiro para uso exclusivo em uma busca documental. "
                "Preserve nomes próprios, títulos de documentos, números, siglas, referências bíblicas e o sentido exato. "
                "Não responda à consulta, não explique a tradução e entregue somente a consulta traduzida em texto simples."
            ),
            input=cleaned,
            max_output_tokens=350,
        )
        translated = (response.output_text or "").strip()
        if not translated:
            raise RuntimeError(answer_message("technical_failure", selected))
        return translated

    async def answer_with_review(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
        language: str = "pt-BR",
        plan: ResponsePlan | None = None,
    ) -> dict:
        selected_language = normalize_language(language)
        plan = plan or build_response_plan(question, selected_language)
        if not chunks:
            return {
                "resposta": answer_message("no_documents", selected_language),
                "status_revisao": "no_documents",
                "motivo_revisao": "Todas as estratégias de recuperação foram executadas sem evidência documental.",
                "coverage": self.coverage_validator.validate_retrieval(plan, []).to_dict(),
                "used_source_indexes": [],
                "input_tokens_estimated": 0,
                "output_tokens_estimated": 0,
                "regenerated": False,
            }
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        answer = await self._create_complete_text(
            self._request_arguments(
                question, chunks, history or [], style_chunks or [], selected_language, plan
            ),
            selected_language,
        )
        if not answer:
            return {
                "resposta": answer_message("no_documents", selected_language),
                "status_revisao": "block",
                "motivo_revisao": "Resposta vazia do modelo principal.",
                "coverage": self.coverage_validator.validate_answer(plan, "", len(chunks)).to_dict(),
                "used_source_indexes": [],
                "input_tokens_estimated": self._estimate_input_tokens(question, chunks, history or [], plan),
                "output_tokens_estimated": 0,
                "regenerated": False,
            }
        review = await self.review_answer(
            question, answer, chunks, history or [], style_chunks or [], selected_language, plan
        )
        action = review.get("action", "approve")
        if action == "approve":
            final_answer = answer
        else:
            fallback = review.get("suggested_answer", "").strip()
            if action == "rewrite" and fallback and not self._looks_like_absence_message(fallback):
                final_answer = fallback
            else:
                # O crítico pode corrigir fidelidade, mas não converter chunks existentes em
                # "ausência documental". Uma rejeição aciona uma reescrita fundamentada.
                final_answer = await self._grounded_rewrite(
                    question, answer, chunks, review.get("reason", ""), history or [],
                    selected_language, plan,
                )
                action = "rewrite"

        regenerated = action != "approve"
        coverage = self.coverage_validator.validate_answer(plan, final_answer, len(chunks))
        if plan.composite and not coverage.passed:
            reason = self._coverage_reason(coverage.to_dict())
            final_answer = await self._grounded_rewrite(
                question, final_answer, chunks, reason, history or [], selected_language, plan,
            )
            regenerated = True
            action = "rewrite"
            coverage = self.coverage_validator.validate_answer(plan, final_answer, len(chunks))

        # Caso uma enumeração ainda tenha lacunas, completa internamente os itens
        # restantes e só então devolve a resposta. O lote deriva do orçamento real
        # do plano; não existe recorte fixo da lista doutrinal.
        if plan.composite and not coverage.passed:
            batch_size = max(1, (plan.max_output_tokens - 1200) // 280)
            initial_targets = list(dict.fromkeys((
                *coverage.missing_components,
                *coverage.shallow_components,
            )))
            attempts_allowed = max(
                2,
                (len(initial_targets) + batch_size - 1) // batch_size + 1,
            )
            previous_failures = coverage.failure_count
            stalled = 0
            while attempts_allowed > 0 and not coverage.passed:
                targets = list(dict.fromkeys((
                    *coverage.missing_components,
                    *coverage.shallow_components,
                )))
                if not targets and coverage.invalid_citations:
                    targets = ["Fundamentação documental e síntese final"]
                if not targets:
                    break
                batch = targets[:batch_size]
                addition = await self._grounded_completion(
                    question,
                    final_answer,
                    chunks,
                    batch,
                    selected_language,
                    plan,
                )
                final_answer = f"{final_answer.rstrip()}\n\n{addition.lstrip()}"
                coverage = self.coverage_validator.validate_answer(plan, final_answer, len(chunks))
                regenerated = True
                action = "rewrite"
                attempts_allowed -= 1
                if coverage.failure_count >= previous_failures:
                    stalled += 1
                else:
                    stalled = 0
                previous_failures = coverage.failure_count
                if stalled >= 2:
                    break
        used_indexes = self.coverage_validator.used_source_indexes(final_answer, len(chunks))
        return {
            "resposta": final_answer,
            "status_revisao": action,
            "motivo_revisao": review.get("reason", "") or (
                "Resposta ajustada para permanecer fiel aos trechos e cobrir o plano."
                if regenerated else ""
            ),
            "coverage": coverage.to_dict(),
            "used_source_indexes": list(used_indexes),
            "input_tokens_estimated": self._estimate_input_tokens(question, chunks, history or [], plan),
            "output_tokens_estimated": max(len(final_answer) // 4, 1),
            "regenerated": regenerated,
        }

    async def _create_complete_text(self, arguments: dict, language: str) -> str:
        """Conclui respostas interrompidas pelo limite técnico antes de publicá-las."""
        response = await self.client.responses.create(**arguments)
        parts = [(getattr(response, "output_text", "") or "").strip()]
        previous_ids: set[str] = set()
        continuation_count = 0
        while str(getattr(response, "status", "")) == "incomplete":
            response_id = str(getattr(response, "id", "") or "")
            if not response_id or response_id in previous_ids or continuation_count >= 12:
                raise RuntimeError(answer_message("technical_failure", language))
            previous_ids.add(response_id)
            continuation_count += 1
            response = await self.client.responses.create(
                model=arguments["model"],
                previous_response_id=response_id,
                input=(
                    "Continue exatamente do ponto interrompido. Não repita nada já escrito. "
                    "Conclua todos os itens e seções pendentes do plano e faça a verificação interna de completude. "
                    f"{answer_language_instruction(language)}"
                ),
                max_output_tokens=arguments.get("max_output_tokens", 6000),
            )
            part = (getattr(response, "output_text", "") or "").strip()
            if part:
                parts.append(part)
        return "\n\n".join(part for part in parts if part).strip()

    async def stream_answer(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
        language: str = "pt-BR",
    ):
        selected_language = normalize_language(language)
        if not chunks:
            yield answer_message("no_documents", selected_language)
            return
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        base_arguments = self._request_arguments(
            question, chunks, history or [], style_chunks or [], selected_language
        )
        previous_response_id = None

        for continuation in range(3):
            arguments = dict(base_arguments)
            if previous_response_id:
                arguments.update(
                    previous_response_id=previous_response_id,
                    input=(
                        "Continue exatamente do ponto em que a resposta foi interrompida. "
                        "Não repita o texto anterior e conclua todas as seções de forma breve. "
                        f"{answer_language_instruction(selected_language)}"
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

    async def review_answer(
        self,
        question: str,
        answer: str,
        chunks: list[dict],
        history: list[dict] | None = None,
        style_chunks: list[dict] | None = None,
        language: str = "pt-BR",
        plan: ResponsePlan | None = None,
    ) -> dict:
        selected_language = normalize_language(language)
        plan = plan or build_response_plan(question, selected_language)
        if not chunks:
            return {"approved": False, "reason": "Sem base documental suficiente."}
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        context = "\n\n".join(
            f"[ORDEM {chunk.get('ordem', 1)} — {chunk.get('categoria', 'Documento')} — TRECHO {number} — {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        conversation = "\n\n".join(
            f"USUÁRIO: {turn.get('pergunta', '')}\nMAGISTERIA: {turn.get('resposta', '')}"
            for turn in (history or [])[-3:]
        ) or "Sem conversa anterior."
        style_context = "\n\n".join(
            f"[AMOSTRA DE ESTILO {number} - {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(style_chunks or [], start=1)
        ) or "Sem amostras especificas de homilias para esta pergunta."

        review_prompt = (
            "Você é um verificador de respostas documentais. "
            "Seu trabalho é avaliar se a resposta abaixo está apoiada nos trechos fornecidos. "
            "Não use conhecimento externo. Não acrescente conteúdo novo. "
            "Responda apenas em JSON válido com as chaves: action (string), reason (string), suggested_answer (string). "
            "Se não houver problema claro, prefira action='approve'. "
            "Use action='rewrite' quando a ideia central estiver correta, mas a formulação precise ser mais cautelosa ou breve. "
            "Use action='block' somente quando houver extrapolação inequívoca, contradição, citação indevida, erro factual ou excesso de confiança evidente. "
            "Nesse caso, suggested_answer deve conter uma recusa educada ou uma versão muito conservadora."
            "Para consultas compostas, confirme também se todos os componentes ativos do plano foram explicados "
            "com profundidade proporcional, se há uma conclusão integradora e se as marcações [F1], [F2] etc. "
            "apontam somente para trechos fornecidos. Omissão de componente essencial exige action='rewrite'. "
            f"{DoctrinalConsistencyValidator.instruction()} "
            f" Qualquer suggested_answer deve obedecer a esta regra: {answer_language_instruction(selected_language)}"
            f" Verifique também a forma segundo esta regra, sem bloquear uma resposta factual apenas por estilo: "
            f"{localized_writing_standard(JOHN_PAUL_II_WRITING_STANDARD, selected_language)}"
            f" {self._catechesis_instruction(question)}"
        )
        response = await self.client.responses.create(
            model=self.review_model,
            instructions=review_prompt,
            input=(
                f"PERGUNTA:\n{question}\n\n"
                f"HISTÓRICO:\n{conversation}\n\n"
                f"TRECHOS:\n{context}\n\n"
                f"AMOSTRAS DE ESTILO:\n{style_context}\n\n"
                f"PLANO DE COBERTURA:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                f"RESPOSTA A VALIDAR:\n{answer}"
            ),
            max_output_tokens=700,
        )
        parsed = self._parse_review_response((response.output_text or "").strip())
        if parsed is None:
            return {
                "action": "rewrite",
                "reason": "O revisor devolveu um formato inválido; a evidência recuperada foi preservada.",
                "suggested_answer": answer,
            }
        return self._soften_overstrict_block(parsed, answer)

    @staticmethod
    def _looks_like_absence_message(text: str) -> bool:
        normalized = text.casefold()
        return any(
            phrase in normalized
            for phrase in (
                "não encontrei", "nao encontrei", "nenhum conteúdo", "nenhum conteudo",
                "sem base documental", "base não contém", "base nao contem",
                "could not find", "couldn't find", "no content", "no documentary basis",
                "no encontré", "no encontre", "ningún contenido", "ningun contenido",
                "sin base documental", "la base no contiene",
            )
        )

    @staticmethod
    def _is_catechesis_request(question: str) -> bool:
        """Detecta pedidos de produção de uma catequese, sem depender de acentos."""
        normalized = re.sub(r"\s+", " ", question.casefold()).strip()
        normalized = normalized.translate(str.maketrans(
            "áàãâäéèêëíìîïóòõôöúùûüç",
            "aaaaaeeeeiiiiooooouuuuc",
        ))
        return bool(re.search(
            r"\b(?:prepare|redija|elabore|monte|produza|crie|faca|facam|escreva|preciso de)\b"
            r"[^.!?\n]{0,80}\buma?\s+catequese\b",
            normalized,
        )) or bool(re.search(r"\b(?:prepare|redija|elabore|monte|produza|crie|escreva)\b[^.!?\n]{0,80}\bcatequese\b", normalized))

    @classmethod
    def _catechesis_instruction(cls, question: str) -> str:
        if not cls._is_catechesis_request(question):
            return ""
        return (
            "ATENÇÃO: a palavra catequese indica apenas o formato pedido pelo usuário; ela não é o tema da resposta. "
            "Comece diretamente pelo tema solicitado. É proibido definir, explicar, introduzir ou fazer um histórico "
            "sobre o que é catequese, educação da fé, iniciação cristã ou elementos da catequese, salvo se o usuário "
            "pedir isso expressamente. Não use trechos recuperados que definam catequese para desviar do tema. "
            "Se a resposta fizer isso, marque action='rewrite' e reescreva removendo esse conteúdo. "
            "Redija o conteúdo como uma catequese pronta, com exemplos concretos adequados ao público declarado "
            "e linguagem didática. "
        )

    async def _grounded_rewrite(
        self,
        question: str,
        answer: str,
        chunks: list[dict],
        review_reason: str,
        history: list[dict],
        language: str = "pt-BR",
        plan: ResponsePlan | None = None,
    ) -> str:
        plan = plan or build_response_plan(question, language)
        context = "\n\n".join(
            f"[F{number} — {chunk['source']}, {chunk['location']} — componente: {chunk.get('component', 'visão geral')}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        rewritten = await self._create_complete_text(
            {
            "model": self.review_model,
            "instructions": (
                "Reescreva a resposta usando exclusivamente os trechos fornecidos. Remova toda afirmação "
                "que não esteja claramente apoiada. Preserve as partes válidas e responda de modo conservador. "
                "Não use conhecimento externo. Como existem trechos recuperados, não diga que nenhum documento "
                "foi encontrado. Se o tema for amplo, produza uma visão geral apenas dos aspectos comprovados. "
                "Cumpra o plano de cobertura, desenvolva cada componente ativo e use marcações [F1], [F2] etc. "
                "somente quando a afirmação estiver apoiada no trecho correspondente. Nunca invente uma marcação. "
                "Entregue somente a resposta reescrita, sem comentários sobre a revisão. "
                f"{self._catechesis_instruction(question)}"
                f"{answer_language_instruction(language)}"
            ),
            "input": (
                f"CONSULTA:\n{question}\n\nMOTIVO DA REVISÃO:\n{review_reason}\n\n"
                f"PLANO:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                f"RESPOSTA ORIGINAL:\n{answer}\n\nTRECHOS:\n{context}"
            ),
            "max_output_tokens": plan.max_output_tokens,
            },
            language,
        )
        if not rewritten or self._looks_like_absence_message(rewritten):
            raise RuntimeError(answer_message("technical_failure", language))
        return rewritten

    async def _grounded_completion(
        self,
        question: str,
        current_answer: str,
        chunks: list[dict],
        targets: list[str],
        language: str,
        plan: ResponsePlan,
    ) -> str:
        context = "\n\n".join(
            f"[F{number} — {chunk['source']}, {chunk['location']} — componente: "
            f"{chunk.get('component', 'visão geral')}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        target_text = "; ".join(targets)
        result = await self._create_complete_text(
            {
                "model": self.review_model,
                "instructions": (
                    "Complete uma resposta documental já iniciada. Escreva somente as subseções ainda ausentes "
                    "ou superficiais, sem repetir introdução nem conteúdo já satisfatório. Crie uma subseção própria "
                    "para cada item solicitado, desenvolva as dimensões sustentadas pelos trechos e use apenas "
                    "marcações [F1], [F2] etc. existentes. Não use conhecimento externo nem fabrique referências. "
                    "Se um aspecto específico não estiver comprovado, declare essa limitação dentro da subseção, "
                    "mas não omita o item. Termine com síntese integradora somente se ela estiver pendente. "
                    f"{DoctrinalConsistencyValidator.instruction()} "
                    f"{answer_language_instruction(language)}"
                ),
                "input": (
                    f"CONSULTA:\n{question}\n\nITENS A COMPLETAR:\n{target_text}\n\n"
                    f"RESPOSTA JÁ PRODUZIDA (não repetir):\n{current_answer}\n\n"
                    f"PLANO COMPLETO:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                    f"TRECHOS AUTORIZADOS:\n{context}"
                ),
                "max_output_tokens": min(
                    plan.max_output_tokens,
                    max(1800, len(targets) * 300 + 1000),
                ),
            },
            language,
        )
        if not result or self._looks_like_absence_message(result):
            raise RuntimeError(answer_message("technical_failure", language))
        return result

    def _parse_review_response(self, text: str) -> dict | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        action = str(data.get("action", "")).strip().lower()
        if action not in {"approve", "rewrite", "block"}:
            approved = bool(data.get("approved"))
            action = "approve" if approved else "block"
        reason = str(data.get("reason", "")).strip()
        suggested_answer = str(data.get("suggested_answer", "")).strip()
        return {"action": action, "reason": reason, "suggested_answer": suggested_answer}

    def _soften_overstrict_block(self, review: dict, answer: str) -> dict:
        action = review.get("action", "approve")
        if action != "block":
            return review

        reason = str(review.get("reason", "")).strip()
        normalized_reason = reason.casefold()
        generic_block = not normalized_reason or any(
            phrase in normalized_reason
            for phrase in (
                "não foi possível validar",
                "nao foi possivel validar",
                "sem base documental suficiente",
                "base insuficiente",
                "resposta vazia",
                "não encontrei",
                "nao encontrei",
                "excessivamente conservadora",
            )
        )
        if generic_block:
            return {
                "action": "rewrite",
                "reason": reason or "Revisão conservadora demais; resposta ajustada para evitar falso bloqueio.",
                "suggested_answer": answer,
            }
        return review

    def _request_arguments(
        self,
        question: str,
        chunks: list[dict],
        history: list[dict],
        style_chunks: list[dict] | None = None,
        language: str = "pt-BR",
        plan: ResponsePlan | None = None,
    ) -> dict:
        analysis = analyze_query(question)
        plan = plan or build_response_plan(question, language)
        context = "\n\n".join(
            f"[F{number} — ORDEM {chunk.get('ordem', 1)} — {chunk.get('categoria', 'Documento')} — "
            f"{chunk['source']}, {chunk['location']} — componente: {chunk.get('component', 'visão geral')}]\n{chunk['text']}"
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
        catechesis_instruction = self._catechesis_instruction(question)
        thematic_instruction = ""
        if analysis.query_type in {QueryType.TERM, QueryType.PHRASE}:
            thematic_instruction = (
                "O usuário informou um tema, não necessariamente uma pergunta. Produza uma visão panorâmica "
                "e organizada exclusivamente a partir dos trechos recuperados. Apresente apenas os principais aspectos "
                "efetivamente encontrados e, se útil, indique subdivisões documentadas que possam ser aprofundadas. "
                "Não trate a amplitude ou a brevidade da consulta como ausência de conteúdo. "
            )
        structure_instruction = self._structure_instruction(plan)
        return {
            "model": self.model,
            "instructions": (
                "Você é o assistente documental do MAGISTERIA. "
                f"REGRA ABSOLUTA: {ABSOLUTE_RULE} "
                f"{thematic_instruction} "
                f"{structure_instruction} "
                f"Adapte a linguagem ao perfil informado: {plan.profile_instruction}. "
                "Não use memória, conhecimento geral, inferências externas ou pesquisa na internet. "
                "Não mencione fontes que não estejam nos trechos. "
                f"{localized_writing_standard(JOHN_PAUL_II_WRITING_STANDARD, language)} "
                "Use as AMOSTRAS DE ESTILO DAS HOMILIAS apenas para calibrar ritmo e cadência; não retire delas "
                "afirmações factuais para responder se elas não estiverem também apoiadas nos TRECHOS CADASTRADOS. "
                "Comece diretamente pela resposta. Explique termos religiosos com simplicidade quando necessário. "
                f"{catechesis_instruction}"
                "Quando a pergunta pedir o significado ou a definição de um termo e os trechos trouxerem uma seção, "
                "um título ou uma frase que o defina explicitamente, responda a partir dessa definição; nesse caso, "
                "é incorreto alegar que a informação não foi encontrada. "
                "Prefira parágrafos curtos e use listas e títulos numerados quando facilitarem a cobertura do plano. "
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
                "Não informe nem liste as fontes no corpo além das marcações de apoio. "
                "Após afirmações centrais, use marcações [F1], [F2] etc. correspondentes aos trechos fornecidos. "
                "Nunca use número de fonte inexistente e nunca fabrique parágrafo, cânon ou referência. A interface "
                "apresentará a identificação completa das fontes ao final; não crie uma bibliografia no corpo. "
                f"{DoctrinalConsistencyValidator.instruction()} "
                "O histórico serve apenas para compreender perguntas de continuidade: toda afirmação da nova resposta "
                "continua obrigada a estar apoiada nos TRECHOS CADASTRADOS desta solicitação. "
                f"{answer_language_instruction(language)}"
            ),
            "input": (
                f"HISTÓRICO DA CONVERSA:\n{conversation}\n\n"
                f"PERGUNTA ATUAL:\n{question}\n\nTRECHOS CADASTRADOS EM ORDEM EDITORIAL:\n{context}"
                f"\n\nPLANO INTERNO DE COBERTURA:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}"
                f"\n\nAMOSTRAS DE ESTILO DAS HOMILIAS:\n{style_context}"
            ),
            "max_output_tokens": plan.max_output_tokens,
        }

    @staticmethod
    def _structure_instruction(plan: ResponsePlan) -> str:
        if not plan.composite:
            return (
                "Responda proporcionalmente: definição, fundamentos principais, explicação e aplicação quando pertinente. "
                "Não expanda uma consulta simples apenas para preencher uma estrutura."
            )
        components = "; ".join(plan.active_components) or "itens documentados recuperados para o catálogo"
        scope = (
            f" Este é um conjunto fechado com {len(plan.active_components)} itens; nenhum pode ser omitido."
            if plan.closed_set and plan.active_components
            else f" Escopo obrigatório do catálogo: {plan.catalog_scope}"
            if plan.catalog_scope
            else ""
        )
        return (
            "A consulta exige resposta composta e exaustiva, não uma visão geral abreviada. Organize, conforme "
            "a evidência disponível, em: 1. Introdução; 2. Definição geral; 3. Fundamento bíblico; "
            "4. Catecismo; 5. Magistério; 6. Contexto histórico; 7. Desenvolvimento doutrinal; "
            "8. Explicação completa de cada item; 9. Exemplos; 10. Aplicações práticas; "
            "11. Erros comuns e distinções; 12. Síntese final; 13. Sugestões de aprofundamento. "
            f"Componentes obrigatórios nesta resposta: {components}. Cada componente precisa de explicação autônoma, "
            "com subtítulo próprio, equilibrada e proporcional; uma lista ou frase genérica por item não basta. "
            f"Dimensões pertinentes a selecionar, sem aplicação mecânica: {', '.join(plan.dimensions)}."
            f"{scope} Antes de encerrar, verifique silenciosamente se todos os itens, seções e distinções pedidos "
            "foram incluídos e corrija qualquer omissão."
        )

    @staticmethod
    def _estimate_input_tokens(
        question: str,
        chunks: list[dict],
        history: list[dict],
        plan: ResponsePlan | None = None,
    ) -> int:
        characters = len(question) + 3000  # instruções estáticas aproximadas
        characters += sum(len(str(chunk.get("text") or "")) for chunk in chunks)
        characters += sum(
            len(str(turn.get("pergunta") or "")) + len(str(turn.get("resposta") or ""))
            for turn in history[-3:]
        )
        if plan:
            characters += len(json.dumps(plan.to_dict(), ensure_ascii=False))
        return max(characters // 4, 1)

    @staticmethod
    def _coverage_reason(coverage: dict) -> str:
        missing = ", ".join(coverage.get("missing_components") or []) or "nenhum"
        shallow = ", ".join(coverage.get("shallow_components") or []) or "nenhum"
        invalid = ", ".join(coverage.get("invalid_citations") or []) or "nenhuma"
        return (
            "A verificação automática de cobertura pediu revisão. "
            f"Componentes ausentes: {missing}. Componentes superficiais: {shallow}. "
            f"Marcações de fonte inválidas ou ausentes: {invalid}."
        )


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
                "indices_citacao": [],
                "relevancia": chunk.get("score", 0),
            },
        )
        item["referencias"].extend(chunk.get("referencias", []))
        item["locais"].append(chunk["location"])
        if chunk.get("citation_index"):
            item["indices_citacao"].append(int(chunk["citation_index"]))
        item["relevancia"] = max(item["relevancia"], chunk.get("score", 0))

    sources = []
    for item in grouped.values():
        references = list(dict.fromkeys(item.pop("referencias")))
        locations = list(dict.fromkeys(item.pop("locais")))
        citation_indexes = sorted(set(item.pop("indices_citacao")))
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
        sources.append({
            **item,
            "local": local,
            "tem_referencias": bool(references),
            "marcador": ", ".join(f"F{index}" for index in citation_indexes),
        })
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
