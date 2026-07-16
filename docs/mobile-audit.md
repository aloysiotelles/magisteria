# Auditoria móvel

Data: 16/07/2026. Branch: `codex/mobile-capacitor-hardening`.

## Estado encontrado

- Backend monolítico FastAPI/Python 3.12, executado no Railway por Docker/Uvicorn.
- Frontend web Jinja2 com JavaScript e CSS estáticos, renderizado pelo servidor; não existia `dist` autônomo.
- Persistência transacional em SQLite (`APP_DATABASE_FILE`) e índice documental SQLite separado no volume persistente.
- Autenticação web por token de sessão opaco em cookie `HttpOnly`, com duração de 30 dias.
- Asaas é o provedor para novas assinaturas web. Mercado Pago é integração legada.
- IA, indexação, documentos, quotas e regras de assinatura residem no backend.
- Build anterior: `python -m compileall -q app.py config.py services tests`.
- Deploy Railway preservado: `Dockerfile`, `railway.toml`, `/health` e volume não foram substituídos.

## Linha de base

- 55 testes passaram antes das alterações.
- A aplicação pública respondeu em `/health`, `/status` e `/versao` em verificação somente leitura.
- Node, Java, Android SDK e Xcode não estavam no `PATH` local. Foi usado o Node 24 do runtime do workspace.

## Compatibilidade com Capacitor

O HTML Jinja não podia ser usado diretamente como `webDir`. Foi criada a menor separação possível:

- `mobile/`: frontend TypeScript/Vite compilado;
- `mobile/dist`: saída de build, não versionada;
- `capacitor.config.ts`: configuração única do contêiner;
- `android/` e `ios/`: projetos nativos;
- FastAPI/Railway: backend único, preservado.

Não foram copiadas regras de negócio, prompts, quotas ou validações de pagamento para o cliente.

## Riscos encontrados e resposta

| Risco | Tratamento |
| --- | --- |
| Administrador inicial determinístico | Removido; exige `ADMIN_BOOTSTRAP_PASSWORD` forte e explícita |
| Sessões após troca de senha | Sessões web e tokens móveis revogados |
| Corrida de quotas | Reserva atômica com `BEGIN IMMEDIATE` |
| Reindexação por usuário comum | `require_admin` no endpoint legado |
| Diagnósticos com texto livre | Métricas tipadas, limpeza de legado e TTL |
| Webhook MP sem segredo | Fail-closed |
| Cookies inadequados em produção | `COOKIE_SECURE=true` documentado |
| WebView navegando externamente | Sem `allowedNavigation`; links passam por allowlist e Browser nativo |
| URL insegura em build | Validação bloqueia localhost/HTTP em produção |
| SQLite em múltiplas réplicas | Continuar com uma réplica; migrar dados transacionais antes de escalar |

## Responsividade e experiência

O frontend móvel usa safe areas, alvos mínimos de 44 px, layouts de 280 px em diante, redução de movimento, foco visível, retrato, estados de carregamento/offline/servidor, teclado redimensionável e ações nativas. A versão web Jinja permanece inalterada visualmente.

## Decisões

1. Capacitor 8 + Vite + TypeScript.
2. UI móvel compilada, sem carregar a home remota em uma WebView.
3. Tokens opacos curtos e refresh rotativo, armazenados em Keychain/Keystore.
4. Mesma API, usuários, banco, documentos e regras do Railway.
5. Asaas somente web; Play Billing/StoreKit ficam preparados, não ativados.
6. `br.com.seudominio.magisteria` é placeholder e deve ser trocado antes de criar apps nas lojas.

## Impacto esperado

O deploy web continua aceitando os fluxos existentes. O schema recebe tabelas de tokens móveis e auditoria mínima de exclusão de conta. O frontend móvel adiciona chamadas HTTPS, mas não requer uma segunda API nem um segundo banco.
