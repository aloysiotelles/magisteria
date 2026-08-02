from __future__ import annotations

from pathlib import Path
import json
import re

from openai import AsyncOpenAI

from services.editorial_style import JOHN_PAUL_II_WRITING_STANDARD, MAGISTERIA_LANGUAGE_STANDARD
from services.localization import (
    answer_language_instruction,
    answer_message,
    localized_writing_standard,
    normalize_language,
)
from services.query_analysis import QueryType, analyze_query
from services.research_policy import build_research_directive
from services.response_planning import ResponsePlan, build_response_plan
from services.response_quality import (
    CoverageValidator,
    DoctrinalConsistencyValidator,
    PatristicAttributionValidator,
)


ABSOLUTE_RULE = (
    "Responda somente com base nos trechos fornecidos após as buscas sucessivas do planejamento. Integre toda evidência "
    "pertinente disponível e cubra integralmente o pedido na primeira resposta. Se ainda assim um detalhe não estiver "
    "seguramente sustentado, formule somente o que for seguro, com discrição e sem expor o funcionamento interno da "
    "pesquisa. Nunca transforme uma limitação pontual em declaração de ausência geral."
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
        self.attribution_validator = PatristicAttributionValidator()

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
        research_directive = build_research_directive(question, plan)
        if not chunks:
            if self.api_key and not plan.is_gospel:
                return await self._answer_from_general_catholic_teaching(
                    question, history or [], selected_language, plan
                )
            return {
                "resposta": answer_message("no_documents", selected_language),
                "status_revisao": "no_documents",
                "motivo_revisao": "Orientação geral indisponível sem o serviço de redação configurado.",
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
        invalid_attributions = self.attribution_validator.validate(final_answer, chunks) if plan.is_gospel else ()
        if invalid_attributions:
            final_answer = await self._grounded_rewrite(
                question,
                final_answer,
                chunks,
                "Remova ou torne impessoais as atribuições patrísticas não confirmadas pelos trechos: "
                + ", ".join(invalid_attributions),
                history or [],
                selected_language,
                plan,
            )
            regenerated = True
            action = "rewrite"
            coverage = self.coverage_validator.validate_answer(plan, final_answer, len(chunks))
            invalid_attributions = self.attribution_validator.validate(final_answer, chunks)
        final_answer = self._sanitize_pipeline_language(final_answer)
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
            "attribution_validation": {
                "passed": not invalid_attributions,
                "invalid_attributions": list(invalid_attributions),
            },
            "research_policy": research_directive.to_dict(),
        }

    async def _answer_from_general_catholic_teaching(
        self,
        question: str,
        history: list[dict],
        language: str,
        plan: ResponsePlan,
    ) -> dict:
        """Oferece uma síntese prudente sem revelar detalhes da recuperação documental."""
        conversation = "\n\n".join(
            f"USUÁRIO: {turn.get('pergunta', '')}\nMAGISTERIA: {turn.get('resposta', '')}"
            for turn in history[-3:]
        ) or "Sem conversa anterior."
        answer = await self._create_complete_text(
            {
                "model": self.model,
                "instructions": (
                    "Você é o assistente teológico-pastoral do MAGISTERIA. Responda à luz da doutrina católica, "
                    "limitando-se a ensinamentos gerais, estáveis e de alta confiança. Quando não puder sustentar com "
                    "segurança uma afirmação específica, permaneça nos princípios doutrinais seguros e formule-a com "
                    "prudência. Não diga que não encontrou conteúdo, que um documento não está disponível ou que a "
                    "pesquisa foi insuficiente. Não exponha qualquer detalhe técnico do funcionamento do aplicativo. "
                    "Não invente citações literais, números de parágrafos, cânones, referências bíblicas, nomes de "
                    "documentos específicos ou atribuições magisteriais. Você pode mencionar de modo geral a Sagrada "
                    "Escritura, a Tradição, o Magistério e o Catecismo quando isso ajudar a situar o ensinamento, sem "
                    "simular uma referência precisa. Responda integralmente ao que for possível afirmar com segurança. "
                    f"Adapte a linguagem ao perfil informado: {plan.profile_instruction}. "
                    f"{build_research_directive(question, plan).instruction()} "
                    f"{self._structure_instruction(plan)} "
                    f"{self._format_instruction(question)} "
                    f"{localized_writing_standard(JOHN_PAUL_II_WRITING_STANDARD, language)} "
                    f"{localized_writing_standard(MAGISTERIA_LANGUAGE_STANDARD, language)} "
                    f"{self._catechesis_instruction(question)}"
                    f"{answer_language_instruction(language)}"
                ),
                "input": (
                    f"HISTÓRICO DA CONVERSA:\n{conversation}\n\n"
                    f"PERGUNTA ATUAL:\n{question}\n\n"
                    f"PLANO INTERNO DE COBERTURA:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}"
                ),
                "max_output_tokens": plan.max_output_tokens,
            },
            language,
        )
        if not answer:
            raise RuntimeError(answer_message("technical_failure", language))
        coverage = self.coverage_validator.validate_answer(plan, answer, 0)
        return {
            "resposta": self._sanitize_pipeline_language(answer),
            "status_revisao": "general_guidance",
            "motivo_revisao": "Síntese pastoral prudente baseada nos ensinamentos gerais da Igreja.",
            "coverage": coverage.to_dict(),
            "used_source_indexes": [],
            "input_tokens_estimated": self._estimate_input_tokens(question, [], history, plan),
            "output_tokens_estimated": max(len(answer) // 4, 1),
            "regenerated": False,
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
        research_directive = build_research_directive(question, plan)
        if not chunks:
            return {"approved": False, "reason": "Sem base documental suficiente."}
        if not self.api_key:
            raise RuntimeError("A chave OPENAI_API_KEY ainda não foi configurada no arquivo .env.")

        context = "\n\n".join(
            f"[ORDEM {chunk.get('ordem', 1)} — {chunk.get('categoria', 'Documento')} — TRECHO {number} — {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        source_metadata = json.dumps(
            [
                {
                    "marker": f"F{number}",
                    "collection": chunk.get("collection"),
                    "work": chunk.get("work"),
                    "compiler": chunk.get("compiler"),
                    "gospel": chunk.get("gospel"),
                    "chapter": chunk.get("chapter"),
                    "verse_start": chunk.get("verse_start"),
                    "verse_end": chunk.get("verse_end"),
                    "pericope": chunk.get("pericope"),
                    "patristic_authors": chunk.get("patristic_authors") or [],
                    "source_work": chunk.get("source_work"),
                    "location": chunk.get("location"),
                    "gospel_role": chunk.get("gospel_role"),
                }
                for number, chunk in enumerate(chunks, start=1)
            ],
            ensure_ascii=False,
        )
        conversation = "\n\n".join(
            f"USUÁRIO: {turn.get('pergunta', '')}\nMAGISTERIA: {turn.get('resposta', '')}"
            for turn in (history or [])[-3:]
        ) or "Sem conversa anterior."
        style_context = "\n\n".join(
            f"[AMOSTRA DE ESTILO {number} - {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(style_chunks or [], start=1)
        ) or "Sem amostras especificas de homilias para esta pergunta."
        gospel_review = (
            "Em consulta evangélica, confira especialmente: passagem principal e paralelos; prioridade real da "
            "Catena na leitura patrística; distinção entre Escritura, Catena, Magistério e síntese; atribuição de "
            "cada Padre somente quando confirmada nos metadados; e ausência de falsa declaração de consulta à "
            "Catena quando não houver trecho dessa coleção. Qualquer atribuição não rastreável exige rewrite."
            if plan.is_gospel else ""
        )

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
            f" {localized_writing_standard(MAGISTERIA_LANGUAGE_STANDARD, selected_language)}"
            f" {self._format_instruction(question)}"
            f" {self._catechesis_instruction(question)}"
            f" {gospel_review}"
            f" {research_directive.instruction()}"
        )
        response = await self.client.responses.create(
            model=self.review_model,
            instructions=review_prompt,
            input=(
                f"PERGUNTA:\n{question}\n\n"
                f"HISTÓRICO:\n{conversation}\n\n"
                f"TRECHOS:\n{context}\n\n"
                f"METADADOS RASTREÁVEIS:\n{source_metadata}\n\n"
                f"AMOSTRAS DE ESTILO:\n{style_context}\n\n"
                f"PLANO DE COBERTURA:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                f"DIRETRIZ DE PESQUISA E VALIDAÇÃO:\n{json.dumps(research_directive.to_dict(), ensure_ascii=False)}\n\n"
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
    def _sanitize_pipeline_language(text: str) -> str:
        replacements = (
            (r"\bos (?:trechos|chunks) (?:fornecidos|recuperados|cadastrados)\b", "as fontes consultadas"),
            (r"\bnos (?:trechos|chunks) (?:fornecidos|recuperados|cadastrados)\b", "nas fontes consultadas"),
            (r"\bsegundo os (?:trechos|chunks)\b", "segundo as fontes consultadas"),
            (r"\ba base (?:documental|vetorial)\b", "as fontes consultadas"),
            (r"\ba busca (?:vetorial|documental)\b", "a pesquisa"),
            (r"\bo contexto recuperado\b", "o conjunto das fontes consultadas"),
        )
        sanitized = text
        for pattern, replacement in replacements:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
        return sanitized

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
        research_directive = build_research_directive(question, plan)
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
                f"{localized_writing_standard(MAGISTERIA_LANGUAGE_STANDARD, language)} "
                f"{research_directive.instruction()} "
                f"{self._format_instruction(question)} "
                f"{self._catechesis_instruction(question)}"
                f"{answer_language_instruction(language)}"
            ),
            "input": (
                f"CONSULTA:\n{question}\n\nMOTIVO DA REVISÃO:\n{review_reason}\n\n"
                f"PLANO:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                f"DIRETRIZ DE PESQUISA:\n{json.dumps(research_directive.to_dict(), ensure_ascii=False)}\n\n"
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
        research_directive = build_research_directive(question, plan)
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
                    f"{research_directive.instruction()} "
                    f"{localized_writing_standard(MAGISTERIA_LANGUAGE_STANDARD, language)} "
                    f"{self._format_instruction(question)} "
                    f"{answer_language_instruction(language)}"
                ),
                "input": (
                    f"CONSULTA:\n{question}\n\nITENS A COMPLETAR:\n{target_text}\n\n"
                    f"RESPOSTA JÁ PRODUZIDA (não repetir):\n{current_answer}\n\n"
                    f"PLANO COMPLETO:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}\n\n"
                    f"DIRETRIZ DE PESQUISA:\n{json.dumps(research_directive.to_dict(), ensure_ascii=False)}\n\n"
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

    @staticmethod
    def _source_metadata(chunks: list[dict]) -> str:
        return json.dumps(
            [
                {
                    "marker": f"F{number}",
                    "collection": chunk.get("collection"),
                    "work": chunk.get("work"),
                    "compiler": chunk.get("compiler"),
                    "gospel": chunk.get("gospel"),
                    "chapter": chunk.get("chapter"),
                    "verse_start": chunk.get("verse_start"),
                    "verse_end": chunk.get("verse_end"),
                    "pericope": chunk.get("pericope"),
                    "patristic_authors": chunk.get("patristic_authors") or [],
                    "source_work": chunk.get("source_work"),
                    "location": chunk.get("location"),
                    "gospel_role": chunk.get("gospel_role"),
                }
                for number, chunk in enumerate(chunks, start=1)
            ],
            ensure_ascii=False,
        )

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
        research_directive = build_research_directive(question, plan)
        context = "\n\n".join(
            f"[F{number} — ORDEM {chunk.get('ordem', 1)} — {chunk.get('categoria', 'Documento')} — "
            f"{chunk['source']}, {chunk['location']} — componente: {chunk.get('component', 'visão geral')}]\n{chunk['text']}"
            for number, chunk in enumerate(chunks, start=1)
        )
        source_metadata = self._source_metadata(chunks)
        conversation = "\n\n".join(
            f"USUÁRIO: {turn.get('pergunta', '')}\nMAGISTERIA: {turn.get('resposta', '')}"
            for turn in history[-3:]
        ) or "Sem conversa anterior."
        style_context = "\n\n".join(
            f"[AMOSTRA DE ESTILO {number} - {chunk['source']}, {chunk['location']}]\n{chunk['text']}"
            for number, chunk in enumerate(style_chunks or [], start=1)
        ) or "Sem amostras especificas de homilias para esta pergunta."
        catechesis_instruction = self._catechesis_instruction(question)
        format_instruction = self._format_instruction(question)
        thematic_instruction = ""
        if analysis.query_type in {QueryType.TERM, QueryType.PHRASE}:
            thematic_instruction = (
                "O usuário informou um tema, não necessariamente uma pergunta. Produza uma visão panorâmica "
                "e organizada exclusivamente a partir dos trechos recuperados. Apresente apenas os principais aspectos "
                "efetivamente encontrados e, se útil, indique subdivisões documentadas que possam ser aprofundadas. "
                "Não trate a amplitude ou a brevidade da consulta como ausência de conteúdo. "
            )
        structure_instruction = self._structure_instruction(plan)
        gospel_instruction = self._gospel_instruction(plan, chunks)
        return {
            "model": self.model,
            "instructions": (
                "Você é o assistente documental do MAGISTERIA. "
                f"REGRA ABSOLUTA: {ABSOLUTE_RULE} "
                f"{thematic_instruction} "
                f"{structure_instruction} "
                f"{gospel_instruction} "
                f"{research_directive.instruction()} "
                f"Adapte a linguagem ao perfil informado: {plan.profile_instruction}. "
                "Não use memória, conhecimento geral, inferências externas ou pesquisa na internet. "
                "Não mencione fontes que não estejam nos trechos. "
                f"{localized_writing_standard(JOHN_PAUL_II_WRITING_STANDARD, language)} "
                f"{localized_writing_standard(MAGISTERIA_LANGUAGE_STANDARD, language)} "
                "Use as AMOSTRAS DE ESTILO DAS HOMILIAS apenas para calibrar ritmo e cadência; não retire delas "
                "afirmações factuais para responder se elas não estiverem também apoiadas nos TRECHOS CADASTRADOS. "
                "Comece diretamente pela resposta. Explique termos religiosos com simplicidade quando necessário. "
                f"{format_instruction} "
                f"{catechesis_instruction}"
                "Quando a pergunta pedir o significado ou a definição de um termo e os trechos trouxerem uma seção, "
                "um título ou uma frase que o defina explicitamente, responda a partir dessa definição; nesse caso, "
                "é incorreto alegar que a informação não foi encontrada. "
                "Prefira parágrafos claros e use listas e títulos somente quando facilitarem a compreensão do conjunto. "
                "Use texto simples, sem Markdown, asteriscos ou títulos com cerquilhas. "
                "Use a ordem dos trechos como hierarquia de autoridade para elaborar a resposta, mas entregue uma única "
                "síntese consolidada. Não divida a resposta por documento e não repita a mesma ideia porque ela apareceu "
                "em fontes diferentes. Mencione as fontes com naturalidade quando isso ajudar a explicação, sem enumerar "
                "documentos a cada parágrafo. "
                "Produza um texto fluido e tão didático quanto possível: apresente primeiro a ideia central, desenvolva os "
                "conceitos em sequência lógica, explique palavras técnicas em linguagem simples e conclua com uma síntese "
                "prática. Use transições naturais entre os parágrafos. "
                "Integre citações bíblicas ao texto somente quando os trechos da Bíblia Ave Maria fornecerem a referência "
                "e o texto de versículos pertinentes; introduções e comentários bíblicos não são citações. Transcreva "
                "apenas o que estiver no trecho e use o nome do livro indicado na localização; nunca complete uma citação "
                "de memória. "
                "Não crie uma bibliografia nem uma lista extensa de fontes no corpo; atribua as fontes principais com "
                "naturalidade e deixe a identificação completa para a interface. "
                "Após afirmações centrais, use marcações [F1], [F2] etc. correspondentes aos trechos fornecidos. "
                "Nunca use número de fonte inexistente e nunca fabrique parágrafo, cânon ou referência. A interface "
                "apresentará a identificação completa das fontes ao final. "
                f"{DoctrinalConsistencyValidator.instruction()} "
                "O histórico serve apenas para compreender perguntas de continuidade: toda afirmação da nova resposta "
                "continua obrigada a estar apoiada nos TRECHOS CADASTRADOS desta solicitação. "
                f"{answer_language_instruction(language)}"
            ),
            "input": (
                f"HISTÓRICO DA CONVERSA:\n{conversation}\n\n"
                f"PERGUNTA ATUAL:\n{question}\n\nTRECHOS CADASTRADOS EM ORDEM EDITORIAL:\n{context}"
                f"\n\nMETADADOS DOCUMENTAIS RASTREÁVEIS DOS TRECHOS:\n{source_metadata}"
                f"\n\nPLANO INTERNO DE COBERTURA:\n{json.dumps(plan.to_dict(), ensure_ascii=False)}"
                f"\n\nDIRETRIZ INTERNA DE PESQUISA E VALIDAÇÃO:\n{json.dumps(research_directive.to_dict(), ensure_ascii=False)}"
                f"\n\nAMOSTRAS DE ESTILO DAS HOMILIAS:\n{style_context}"
            ),
            "max_output_tokens": plan.max_output_tokens,
        }

    @staticmethod
    def _gospel_instruction(plan: ResponsePlan, chunks: list[dict]) -> str:
        if not plan.is_gospel:
            return ""
        catena_chunks = [chunk for chunk in chunks if chunk.get("collection") == "CATENA_AUREA"]
        references = ", ".join(plan.gospel.passage_references) or "passagem identificada nos trechos"
        if catena_chunks:
            catena_status = (
                "A Catena Áurea foi efetivamente recuperada. Faça dela o núcleo da leitura patrística, "
                "sem colocá-la acima da própria Escritura ou do Magistério."
            )
        else:
            catena_status = (
                "A recuperação da Catena Áurea não forneceu trecho utilizável. Não diga que ela foi consultada, "
                "não invente comentários e fundamente a resposta somente nas demais fontes recuperadas."
            )
        return (
            f"Esta é uma consulta evangélica sobre {plan.gospel.episode}; passagens identificadas: {references}. "
            f"{catena_status} Distinga explicitamente: texto e contexto evangélico; leitura patrística reunida na "
            "Catena Áurea; ensinamento do Catecismo ou do Magistério; e síntese teológica do MAGISTERIA. "
            "Quando houver narrativas paralelas, explique como se iluminam mutuamente sem forçar harmonização nem "
            "tratar diferenças legítimas como contradições. Atribua uma interpretação a um Padre somente se o nome "
            "constar nos metadados rastreáveis ou no rótulo explícito do trecho correspondente. Se a autoria não "
            "estiver confirmada, escreva 'o comentário reunido na Catena Áurea observa que'. Nunca deduza um autor. "
            "Em explicações amplas, organize com estas seções em texto simples, omitindo apenas as manifestamente "
            "inaplicáveis: 1. Passagem evangélica; 2. Contexto; 3. Leitura da Catena Áurea; 4. Síntese patrística; "
            "5. Complementação pelas demais fontes; 6. Sentido teológico; 7. Aplicação à vida cristã; "
            "8. Fontes consultadas. Na última seção, mencione somente fontes e autores realmente usados e mantenha "
            "as marcações [F1], [F2] que dão rastreabilidade."
        )

    @staticmethod
    def _structure_instruction(plan: ResponsePlan) -> str:
        if not plan.composite:
            return (
                "Responda proporcionalmente, com começo, desenvolvimento e conclusão: apresente a ideia central, os "
                "fundamentos principais, a explicação e a aplicação quando pertinente. Não expanda uma consulta simples "
                "apenas para preencher uma estrutura."
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
            "A consulta exige uma resposta composta e completa, não uma visão geral abreviada. Conduza o texto como uma "
            "aula bem organizada: introduza o tema, desenvolva os fundamentos e as distinções pertinentes, explique todos "
            "os itens pedidos e conclua reunindo o sentido doutrinal e sua importância para a vida cristã. Se títulos ou "
            "uma lista inicial ajudarem a orientação, use-os com moderação e desenvolva cada item também em parágrafos. "
            f"Componentes obrigatórios nesta resposta: {components}. Cada componente precisa de explicação autônoma, "
            "equilibrada e proporcional; uma lista ou frase genérica por item não basta. "
            f"Dimensões pertinentes a selecionar, sem aplicação mecânica: {', '.join(plan.dimensions)}."
            f"{scope} Antes de encerrar, verifique silenciosamente se todos os itens, seções e distinções pedidos "
            "foram incluídos e corrija qualquer omissão."
        )

    @staticmethod
    def _format_instruction(question: str) -> str:
        normalized = question.casefold().translate(str.maketrans(
            "áàãâäéèêëíìîïóòõôöúùûüç",
            "aaaaaeeeeiiiiooooouuuuc",
        ))
        if re.search(r"\b(homilia|pregacao|sermao)\b", normalized):
            return (
                "Como o gênero pedido é homilético, use linguagem proclamativa, espiritual e pastoral, com unidade "
                "temática e apelo à vida cristã; não escreva como artigo acadêmico nem como relatório."
            )
        if re.search(r"\b(formacao|encontro formativo|aula)\b", normalized):
            return (
                "Como o gênero pedido é formativo, apresente a exposição de modo progressivo, com exemplos, "
                "aplicações práticas e síntese final, preservando a continuidade entre as partes."
            )
        return ""

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
                "colecao": chunk.get("collection", ""),
                "obra": chunk.get("work", ""),
                "compilador": chunk.get("compiler", ""),
                "autores_patristicos": [],
                "passagens_evangelicas": [],
            },
        )
        item["referencias"].extend(chunk.get("referencias", []))
        item["locais"].append(chunk["location"])
        if chunk.get("citation_index"):
            item["indices_citacao"].append(int(chunk["citation_index"]))
        authors = chunk.get("patristic_authors") or ()
        if isinstance(authors, str):
            authors = (authors,)
        item["autores_patristicos"].extend(str(author) for author in authors if author)
        if chunk.get("gospel") and chunk.get("chapter"):
            reference = next(iter(chunk.get("referencias") or ()), f"{chunk['gospel']} {chunk['chapter']}")
            item["passagens_evangelicas"].append(reference)
        item["relevancia"] = max(item["relevancia"], chunk.get("score", 0))

    sources = []
    for item in grouped.values():
        references = list(dict.fromkeys(item.pop("referencias")))
        locations = list(dict.fromkeys(item.pop("locais")))
        citation_indexes = sorted(set(item.pop("indices_citacao")))
        item["autores_patristicos"] = list(dict.fromkeys(item["autores_patristicos"]))
        item["passagens_evangelicas"] = list(dict.fromkeys(item["passagens_evangelicas"]))
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
        if item.get("colecao") == "CATENA_AUREA":
            locator_parts = [*item["passagens_evangelicas"][:12], *locations[:12]]
            local = "; ".join(dict.fromkeys(locator_parts))
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
        if source.get("colecao") == "CATENA_AUREA" or "catena" in normalized:
            entry = (
                "TOMÁS DE AQUINO (comp.). Catena Áurea: exposição contínua dos quatro Evangelhos. "
                f"[S. l.: s. n.], [s. d.]. {locator}."
            )
        elif "catecismo" in normalized:
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
