# Relatório de implementação — MAGISTERIA 0.9.0 (Android build 900)

Data da verificação final: 29/07/2026.

## 1. Diagnóstico do problema original

O fluxo anterior recuperava um conjunto geral fixo de pelo menos 16 trechos e enviava a pergunta diretamente à composição. Não havia um plano explícito dos componentes católicos, busca por subtema, validação determinística de cobertura nem orçamento específico por profundidade. Isso favorecia introduções corretas, porém superficiais, em temas enumerativos como sacramentos, mandamentos, dogmas e livros bíblicos.

## 2. Arquivos analisados

Foram analisados o backend FastAPI (`app.py`, `config.py` e `services/`), o banco/autenticação, o índice FTS local, a geração e revisão pela API OpenAI, os diagnósticos RAG, os testes, a interface móvel TypeScript/Vite, o projeto Capacitor Android, a automação de release, os documentos de publicação e o acervo local usado no teste controlado.

## 3. Arquitetura existente encontrada

- FastAPI como API e aplicação web.
- SQLite para contas, sessões, cobrança e diagnósticos; SQLite FTS5 para recuperação documental.
- OpenAI Responses API para redação, crítica e eventual reescrita fundamentada.
- Vite + TypeScript como cliente móvel; Capacitor 8 como invólucro Android.
- GitHub Actions para geração de AAB assinado, mediante segredos protegidos.

## 4. Alterações implementadas

Foi adicionado um pipeline determinístico de classificação, taxonomia, decomposição e planejamento; recuperação geral e por componente; priorização por autoridade; deduplicação; orçamento dinâmico; cache documental; resumos técnicos; cobertura e citação; histórico privado; sugestões relacionadas; perfis de linguagem; métricas agregadas; interface móvel; invalidação por versão do acervo; e preparação Android 0.9.0 (900).

## 5. Arquivos criados

- `services/catholic_taxonomy.py`
- `services/response_planning.py`
- `services/retrieval_orchestrator.py`
- `services/response_quality.py`
- `services/semantic_cache.py`
- `services/search_history.py`
- `services/migrations.py`
- `migrations/0001_composite_queries.up.sql` e `.down.sql`
- `migrations/0002_document_summary_index.up.sql` e `.down.sql`
- `migrations/0003_document_summary_metadata.up.sql` e `.down.sql`
- `tests/test_composite_queries.py`
- `docs/release-0.9.0-play-testing.md`
- `docs/token-budget-comparison-0.9.0.md`
- `store-assets/android/release-notes-0.9.0-pt-BR.txt`
- este relatório.

## 6. Arquivos modificados

`.env.example`, `.github/workflows/android-release.yml`, `CHANGELOG.md`, `README.md`, `android/app/build.gradle`, `app.py`, `config.py`, `docs/google-play-publication.md`, `mobile/index.html`, `mobile/src/api.ts`, `mobile/src/main.ts`, `mobile/src/styles.css`, `mobile/src/types.ts`, `package.json`, `services/answer_service.py`, `services/auth_repository.py`, `services/rag_diagnostics.py`, `services/vector_store.py` e `tests/test_app.py`.

## 7. Migrations criadas

`0001` cria histórico, cache e resumos técnicos com índices; `0002` garante o índice de autoridade também em instalações nas quais `0001` já tenha sido aplicada; `0003` adiciona metadados técnicos de autor/autoridade, data, subtópicos, afirmações, palavras-chave e relações. Os `down.sql` são executados na ordem inversa. O rollback testado remove somente as estruturas novas e preserva usuários e tabelas anteriores. Colunas agregadas de diagnóstico usam o atual mecanismo aditivo e compatível do repositório, permanecendo inofensivas para uma versão anterior.

## 8. Mecanismo de aprofundamento

O plano identifica intenção, categoria, profundidade, tema, componentes, dimensões pertinentes, fontes preferidas, perfil e limites. Consultas implícitas, como “Quero compreender os sacramentos”, ativam os sete componentes. A busca é feita uma vez para a visão geral e novamente para cada componente ativo. Conjuntos extensos, como os 73 livros do cânon católico, são divididos em partes substantivas com continuação explícita.

## 9. Mecanismo de economia de tokens

Consultas simples usam uma única busca de até seis trechos e saída máxima de 2.000 tokens; resumos usam até 1.200; só consultas aprofundadas recebem contexto e saída ampliados. Planejamento, taxonomia, deduplicação, cache e sugestões não fazem chamadas extras. O contexto remove duplicatas e limita repetição por componente. A comparação detalhada está em `docs/token-budget-comparison-0.9.0.md`.

## 10. Funcionamento do cache

O cache é compartilhável apenas para plano e evidência documental: assinatura temática, componentes, IDs, trechos e referências. Ele nunca armazena nem devolve a resposta final. Perguntas equivalentes reaproveitam evidência, mas geram uma resposta nova para pergunta, profundidade e perfil atuais. A chave contém versões do acervo, taxonomia e estratégia; mudança documental, ativação/desativação ou reindexação altera/invalida a versão.

## 11. Funcionamento do histórico

O histórico consolida tema equivalente por usuário, aumenta a frequência e mantém consulta original de forma configurável. A tela “Histórico de consultas” permite listar, pesquisar, ordenar por data/frequência, identificar repetição, refazer, excluir item e limpar. Ao refazer, a API devolve a consulta original ou reconstrói uma consulta segura; o cliente executa novamente o pipeline.

## 12. Medidas de privacidade

Todas as operações de histórico filtram `user_id` obtido da sessão autenticada. Exclusão e reconsulta exigem proprietário; exclusão de conta usa cascata; há retenção configurável e exclusão lógica. Cache não contém usuário nem resposta. Diagnósticos apagam texto da consulta, documentos, motivo e erro livre, retendo somente contadores, categorias e estado técnico agregado. O administrador recebe métricas agregadas, não históricos individuais.

## 13. Testes criados

Foram cobertos os sete cenários doutrinais obrigatórios, detecção implícita, equivalência semântica do cache, cânon católico de 73 livros, orçamento simples, cobertura/citação, recuperação em camadas, invalidação por acervo, metadados técnicos, consolidação e isolamento do histórico, reconsulta, exclusão, cascata de conta, endpoints móveis e rollback. A jornada manual simulou conta, três níveis de consulta, histórico, reconsulta, exclusões, logout, segundo usuário, cache equivalente e atualização de acervo.

## 14. Resultado da primeira checagem

Compilação Python, suíte backend (87 testes), tipagem, lint, 2 testes móveis, build Vite e sincronização Capacitor foram aprovados. A revisão incluiu banco, autenticação, autorização, cache, recuperação, geração, responsividade e compatibilidade dos fluxos existentes.

## 15. Bugs encontrados e corrigidos

- Resumo dos sete sacramentos inicialmente não ativava componentes: corrigido.
- Reescrita após bloqueio mantinha estado incorreto: corrigido para `rewrite`.
- Prompt novo quebrou uma expectativa legada de apresentação de fontes: compatibilidade preservada com marcadores `[F#]`.
- Fontes exibidas podiam não refletir somente os trechos citados: corrigido o mapeamento de índices efetivamente usados.
- Cache podia permanecer válido após ativação/desativação ou alteração documental: adicionada invalidação/versionamento.
- Índice de resumos adicionado após uma migration já aplicada localmente: criada migration `0002` idempotente.
- Metadados de resumo documental estavam incompletos: criada migration `0003` e persistência ampliada.
- Consulta no singular “cada sacramento” não compartilhava a assinatura temática: adicionada equivalência taxonômica e teste.
- Comparação de consumo não distinguia versões nem erros de citação: adicionadas métricas por estratégia e contador específico.

## 16. Resultado da segunda checagem

Após as correções, passaram 89 testes backend e 2 testes móveis, compilação, tipagem, lint, build de produção e sincronização Android. A jornada manual passou. Um teste real controlado com a API OpenAI e o acervo local aprovou cobertura da consulta simples e dos sete sacramentos; a composta apresentou os sete itens, nove fontes válidas, nenhuma omissão e nenhuma superficialidade detectada. `git diff --check` não encontrou erro de whitespace.

## 17. Comparação de consumo de tokens

O limite bruto de trechos para consulta simples caiu de 16 para 6 (-62,5%) e a saída máxima de 2.400 para 2.000 (-16,7%). Um resumo composto dos sete sacramentos passa de 16 trechos gerais para até 12 blocos direcionados antes da deduplicação (-25%) e saída máxima de 1.200 (-50%). Consultas aprofundadas recebem deliberadamente até 10.500 tokens de contexto e 5.000 de saída. A API administrativa agora compara médias por `strategy_version`, incluindo quantidade de medições completas, para evitar interpretar zeros legados como consumo.

## 18. Limitações remanescentes

- O AAB assinado não foi gerado localmente: este computador não possui Java/JDK, Android SDK nem as quatro credenciais da upload key.
- O worktree limpo de release não contém o acervo; o teste real leu o acervo do worktree atual em modo somente leitura.
- A validação física em aparelhos e a revisão pré-lançamento da Play Console dependem do AAB assinado e da faixa de testes.
- Os validadores reduzem risco, mas não substituem revisão humana teológica em temas disputados, casos canônicos concretos ou documentação insuficiente.
- A redução financeira real deve ser confirmada com volume de uso na faixa de testes.

## 19. Recomendações futuras

1. Configurar os quatro segredos de upload no ambiente protegido `google-play`, executar o workflow e validar o AAB na Play Console.
2. Publicar primeiro o backend 0.9.0, fazer backup do SQLite e executar o roteiro com duas contas.
3. Observar métricas por estratégia por pelo menos uma semana e calibrar limites por categoria.
4. Expandir a taxonomia a partir dos temas realmente consultados, sem transformar todos os temas em respostas longas.
5. Acrescentar revisão doutrinal humana amostral e testes instrumentados em aparelhos Android de memória e tamanhos de tela variados.
