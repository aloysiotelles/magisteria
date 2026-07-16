# 4. Plano de implementação por etapas

## Fase 0 — Decisões e proteção imediata

Objetivo: remover riscos críticos antes de ampliar a superfície.

- responder às pendências do documento 11;
- verificar e rotacionar o bootstrap administrativo;
- adicionar rate limits, limites de body/upload e revogação de sessão;
- fechar webhook legado quando HMAC não estiver configurado;
- aplicar allowlist de URLs externas e cabeçalhos de segurança;
- definir política de dados, retenção, backup e restauração;
- congelar package name e bundle identifier definitivos.

Saída: produção web protegida, decisões registradas e critérios de aceite assinados. Nenhuma mudança de loja nesta fase.

## Fase 1 — Contrato do backend móvel

- criar `/api/v1` com OpenAPI e schemas de erro consistentes;
- implementar tokens móveis curtos + refresh rotativo e revogável;
- CORS por origem exata e TLS obrigatório;
- tornar quotas e idempotência transacionais;
- criar exclusão de conta e política de retenção;
- criar configuração remota, minimum version, maintenance e feature flags;
- adicionar testes de compatibilidade e migrações reversíveis.

Saída: cliente de teste consegue autenticar, consultar IA, baixar/compartilhar documento e gerenciar conta sem Jinja/cookie.

## Fase 2 — Entitlement e pagamentos

- normalizar `subscriptions`, `subscription_events` e `entitlements`;
- manter Asaas apenas no site;
- implementar Play Billing + validação server-side + RTDN;
- implementar StoreKit 2 + App Store Server Notifications/API;
- tratar restore, cancelamento, grace, expiração, reembolso e chargeback;
- decidir RevenueCat por ADR técnico/comercial;
- esconder qualquer CTA web não permitido nos builds nativos por capability/configuração server-side.

Saída: matriz de testes de assinatura aprovada em sandboxes das duas lojas.

## Fase 3 — Cliente web empacotável

- criar `mobile/` com TypeScript e build reproduzível;
- migrar login, pergunta/streaming, fontes, histórico, roteiro, slides e perfil;
- reutilizar tokens visuais, traduções e CSS onde fizer sentido;
- implementar estados loading/empty/error/offline e prevenção de clique duplo;
- garantir teclado, safe area, dark mode decidido e acessibilidade básica;
- testar no navegador contra staging.

Saída: `mobile/dist/index.html` autônomo, sem segredo e sem dependência de Jinja.

## Fase 4 — Capacitor Android

- instalar Capacitor estável compatível e registrar decisões de versão;
- `appId`, nome, `webDir=dist`, ícones e splash;
- botão voltar, lifecycle, network, browser externo, arquivos e share;
- Play Billing, deep links e secure storage;
- gerar AAB release e ativar Play App Signing;
- testes internos e fechados.

Saída: AAB assinado, testes automáticos e checklist Play sem P0.

## Fase 5 — Capacitor iOS

- executar em macOS com Xcode 26+ e SDK iOS 26+;
- configurar Bundle ID, capabilities, certificados e profile;
- safe areas, teclado, arquivos/share, links e secure storage;
- StoreKit 2 e restore;
- TestFlight interno e externo.

Saída: archive validado e checklist App Store sem P0.

## Fase 6 — Observabilidade e hardening

- métricas de latência, erro, quota, webhook e entitlement sem PII;
- alertas de falha de compra/reconciliação e fila de reprocessamento;
- testes de restauração de backup;
- revisão de permissões, SBOM/dependências e scan de segredos;
- testes de carga de IA, slides, upload e indexação;
- pentest focado em auth, billing, WebView e uploads.

## Fase 7 — Publicação gradual

- staging → internal → closed/TestFlight → produção gradual;
- Android em rollout por porcentagem; iOS com phased release;
- monitorar crash-free, login, purchase success, restore, erro IA e tickets;
- promover apenas após gates do documento 9.

## Dependências e ordem crítica

Conta/exclusão e entitlement devem preceder a UI final. IDs de pacote, titular legal e produtos de loja devem ser definidos antes de criar os projetos. O iOS depende de Mac/Xcode; este ambiente Windows não pode assinar nem enviar o archive iOS.

