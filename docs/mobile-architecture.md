# Arquitetura móvel

## Topologia

```text
Web/Jinja ───────────────┐
Android/Capacitor ───────┼─ HTTPS ─ FastAPI no Railway ─ SQLite/índice/Documentos
iOS/Capacitor ───────────┘                 ├─ OpenAI
                                           ├─ Asaas web
                                           └─ Play/Apple no futuro
```

`mobile/dist` é empacotado nos binários. Não há `server.url` de produção e o aplicativo não é um navegador apontando para o site.

## Componentes

- `mobile/src/config.ts`: URL única da API e allowlist de links.
- `mobile/src/api.ts`: timeout, refresh único, tratamento de 401, deduplicação de GET, streaming, downloads e upload em partes.
- `mobile/src/auth-store.ts`: sessão no armazenamento seguro nativo.
- `mobile/src/native.ts`: rede, voltar Android, Browser, Filesystem, Share e Splash.
- `mobile/src/main.ts`: apresentação e orquestração; não contém regra de quota ou assinatura.
- `services/auth_repository.py`: sessões móveis, rotação e revogação.
- `services/subscription_service.py`: normalização web/Android/iOS.

## Ambientes

| Ambiente | Arquivo/configuração | API |
| --- | --- | --- |
| Web local | `.env` backend | `http://127.0.0.1:8000` |
| Móvel local | `mobile/.env.development` | `http://127.0.0.1:8000` |
| Homologação | variável `VITE_API_BASE_URL` no CI | domínio HTTPS de homologação |
| Web produção | Railway `APP_PUBLIC_URL` | domínio Railway |
| Móvel produção | `mobile/.env.production` | domínio Railway HTTPS |

O build de produção falha se a API for local ou não usar HTTPS.

## Navegação e segurança

- Conteúdo principal: arquivos locais do bundle.
- API: `fetch` para a origem configurada.
- Links jurídicos/suporte: Browser nativo e hosts permitidos.
- Não há `allowedNavigation` para domínios remotos.
- Android desabilita cleartext e backup; iOS usa ATS sem exceção arbitrária.
- CSP do bundle limita conexão ao Railway e ao backend local de desenvolvimento.

## Persistência

O dispositivo armazena apenas o par de sessão e arquivos temporários gerados. Dados de usuário, histórico de acesso, assinaturas, documentos e quotas ficam no Railway. O refresh token e o access token são opacos; somente hashes ficam no banco.

## Escala

O bloqueio SQLite é suficiente para a implantação documentada de uma réplica. Antes de múltiplas réplicas, mover usuários, tokens, quotas, pagamentos e auditoria para PostgreSQL. O índice documental pode permanecer como artefato separado, desde que o backend continue sendo a única fonte de verdade.

## Rollback arquitetural

- Web: reverter commit/deploy sem depender de uma versão móvel.
- API: manter endpoints antigos durante pelo menos uma versão móvel publicada.
- Banco: usar migrações aditivas; não remover colunas/tabelas no mesmo release.
- App: pausar rollout e publicar correção com número de build maior; lojas não fazem downgrade direto.
