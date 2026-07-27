# 3. Problemas que precisam ser resolvidos

## Bloqueadores de loja

| Prioridade | Problema | Critério de encerramento |
|---|---|---|
| P0 | Não há política de privacidade completa nem URL pública | Documento publicado, coerente com coleta real e vinculado no app e nas lojas |
| P0 | Não há exclusão de conta | Fluxo autenticado no app e link web funcional, com política de retenção |
| P0 | Assinatura digital móvel não usa billing das lojas | Play Billing e StoreKit implementados ou decisão formal de app companion sem CTA, validada por storefront |
| P0 | Frontend Jinja não é empacotável | `mobile/dist/index.html` autônomo e API v1 funcional |
| P0 | Credencial inicial administrativa previsível | Bootstrap por segredo one-time/convite, rotação e verificação de produção |
| P0 | Ausência de projetos, assinatura e assets nativos | Android/iOS compilam reproduzivelmente, com IDs definitivos e chaves protegidas |
| P0 | Falta informação legal/comercial do proprietário | Itens do documento 11 respondidos e aprovados |

## Segurança e abuso

- Credencial bootstrap `Admin`/`3510` previsível em banco novo; verificar imediatamente se existe/foi rotacionada em produção sem expor a senha em logs.
- Login e cadastro sem rate limit; PBKDF2 torna credential stuffing também um vetor de CPU.
- Cookie de sessão sem flag `Secure`; troca de senha não revoga sessões anteriores.
- Reindexação acessível a usuário autenticado comum em uma rota e operações administrativas sem defesa CSRF completa.
- Quotas de IA verificadas e consumidas em operações separadas, permitindo corrida em pergunta, streaming, roteiro e slides.
- Geração de slides executa fallback CPU-bound no event loop e pode paralisar o único processo.
- Upload e indexação sem limites globais de bytes/páginas/chunks/tempo; offset/chunks precisam de protocolo e orçamento.
- Webhook legado Mercado Pago falha aberto se o segredo HMAC estiver ausente e não rejeita timestamps antigos.
- Redirecionamento de checkout aceita qualquer URL HTTPS retornada por provedor, sem allowlist de host.
- Diagnósticos RAG podem persistir consulta normalizada, derivados, motivos do modelo e erros sem redaction/TTL.
- Respostas de erro de pagamento podem registrar PII em logs.
- Cabeçalhos de segurança e CSP não foram observados na produção.
- O atalho de deploy usa `git add -A`, commit e push automáticos sem revisão de diff/secret scan.

## Produto e mobile

- Navegação desktop adaptada apenas por media query; falta arquitetura de rotas para celular.
- Sem estado offline, retry, prevenção de duplo envio global, cancelamento de request ou fila segura.
- Sem tratamento de app lifecycle, retorno de links, botão voltar Android, safe areas e teclado.
- Downloads por Blob precisam ser adaptados a arquivo/compartilhamento nativo.
- Checkout atual usa `window.location.assign`, inadequado para WebView e incompatível com a política padrão das lojas.
- Não há tela de assinatura multiplataforma, restaurar compras, gerenciar assinatura ou explicar estado de graça/reembolso.
- Não há tela de suporte, política, termos, exclusão e versão.
- Acessibilidade precisa de auditoria em dispositivo: foco, leitor de tela, contraste, fonte ampliada e alvos de toque.

## Dados e operação

- SQLite e índice em volume único são adequados apenas enquanto houver uma réplica e carga controlada.
- Não há evidência no repositório de backup automatizado, teste de restauração, RPO/RTO ou retenção.
- Diagnósticos não têm retenção; dados pessoais podem permanecer indefinidamente.
- Contrato de API não é versionado; atualização do servidor pode quebrar apps instalados.
- Não há ambientes mobile separados (dev/staging/prod), feature flags, kill switch ou minimum supported version.
- A produção confia em proxy headers amplamente; confirmar a fronteira real do Railway.

## Pendências de diagnóstico externo

Não foi possível confirmar apenas pelo repositório:

- valores e rotação dos segredos no Railway;
- backups e restaurações do volume;
- contas e contratos Asaas/Mercado Pago;
- política de logs/retention do Railway e OpenAI;
- situação da conta administrativa em produção;
- titularidade e licenças do corpus;
- contas Google/Apple, status de trader, fiscal e bancário;
- domínios, suporte e documentos legais.

Esses itens exigem acesso do proprietário ou exportações controladas, nunca inclusão de segredos no chat ou no repositório.

