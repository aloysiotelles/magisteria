# Segurança móvel e backend

## Controles implementados

- Sem segredos no bundle; somente URL e IDs públicos podem usar `VITE_*`.
- Tokens opacos com hashes no banco, access curto, refresh rotativo e revogação de família.
- Keychain/Keystore por secure storage; sem tokens em `localStorage`.
- Web cookie `HttpOnly`, `SameSite=Lax` e opção `Secure` para Railway.
- CORS restrito às origens Capacitor configuradas e sem credentials.
- CSP, HSTS em HTTPS, nosniff, frame deny, referrer e permissions policy.
- HTTP claro/backup Android desabilitados; ATS iOS restrito.
- WebView sem lista de navegação remota; Browser nativo usa allowlist HTTPS.
- Limites por IP/rota em produção e quotas atômicas por usuário.
- Upload administrativo por extensão, path containment, chunks de até 5 MiB e sem permissão ampla.
- Diagnóstico RAG em métricas tipadas, sem pergunta, source name, motivo livre ou trace completo; TTL padrão de 14 dias.
- Webhooks Asaas autenticados e MP fail-closed.
- Release Android com minificação/resource shrinking.

## Achados corrigidos

1. Bootstrap administrativo determinístico.
2. Sessões antigas após troca de senha.
3. Quatro corridas de quota.
4. Reindexação sem papel administrativo.
5. Fallback de slide bloqueando event loop.
6. Retenção de texto sensível em diagnóstico.
7. Webhook Mercado Pago sem segredo.

O relatório técnico de correção fica no bundle da auditoria Codex Security em `artifacts/fix_report.md`.

## Ameaças residuais

- Administrador histórico em produção: proprietário deve confirmar rotação; o código não altera produção automaticamente.
- Rate limit em memória é por réplica. Em escala, mover para gateway/Redis/PostgreSQL.
- SQLite é um limite para múltiplas réplicas e alta concorrência.
- Imports e montagem final do PPTX ainda têm partes síncronas; uma fila de worker é recomendada sob carga.
- Textos legais/suporte ainda provisórios.
- Dependências devem ser auditadas a cada release.
- Root/jailbreak pode reduzir garantias do dispositivo; tokens curtos limitam impacto.

## Revisão por release

- `git grep` por `sk-`, tokens, senhas, certificados e chaves privadas.
- `pnpm audit --audit-level high` e revisão do lockfile.
- `pip`/dependências Python dentro das faixas do requirements.
- Android lint, manifest e App Bundle Explorer.
- Xcode Analyze, Privacy Report e target membership do privacy manifest.
- Testar CSP/CORS com origem permitida e não permitida.
- Confirmar que stack traces não são retornadas ao cliente.

## Incidente e revogação

Trocar a senha revoga sessões da conta. Para comprometimento amplo, rotacionar segredos no Railway, revogar tokens no banco, desativar integrações afetadas e publicar uma versão móvel superior. Nunca incluir o segredo novo em commit ou log.
