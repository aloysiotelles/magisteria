# 7. Matriz de riscos

Escala: probabilidade e impacto de 1 (baixo) a 5 (crítico). Nível = P × I. A avaliação considera o estado do código, não confirma valores/segredos atuais do Railway.

| ID | Risco | P | I | Nível | Tratamento | Gate |
|---|---|---:|---:|---:|---|---|
| R01 | Bootstrap administrativo previsível `Admin/3510` em banco novo ou não rotacionado | 5 | 5 | 25 crítico | Remover literal, convite/segredo one-time, rotação e auditoria autorizada | Antes de qualquer beta |
| R02 | Checkout web dentro do app viola billing das lojas | 4 | 5 | 20 crítico | Play Billing/StoreKit ou companion sem CTA conforme storefront | Antes da submissão |
| R03 | Ausência de exclusão de conta e política de privacidade | 5 | 4 | 20 crítico | Fluxo in-app + web, política e retenção verificadas | Antes da submissão |
| R04 | Usuário comum aciona reindexação e causa indisponibilidade | 4 | 4 | 16 alto | `require_admin`, fila, cooldown, auditoria | Antes do beta |
| R05 | Upload/parser/indexação sem orçamento; arquivo esparso/bomba | 4 | 5 | 20 crítico | Limite bytes/páginas/chunks/tempo, quota, staging de arquivo, worker isolado | Antes do beta |
| R06 | Corridas de quota multiplicam custo de IA/slides | 4 | 4 | 16 alto | Reserva atômica/idempotency key, reconciliação | Antes do beta público |
| R07 | Fallback de imagem bloqueia event loop | 4 | 4 | 16 alto | Worker/thread, limite e timeout; carga concorrente | Antes do beta |
| R08 | Sessão roubada sobrevive à troca de senha; cookie sem `Secure` | 3 | 4 | 12 alto | Session version/revoke-all, Secure, auth móvel rotativa | Antes do beta |
| R09 | Webhook Mercado Pago falha aberto/replay quando legado está parcialmente configurado | 3 | 4 | 12 alto | Fail closed, freshness, idempotência; desligar legado se não usado | Antes do beta |
| R10 | Diagnósticos persistem PII/segredos/saídas e crescem sem TTL | 4 | 4 | 16 alto | Redaction estrutural, minimização, TTL/purge e acesso auditado | Antes da política final |
| R11 | URL de checkout sem allowlist leva a phishing/WebView hostil | 2 | 4 | 8 médio | Parse e allowlist no servidor/cliente, browser externo | Antes do beta |
| R12 | Resposta RAG passa em falhas do revisor/JSON inválido | 3 | 3 | 9 médio | Fail closed/answer-safe, testes adversariais | Antes do beta |
| R13 | SQLite/volume único sem restauração testada perde usuários/assinaturas | 3 | 5 | 15 alto | Backup, restore drill, RPO/RTO; PostgreSQL antes de escala | Antes da produção móvel |
| R14 | App antigo quebra após mudança de API | 4 | 4 | 16 alto | `/api/v1`, compatibilidade, minimum version e feature flags | Antes do primeiro release |
| R15 | Segredo embarcado no bundle/CI | 3 | 5 | 15 alto | Secret scan de AAB/IPA, vault, build config pública mínima | Todo release |
| R16 | App rejeitado como site empacotado | 3 | 4 | 12 alto | UI empacotada e capacidades móveis reais documentadas | Antes do Review |
| R17 | Certificados/keystore perdidos ou expostos | 2 | 5 | 10 alto | Play App Signing, backup controlado, rotação e papéis | Antes do release |
| R18 | Dependência do Mac/Xcode atrasa iOS | 4 | 3 | 12 alto | Garantir Mac/CI e conta cedo | Fase 0 |
| R19 | Notificações de loja/webhooks fora de ordem corrompem entitlement | 3 | 5 | 15 alto | Ledger idempotente, ordenação por tempo/versão e reconciliação periódica | Antes de IAP prod |
| R20 | Atalho de deploy publica arquivos não revisados ou segredos | 3 | 4 | 12 alto | Remover `git add -A`, mostrar diff, branch guard e secret scan | Antes de ampliar equipe |

## Cadeias críticas

O risco mais importante não é um item isolado: credencial admin previsível → upload administrativo → arquivo esparso/DOCX/PDF adversarial → reindexação → indisponibilidade do único container. Corrigir somente o parser ou somente a senha deixa parte da cadeia viva.

Outra cadeia é corrida de quota → múltiplas gerações de slides → fallback CPU-bound → event loop bloqueado → health/login/IA indisponíveis. Reserva atômica e isolamento de trabalho são controles complementares.

## Risco residual aceito somente com decisão explícita

- permanecer em SQLite durante piloto com uma réplica;
- não usar RevenueCat e manter duas integrações nativas próprias;
- oferecer apenas login para assinantes web em determinadas storefronts;
- adiar dark mode ou notificações, desde que a acessibilidade mínima seja cumprida.

Cada aceitação deve registrar proprietário, data de expiração, monitoramento e plano de saída.

