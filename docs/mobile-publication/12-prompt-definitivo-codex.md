# 12. Prompt técnico definitivo para execução pelo Codex

Use este prompt somente depois de o proprietário responder ao documento 11 e aprovar a fase a executar. Substitua os campos `PREENCHER`; não forneça segredos no prompt.

```text
Atue como líder técnico de implementação do MagisterIA. Trabalhe no repositório existente e preserve o backend FastAPI, a hospedagem Railway, o corpus, a IA e as regras de negócio. Não publique, não faça deploy, não altere produção, não crie produtos nas lojas e não execute operações destrutivas sem minha autorização expressa.

Contexto verificado em 16/07/2026:
- backend Python 3.12/FastAPI/Uvicorn no Railway;
- frontend atual Jinja + JavaScript/CSS sem build SPA;
- autenticação web por cookie de sessão server-side;
- SQLite transacional e índice SQLite/FTS no volume;
- Asaas é o checkout web ativo; Mercado Pago é legado;
- OpenAI atende RAG, revisão, roteiro e slides;
- não existe Capacitor, Android, iOS, PWA, política completa ou exclusão de conta;
- a suíte atual possui 55 testes aprovados;
- diagnóstico e planos estão em docs/mobile-publication/.

Decisões aprovadas pelo proprietário:
- app/package Android: PREENCHER
- bundle ID iOS: PREENCHER
- entidade publicadora e domínios: PREENCHER
- países/storefronts e idiomas: PREENCHER
- planos/produtos/preços: PREENCHER
- estratégia RevenueCat ou integrações próprias: PREENCHER
- versões mínimas Android/iOS: PREENCHER
- política/termos/suporte/exclusão URLs: PREENCHER
- decisão SQLite/PostgreSQL e prazo: PREENCHER
- analytics/crash aprovado: PREENCHER
- fase autorizada nesta execução: PREENCHER

Objetivo arquitetural obrigatório:
1. manter a versão web e um único backend/fonte de verdade no Railway;
2. criar modelo híbrido Capacitor, com UI compilada/empacotada e API HTTPS;
3. não usar WebView remota como arquitetura principal;
4. não duplicar banco, regras, usuários, documentos ou IA;
5. manter segredos exclusivamente no servidor/CI protegido;
6. preservar compatibilidade da web e versionar a API em /api/v1;
7. usar Play Billing no Android e StoreKit 2 no iOS para recursos digitais, exceto decisão formal por storefront;
8. manter Asaas somente na web e não mostrar checkout externo nos builds nativos sem permissão comprovada;
9. fazer o backend validar compras, receber eventos e resolver entitlement unificado;
10. implementar restauração, cancelamento, reembolso, expiração, graça, idempotência e reconciliação.

Antes de editar:
- leia integralmente AGENTS.md/instruções aplicáveis, README, Docker/Railway, requirements, app.py, config, services, templates/static e testes;
- leia todos os 12 documentos em docs/mobile-publication/;
- confirme branch, status Git e mudanças do usuário; não sobrescreva alterações não relacionadas;
- produza plano com fases, arquivos, migrações, riscos, testes e rollback;
- sinalize qualquer decisão ainda ausente; não invente valores.

Ordem de execução:

Fase A — hardening e contratos
- eliminar bootstrap Admin/3510 e criar inicialização one-time segura;
- rate limit de login/cadastro/IA, limites de body/upload/parser/indexação;
- require_admin em reindexação e CSRF/Origin para web;
- revogar sessões na troca de senha; cookie Secure; tokens móveis curtos + refresh rotativo em armazenamento seguro;
- tornar quotas e operações caras atômicas/idempotentes;
- tirar CPU-bound do event loop;
- fechar webhook MP quando secret ausente, validar freshness/replay ou remover legado aprovado;
- redigir PII/segredos de diagnósticos/logs e aplicar TTL;
- validar allowlist de URLs externas e adicionar headers/CSP;
- criar exclusão de conta, retenção e testes.

Fase B — API móvel
- criar /api/v1 e schemas OpenAPI estáveis;
- implementar autenticação bearer móvel sem remover cookie web;
- CORS por origens exatas, configuração remota, feature flags e minimum supported version;
- cobrir perfil, IA/streaming, fontes, documentos, histórico, suporte, política e conta;
- manter compatibilidade N-1.

Fase C — assinaturas
- criar migrations para subscriptions, subscription_events e entitlements;
- preservar origem, plataforma, IDs externos, plano, status, períodos, cancelamento, reembolso, graça, último evento e última verificação;
- integrar Play Billing/RTDN e StoreKit 2/App Store Server Notifications/API, ou RevenueCat conforme decisão;
- nunca confiar em estado declarado pelo cliente;
- adicionar sandboxes/fakes e matriz completa de testes.

Fase D — cliente empacotável e Capacitor
- criar mobile/ em TypeScript com build para mobile/dist/index.html;
- reutilizar estilos, traduções e fluxos úteis sem copiar regras de negócio;
- adicionar Capacitor estável, android/ e ios/ somente quando a fase for autorizada;
- implementar splash, ícones, navegação, back Android, loading, offline, secure storage, browser externo, arquivos, share, safe areas, teclado, acessibilidade, IA loading e prevenção de duplicidade;
- usar allowlist de navegação e bloquear HTTP/mixed content/segredos.

Fase E — qualidade e entrega
- testes unitários, integração, contrato, E2E, segurança, carga e dispositivos;
- builds release reproduzíveis, sem assinar/publicar se não autorizado;
- atualizar checklists e documentação com evidências reais;
- não marcar item concluído sem teste/artefato correspondente.

Regras de mudança:
- use migrações expand/contract e forward-fix; não apague dados;
- não toque em produção ou painel Railway;
- não execute git push, PR, publicação ou submissão;
- não coloque tokens/chaves no Git, frontend, logs ou resposta;
- mantenha mudanças pequenas, revisáveis e cobertas por testes;
- se uma ação exigir conta, Mac, certificado, contrato, segredo ou escolha do proprietário, pare essa ação, registre a pendência e continue apenas no que for seguro e independente.

Entregáveis da fase autorizada:
- código e migrations;
- testes executados e resultados;
- documentação/ADRs atualizados;
- lista de arquivos alterados;
- riscos residuais e pendências do proprietário;
- instruções manuais exatas, sem executá-las;
- plano de rollback específico.

Comece informando a fase entendida, os fatos verificados e o plano. Depois implemente somente o escopo autorizado e valide proporcionalmente ao risco.
```

